"""
Spotify PKCE OAuth2 Client & Automatic Active Windows Spotify Session Connector.
- Automatically connects on boot to the user's running Spotify Desktop app via Windows
  Global System Media Transport Controls (GSMTC / WinRT), reading live Title, Artist, Album,
  PlaybackStatus, Position (progress_ms), and EndTime (duration_ms).
- Automatically resolves `(title, artist)` to its official Spotify Track ID and ReccoBeats
  measured audio features via MusicBrainz ISRC -> ReccoBeats lookup (zero API keys needed).
- Also supports full Spotify Web API OAuth2 PKCE (`http://127.0.0.1:8765/callback`) when configured.
"""
from __future__ import annotations

import json
import re
import subprocess
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx
import spotipy
from spotipy.exceptions import SpotifyException
from spotipy.oauth2 import SpotifyPKCE

from config import SPOTIFY_CACHE_PATH, get_secret
from database import Database

SPOTIFY_SCOPES = (
    "user-read-currently-playing "
    "user-read-playback-state "
    "user-read-recently-played "
    "playlist-modify-private"
)

USER_AGENT = "PulseMind/1.0 (https://github.com/pulsemind-local)"


class SpotifyClientWrapper:
    def __init__(self, redirect_uri: str = "http://127.0.0.1:8765/callback") -> None:
        self.redirect_uri = redirect_uri
        self._auth_manager: Optional[SpotifyPKCE] = None
        self._sp: Optional[spotipy.Spotify] = None

    def _build_auth_manager(self) -> Optional[SpotifyPKCE]:
        client_id = get_secret("spotify_client_id")
        if not client_id:
            return None
        return SpotifyPKCE(
            client_id=client_id,
            redirect_uri=self.redirect_uri,
            scope=SPOTIFY_SCOPES,
            cache_path=str(SPOTIFY_CACHE_PATH),
            open_browser=False,
        )

    def is_configured(self) -> bool:
        return bool(get_secret("spotify_client_id"))

    def is_authenticated(self) -> bool:
        auth = self._build_auth_manager()
        if not auth:
            return False
        try:
            token_info = auth.get_cached_token()
            return token_info is not None
        except Exception:
            return False

    def get_authorize_url(self) -> Optional[str]:
        auth = self._build_auth_manager()
        if not auth:
            return None
        self._auth_manager = auth
        return auth.get_authorize_url()

    def handle_oauth_callback(self, code: str) -> bool:
        auth = self._auth_manager or self._build_auth_manager()
        if not auth:
            return False
        try:
            auth.get_access_token(code=code, check_cache=False)
            self._sp = spotipy.Spotify(auth_manager=auth, retries=2, status_retries=2, backoff_factor=0.5)
            return True
        except Exception:
            return False

    def _client(self) -> Optional[spotipy.Spotify]:
        if self._sp is not None:
            return self._sp
        auth = self._build_auth_manager()
        if not auth:
            return None
        token = auth.get_cached_token()
        if not token:
            return None
        self._sp = spotipy.Spotify(auth_manager=auth, retries=2, status_retries=2, backoff_factor=0.5)
        return self._sp

    def get_current_playback(self) -> Optional[Dict[str, Any]]:
        """
        Returns normalized playback dict from Spotify Web API if authenticated.
        """
        sp = self._client()
        if not sp:
            return None
        try:
            pb = sp.current_user_playing_track()
            if not pb or not pb.get("item"):
                return None
            item = pb["item"]
            if item.get("type") != "track" or not item.get("id"):
                return None
            artists = ", ".join(a["name"] for a in item.get("artists", []) if a.get("name"))
            images = item.get("album", {}).get("images", [])
            art_url = images[0]["url"] if images else ""
            return {
                "track_id": item["id"],
                "title": item.get("name", "Unknown"),
                "artist": artists or "Unknown Artist",
                "album": item.get("album", {}).get("name", ""),
                "album_art_url": art_url,
                "duration_ms": int(item.get("duration_ms") or 200000),
                "progress_ms": int(pb.get("progress_ms") or 0),
                "is_playing": bool(pb.get("is_playing", False)),
                "spotify_url": item.get("external_urls", {}).get(
                    "spotify", f"https://open.spotify.com/track/{item['id']}"
                ),
                "source": "spotify_pkce",
            }
        except SpotifyException as e:
            if e.http_status == 429:
                retry_after = int(e.headers.get("Retry-After", 5)) if e.headers else 5
                time.sleep(min(retry_after, 15))
            return None
        except Exception:
            return None

    def get_recently_played(self, limit: int = 50) -> List[Dict[str, Any]]:
        sp = self._client()
        if not sp:
            return []
        try:
            res = sp.current_user_recently_played(limit=min(50, limit))
            items = res.get("items", []) if res else []
            parsed = []
            for entry in items:
                track = entry.get("item") or entry.get("track")
                if not track or not track.get("id"):
                    continue
                played_at_str = entry.get("played_at", "")
                try:
                    dt = datetime.fromisoformat(played_at_str.replace("Z", "+00:00"))
                    played_ts = dt.timestamp()
                except Exception:
                    played_ts = time.time()
                artists = ", ".join(a["name"] for a in track.get("artists", []) if a.get("name"))
                images = track.get("album", {}).get("images", [])
                art_url = images[0]["url"] if images else ""
                parsed.append(
                    {
                        "track_id": track["id"],
                        "title": track.get("name", "Unknown"),
                        "artist": artists or "Unknown Artist",
                        "album": track.get("album", {}).get("name", ""),
                        "album_art_url": art_url,
                        "duration_ms": int(track.get("duration_ms") or 200000),
                        "played_at_ts": played_ts,
                        "spotify_url": track.get("external_urls", {}).get(
                            "spotify", f"https://open.spotify.com/track/{track['id']}"
                        ),
                    }
                )
            return parsed
        except Exception:
            return []

    def search_track(self, title: str, artist: str = "") -> Optional[Dict[str, Any]]:
        sp = self._client()
        if not sp:
            return None
        query = f"track:{title} artist:{artist}".strip() if artist else title
        try:
            res = sp.search(q=query, type="track", limit=5)
            items = res.get("tracks", {}).get("items", [])
            if not items and artist:
                res = sp.search(q=f"{title} {artist}", type="track", limit=5)
                items = res.get("tracks", {}).get("items", [])
            if not items:
                return None
            item = items[0]
            artists = ", ".join(a["name"] for a in item.get("artists", []) if a.get("name"))
            images = item.get("album", {}).get("images", [])
            art_url = images[0]["url"] if images else ""
            return {
                "track_id": item["id"],
                "title": item.get("name", title),
                "artist": artists or artist,
                "album": item.get("album", {}).get("name", ""),
                "album_art_url": art_url,
                "duration_ms": int(item.get("duration_ms") or 200000),
                "spotify_url": item.get("external_urls", {}).get(
                    "spotify", f"https://open.spotify.com/track/{item['id']}"
                ),
            }
        except Exception:
            return None

    def create_private_playlist(
        self,
        name: str,
        description: str,
        track_ids: List[str],
    ) -> Optional[str]:
        sp = self._client()
        if not sp or not track_ids:
            return None
        try:
            me = sp.current_user()
            user_id = me["id"]
            playlist = sp.user_playlist_create(
                user=user_id,
                name=name,
                public=False,
                description=description[:300],
            )
            playlist_id = playlist["id"]
            uris = [
                f"spotify:track:{tid}"
                for tid in track_ids
                if tid and not tid.startswith("winmedia_") and not tid.startswith("local_")
            ]
            if uris:
                sp.playlist_add_items(playlist_id, uris[:100])
            return playlist.get("external_urls", {}).get(
                "spotify", f"https://open.spotify.com/playlist/{playlist_id}"
            )
        except Exception:
            return None


