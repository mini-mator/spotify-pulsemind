"""
FastAPI Backend for PulseMind Local Web Dashboard (`http://127.0.0.1:8765`).
Provides REST endpoints for:
- Live Now-Playing & Sonic/Lyrical Inspector
- Taste DNA Analytics (Controlled Vocabulary distributions, skip/repeat metrics)
- Two-Step Playlist Studio (Preview Draft -> Confirm Private Spotify Export)
- OAuth2 PKCE Callback (`http://127.0.0.1:8765/callback`)
- Secure Keyring Settings & Tunable Taste Weights
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from analyzer import SongProfiler
from config import AppSettings, TasteWeightsConfig, get_secret, set_secret
from database import Database
from recommender import TasteAndRecommendationEngine
from schemas import (
    BEAT_ARCHETYPE_LABELS,
    LYRICAL_THEME_LABELS,
    BeatArchetype,
    LyricalTheme,
)
from spotify_client import SpotifyClientWrapper
from tracker import PlaybackTracker

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
STATIC_DIR.mkdir(parents=True, exist_ok=True)

db = Database()
db.purge_demo_data()
profiler = SongProfiler(db)
spotify_client = SpotifyClientWrapper(redirect_uri=db.get_settings().redirect_uri)
tracker = PlaybackTracker(
    db=db,
    spotify=spotify_client,
    on_track_need_profile=lambda snap: profiler.profile_track(snap),
)
recommender = TasteAndRecommendationEngine(db=db, profiler=profiler, spotify=spotify_client)

app = FastAPI(title="PulseMind Spotify Tracker & Recommender", version="1.0.0")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


class PlaylistPreviewRequest(BaseModel):
    prompt: str = ""
    beat_archetype: str = "any"
    lyrical_theme: str = "any"
    target_bpm: Optional[float] = None
    target_energy: Optional[float] = None
    target_valence: Optional[float] = None
    playlist_size: int = 8


class ManualAnalyzeRequest(BaseModel):
    track_id: str = ""
    title: str
    artist: str


class SimulatePlayRequest(BaseModel):
    track_id: str
    action: str = "full_play"  # 'full_play', 'skip', 'repeat_loop'


class SettingsUpdateRequest(BaseModel):
    llm_provider: str = "ollama"
    llm_model: str = "llama3.2"
    ollama_base_url: str = "http://127.0.0.1:11434"
    send_lyrics_to_cloud_llm: bool = False
    enable_windows_media_fallback: bool = False
    demo_mode: bool = True
    weights: TasteWeightsConfig
    # Optional secrets (written to OS keyring only if non-empty)
    spotify_client_id: Optional[str] = None
    llm_api_key: Optional[str] = None
    lastfm_api_key: Optional[str] = None


@app.on_event("startup")
def on_startup() -> None:
    import threading
    from analyzer import ensure_local_llama_server

    db.purge_demo_data()
    tracker.start_background_loop()

    def _upgrade_existing_profiles() -> None:
        ensure_local_llama_server(wait_seconds=8.0)
        # Only upgrade the user's actually played tracks so llama-server is immediately free for live playback!
        played_ids = {ev["track_id"] for ev in db.get_play_events(include_demo=False, limit=30)}
        if tracker.active:
            played_ids.add(tracker.active.track_id)
        for tid in played_ids:
            prof = db.get_track_profile(tid)
            if not prof:
                continue
            if prof.llm_provider_used not in ("local_llama_llm", "ollama_llm", "gemini", "openai"):
                try:
                    profiler.profile_track(
                        {
                            "track_id": prof.track_id,
                            "title": prof.title,
                            "artist": prof.artist,
                            "album": prof.album,
                            "album_art_url": prof.album_art_url,
                            "duration_ms": prof.duration_ms,
                            "spotify_url": prof.spotify_url,
                        },
                        force_refresh=True,
                    )
                except Exception:
                    pass

    threading.Thread(target=_upgrade_existing_profiles, name="PulseMindProfileUpgrader", daemon=True).start()


@app.get("/", response_class=HTMLResponse)
def index() -> FileResponse:
    return FileResponse(str(STATIC_DIR / "index.html"))


@app.get("/callback")
def spotify_oauth_callback(code: Optional[str] = Query(default=None), error: Optional[str] = Query(default=None)):
    if error or not code:
        return RedirectResponse(url="/?auth=error")
    ok = spotify_client.handle_oauth_callback(code)
    if ok:
        try:
            tracker.backfill_recent_plays()
        except Exception:
            pass
        return RedirectResponse(url="/?auth=success")
    return RedirectResponse(url="/?auth=failed")


@app.get("/api/vocabularies")
def get_vocabularies() -> Dict[str, Any]:
    return {
        "beat_archetypes": [
            {"id": k.value, "label": v} for k, v in BEAT_ARCHETYPE_LABELS.items()
        ],
        "lyrical_themes": [
            {"id": k.value, "label": v} for k, v in LYRICAL_THEME_LABELS.items()
        ],
    }


@app.get("/api/status")
def get_status() -> Dict[str, Any]:
    settings = db.get_settings()
    if tracker.active is None and not tracker.paused_by_user:
        try:
            tracker.poll_once(record_initial_if_empty=True)
        except Exception:
            pass
    active_state = tracker.active
    active_profile = None

    if active_state:
        prof = profiler.profile_track(
            {
                "track_id": active_state.track_id,
                "title": active_state.title,
                "artist": active_state.artist,
                "album": active_state.album,
                "album_art_url": active_state.album_art_url,
                "duration_ms": active_state.duration_ms,
                "spotify_url": active_state.spotify_url,
            }
        )
        active_profile = _serialize_profile(prof)
        now_playing = {
            "is_live": True,
            "is_playing": active_state.is_playing,
            "progress_ms": active_state.last_progress_ms,
            "max_progress_ms": active_state.max_progress_ms,
            "duration_ms": active_state.duration_ms,
            "repeat_count": active_state.repeat_count,
            "source": active_state.source,
            "profile": active_profile,
        }
    else:
        recent = db.get_play_events(include_demo=False, limit=1)
        if recent:
            tid = recent[0]["track_id"]
            prof = db.get_track_profile(tid)
            now_playing = {
                "is_live": False,
                "is_playing": False,
                "progress_ms": recent[0]["listened_ms"],
                "max_progress_ms": recent[0]["listened_ms"],
                "duration_ms": recent[0]["duration_ms"],
                "repeat_count": recent[0]["repeat_count"],
                "source": recent[0]["source"],
                "profile": _serialize_profile(prof) if prof else None,
            }
        else:
            now_playing = None

    return {
        "tracker_paused": tracker.paused_by_user,
        "spotify_configured": spotify_client.is_configured(),
        "spotify_authenticated": spotify_client.is_authenticated(),
        "desktop_session_active": active_state is not None,
        "llm_provider": settings.llm_provider,
        "privacy_mode": (
            "local_only"
            if settings.llm_provider in ("ollama", "heuristic") or not settings.send_lyrics_to_cloud_llm
            else "cloud_lyrics_enabled"
        ),
        "now_playing": now_playing,
    }


def _serialize_profile(prof) -> Dict[str, Any]:
    d = prof.model_dump()
    d["beat_label"] = BEAT_ARCHETYPE_LABELS.get(prof.interpretation.beat_archetype, "")
    d["primary_theme_label"] = LYRICAL_THEME_LABELS.get(prof.interpretation.primary_theme, "")
    d["secondary_theme_label"] = (
        LYRICAL_THEME_LABELS.get(prof.interpretation.secondary_theme, "")
        if prof.interpretation.secondary_theme
        else None
    )
    return d


@app.post("/api/tracker/toggle")
def toggle_tracker() -> Dict[str, Any]:
    tracker.paused_by_user = not tracker.paused_by_user
    return {"tracker_paused": tracker.paused_by_user}


@app.get("/api/spotify/auth-url")
def get_spotify_auth_url() -> Dict[str, Any]:
    url = spotify_client.get_authorize_url()
    if not url:
        raise HTTPException(
            status_code=400,
            detail="Spotify Client ID is not configured yet. Add it in Settings first.",
        )
    return {"authorize_url": url}


@app.get("/api/taste-dna")
def get_taste_dna() -> Dict[str, Any]:
    return recommender.compute_taste_dna()


@app.get("/api/history")
def get_history(limit: int = Query(default=40, ge=1, le=200)) -> Dict[str, Any]:
    events = db.get_play_events(include_demo=False, limit=limit)
    for ev in events:
        interp = ev["interpretation"]
        try:
            b_enum = BeatArchetype(interp.get("beat_archetype", "other"))
        except ValueError:
            b_enum = BeatArchetype.OTHER
        try:
            t_enum = LyricalTheme(interp.get("primary_theme", "other"))
        except ValueError:
            t_enum = LyricalTheme.OTHER
        ev["beat_label"] = BEAT_ARCHETYPE_LABELS.get(b_enum, b_enum.value)
        ev["theme_label"] = interp.get("specific_theme_headline") or LYRICAL_THEME_LABELS.get(t_enum, t_enum.value)
        ev["macro_theme_label"] = LYRICAL_THEME_LABELS.get(t_enum, t_enum.value)
    return {"events": events}


@app.post("/api/analyze-track")
def analyze_track_endpoint(req: ManualAnalyzeRequest) -> Dict[str, Any]:
    tid = req.track_id.strip()
    meta: Dict[str, Any] = {
        "track_id": tid or f"manual_{abs(hash(f'{req.artist}::{req.title}')) % 100000000}",
        "title": req.title.strip(),
        "artist": req.artist.strip(),
        "duration_ms": 200000,
    }
    if not tid and spotify_client.is_authenticated():
        found = spotify_client.search_track(req.title, req.artist)
        if found:
            meta.update(found)

    prof = profiler.profile_track(meta, force_refresh=True)
    return {"profile": _serialize_profile(prof)}


@app.post("/api/simulate-event")
def simulate_play_event(req: SimulatePlayRequest) -> Dict[str, Any]:
    prof = db.get_track_profile(req.track_id)
    if not prof:
        raise HTTPException(status_code=404, detail="Track profile not found")

    if req.action == "skip":
        listened_ms = 14000
        was_skipped = True
        repeats = 0
    elif req.action == "repeat_loop":
        listened_ms = prof.duration_ms
        was_skipped = False
        repeats = 2
    else:
        listened_ms = prof.duration_ms
        was_skipped = False
        repeats = 0

    event_id = db.record_play_event(
        track_id=prof.track_id,
        listened_ms=listened_ms,
        duration_ms=prof.duration_ms,
        was_skipped=was_skipped,
        repeat_count=repeats,
        played_at_ts=time.time(),
        source="simulated_live",
        is_demo=False,
    )
    return {
        "status": "recorded",
        "event_id": event_id,
        "action": req.action,
        "track": _serialize_profile(prof),
    }


@app.post("/api/playlist/preview")
def create_playlist_preview(req: PlaylistPreviewRequest) -> Dict[str, Any]:
    draft = recommender.generate_personalized_playlist(
        prompt=req.prompt,
        beat_archetype=req.beat_archetype,
        lyrical_theme=req.lyrical_theme,
        target_bpm=req.target_bpm,
        target_energy=req.target_energy,
        target_valence=req.target_valence,
        playlist_size=req.playlist_size,
    )
    return {"draft": draft}


@app.get("/api/playlist/drafts")
def get_playlist_drafts() -> Dict[str, Any]:
    return {"drafts": db.list_playlist_drafts(limit=15)}


@app.post("/api/playlist/export/{draft_id}")
def confirm_playlist_export(draft_id: str) -> Dict[str, Any]:
    draft = db.get_playlist_draft(draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Playlist draft not found")
    if not spotify_client.is_authenticated():
        raise HTTPException(
            status_code=400,
            detail="Connect your Spotify account via PKCE in Settings before exporting playlists.",
        )

    track_ids = [t["track_id"] for t in draft["tracks"]]
    url = spotify_client.create_private_playlist(
        name=draft["name"],
        description=draft["description"],
        track_ids=track_ids,
    )
    if not url:
        raise HTTPException(status_code=502, detail="Failed to create private playlist on Spotify.")
    db.mark_draft_exported(draft_id, url)
    return {"status": "exported", "spotify_url": url, "draft": db.get_playlist_draft(draft_id)}


@app.get("/api/settings")
def read_settings() -> Dict[str, Any]:
    s = db.get_settings()
    return {
        "settings": s.model_dump(),
        "secrets_status": {
            "has_spotify_client_id": bool(get_secret("spotify_client_id")),
            "spotify_client_id_masked": _mask(get_secret("spotify_client_id")),
            "has_llm_api_key": bool(get_secret("llm_api_key")),
            "llm_api_key_masked": _mask(get_secret("llm_api_key")),
            "has_lastfm_api_key": bool(get_secret("lastfm_api_key")),
            "lastfm_api_key_masked": _mask(get_secret("lastfm_api_key")),
        },
    }


@app.post("/api/settings")
def update_settings(req: SettingsUpdateRequest) -> Dict[str, Any]:
    current = db.get_settings()
    current.llm_provider = req.llm_provider
    current.llm_model = req.llm_model
    current.ollama_base_url = req.ollama_base_url
    current.send_lyrics_to_cloud_llm = req.send_lyrics_to_cloud_llm
    current.enable_windows_media_fallback = req.enable_windows_media_fallback
    current.demo_mode = req.demo_mode
    current.weights = req.weights
    db.save_settings(current)

    if req.spotify_client_id is not None and req.spotify_client_id.strip() != "":
        set_secret("spotify_client_id", req.spotify_client_id)
    if req.llm_api_key is not None and req.llm_api_key.strip() != "":
        set_secret("llm_api_key", req.llm_api_key)
    if req.lastfm_api_key is not None and req.lastfm_api_key.strip() != "":
        set_secret("lastfm_api_key", req.lastfm_api_key)

    return read_settings()


def _mask(secret: str) -> str:
    if not secret:
        return ""
    if len(secret) <= 6:
        return "***"
    return f"{secret[:4]}...{secret[-3:]}"