_GSMTC_POWERSHELL_SCRIPT = r"""
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$asTaskGeneric = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
Function Await($WinRtTask, $ResultType) {
    $asTask = $asTaskGeneric.MakeGenericMethod($ResultType)
    $netTask = $asTask.Invoke($null, @($WinRtTask))
    $netTask.Wait(-1) | Out-Null
    $netTask.Result
}
[Windows.Media.Control.GlobalSystemMediaTransportControlsSessionManager,Windows.Media.Control,ContentType=WindowsRuntime] | Out-Null
$mgr = Await ([Windows.Media.Control.GlobalSystemMediaTransportControlsSessionManager]::RequestAsync()) ([Windows.Media.Control.GlobalSystemMediaTransportControlsSessionManager])
$sessions = $mgr.GetSessions()
foreach ($s in $sessions) {
    if ($s.SourceAppUserModelId -match 'Spotify') {
        $info = Await ($s.TryGetMediaPropertiesAsync()) ([Windows.Media.Control.GlobalSystemMediaTransportControlsSessionMediaProperties])
        $pb = $s.GetPlaybackInfo()
        $tl = $s.GetTimelineProperties()
        [PSCustomObject]@{
            App = $s.SourceAppUserModelId
            Title = $info.Title
            Artist = $info.Artist
            Album = $info.AlbumTitle
            Status = $pb.PlaybackStatus.ToString()
            PosMs = [int]$tl.Position.TotalMilliseconds
            EndMs = [int]$tl.EndTime.TotalMilliseconds
        } | ConvertTo-Json -Compress
        break
    }
}
"""


def resolve_track_via_musicbrainz_reccobeats(
    title: str,
    artist: str,
    db: Optional[Database] = None,
) -> Optional[Dict[str, Any]]:
    """
    Zero-key resolver: maps `(title, artist)` -> MusicBrainz ISRC -> ReccoBeats Spotify Track ID
    and caches the measured ReccoBeats audio features under that Spotify Track ID.
    """
    cache_key = f"mb_rb_resolve::{artist.lower().strip()}::{title.lower().strip()}"
    if db:
        cached = db.get_cache(cache_key)
        if cached:
            return cached

    clean_title = re.sub(r"\s*\(.*?\)\s*|\s*-\s*Remastered.*$", "", title, flags=re.I).strip() or title
    primary_artist = artist.split(",")[0].strip() or artist
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}

    try:
        with httpx.Client(timeout=8.0, headers=headers, follow_redirects=True) as client:
            mb_resp = client.get(
                "https://musicbrainz.org/ws/2/recording/",
                params={
                    "query": f"recording:{clean_title} AND artist:{primary_artist}",
                    "fmt": "json",
                    "limit": 5,
                },
            )
            if mb_resp.status_code != 200:
                return None
            recordings = mb_resp.json().get("recordings", [])
            isrcs: List[str] = []
            for rec in recordings:
                for code in rec.get("isrcs", []):
                    if code and code not in isrcs:
                        isrcs.append(code)

            if not isrcs:
                return None

            rb_resp = client.get(
                "https://api.reccobeats.com/v1/audio-features",
                params={"ids": ",".join(isrcs[:5])},
            )
            if rb_resp.status_code != 200:
                return None
            content = rb_resp.json().get("content", [])
            if not content:
                return None

            first = content[0]
            href = first.get("href") or ""
            m = re.search(r"spotify\.com/track/([A-Za-z0-9]+)", href)
            if not m:
                return None
            spotify_tid = m.group(1)

            # Pre-populate the ReccoBeats audio-features cache for this Spotify Track ID!
            if db:
                af_payload = {
                    "tempo": float(first.get("tempo") or 120.0),
                    "energy": float(first.get("energy") or 0.5),
                    "danceability": float(first.get("danceability") or 0.5),
                    "valence": float(first.get("valence") or 0.5),
                    "acousticness": float(first.get("acousticness") or 0.2),
                    "instrumentalness": float(first.get("instrumentalness") or 0.0),
                    "speechiness": float(first.get("speechiness") or 0.05),
                    "loudness": float(first.get("loudness") or -8.0),
                    "key": int(first.get("key") if first.get("key") is not None else 0),
                    "mode": int(first.get("mode") if first.get("mode") is not None else 1),
                    "source": "reccobeats",
                    "confidence": 0.95,
                }
                db.set_cache(f"reccobeats_af::{spotify_tid}", af_payload, ttl_seconds=86400 * 30)

            resolved = {
                "track_id": spotify_tid,
                "spotify_url": f"https://open.spotify.com/track/{spotify_tid}",
            }
            if db:
                db.set_cache(cache_key, resolved, ttl_seconds=86400 * 30)
            return resolved
    except Exception:
        return None


def get_windows_media_session_track(db: Optional[Database] = None) -> Optional[Dict[str, Any]]:
    """
    Connects directly to the active Windows Spotify Desktop session via WinRT GSMTC
    (`GlobalSystemMediaTransportControlsSessionManager`), returning live Title, Artist,
    Album, Position (`progress_ms`), Duration (`duration_ms`), and Playing status, and
    resolving the official Spotify Track ID via MusicBrainz + ReccoBeats.
    """
    try:
        out = subprocess.check_output(
            ["powershell", "-NoProfile", "-Command", _GSMTC_POWERSHELL_SCRIPT],
            timeout=4.0,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        ).decode("utf-8", errors="ignore").strip()

        if out:
            # Take last JSON line in case of any preamble
            lines = [line.strip() for line in out.splitlines() if line.strip().startswith("{")]
            if lines:
                data = json.loads(lines[-1])
                title = (data.get("Title") or "").strip()
                artist = (data.get("Artist") or "").strip()
                album = (data.get("Album") or "").strip()
                status = (data.get("Status") or "").strip()
                pos_ms = max(0, int(data.get("PosMs") or 0))
                end_ms = int(data.get("EndMs") or 200000)
                if end_ms <= 0:
                    end_ms = 200000

                if title and artist:
                    pseudo_id = f"winmedia_{abs(hash(f'{artist.lower()}::{title.lower()}')) % 1000000000}"
                    spotify_url = f"https://open.spotify.com/search/{title}%20{artist}"

                    resolved = resolve_track_via_musicbrainz_reccobeats(title, artist, db=db)
                    if resolved:
                        pseudo_id = resolved["track_id"]
                        spotify_url = resolved["spotify_url"]

                    return {
                        "track_id": pseudo_id,
                        "title": title,
                        "artist": artist,
                        "album": album,
                        "album_art_url": "",
                        "duration_ms": end_ms,
                        "progress_ms": pos_ms,
                        "is_playing": status.lower() == "playing",
                        "spotify_url": spotify_url,
                        "source": "active_spotify_desktop",
                    }
    except Exception:
        pass
    return None
