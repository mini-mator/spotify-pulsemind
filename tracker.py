"""
Playback Tracker State Machine for PulseMind.
Handles:
1. Skip Detection: Inferred from `max_progress_ms / duration_ms` when the track changes.
   Treats under `skip_min_ms` (30s) OR under `skip_min_ratio` (50%) as a skip.
2. Repeat-Loop Detection: Detects when the same `track_id` drops from >= `skip_min_ms`
   back near 0 (< `repeat_restart_threshold_ms`), incrementing `repeat_count`.
3. Recently-Played Gap Backfill: Uses Spotify's last-50 recently played tracks to fill gaps
   when the app starts or wakes from sleep.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional

from config import TasteWeightsConfig
from database import Database
from spotify_client import SpotifyClientWrapper, get_windows_media_session_track


@dataclass
class ActiveTrackState:
    track_id: str
    title: str
    artist: str
    album: str
    album_art_url: str
    duration_ms: int
    spotify_url: str
    source: str
    started_at_ts: float = field(default_factory=time.time)
    last_progress_ms: int = 0
    max_progress_ms: int = 0
    is_playing: bool = True
    repeat_count: int = 0
    accumulated_wall_ms: int = 0
    last_poll_ts: float = field(default_factory=time.time)


def is_track_skipped(
    listened_ms: int,
    duration_ms: int,
    weights: TasteWeightsConfig,
) -> bool:
    """
    Pure logic function for skip classification (unit-tested).
    Treats under `skip_min_ms` (default 30,000 ms) OR under `skip_min_ratio` (default 50%)
    as a skip.
    """
    if duration_ms <= 0:
        return False
    completion_ratio = listened_ms / float(duration_ms)
    if listened_ms < weights.skip_min_ms or completion_ratio < weights.skip_min_ratio:
        return True
    return False


def is_repeat_restart(
    previous_max_progress_ms: int,
    current_progress_ms: int,
    weights: TasteWeightsConfig,
) -> bool:
    """
    Pure logic function for repeat-loop detection (unit-tested).
    If the same track was previously heard past `skip_min_ms` (e.g. >=30s)
    and its progress suddenly drops near 0 (< `repeat_restart_threshold_ms`, e.g. 15s),
    we classify it as a repeat loop!
    """
    return (
        previous_max_progress_ms >= weights.skip_min_ms
        and current_progress_ms < weights.repeat_restart_threshold_ms
        and (previous_max_progress_ms - current_progress_ms) >= 20000
    )


class PlaybackTracker:
    def __init__(
        self,
        db: Database,
        spotify: SpotifyClientWrapper,
        on_track_need_profile: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> None:
        self.db = db
        self.spotify = spotify
        self.on_track_need_profile = on_track_need_profile
        self.active: Optional[ActiveTrackState] = None
        self.paused_by_user: bool = False
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._last_backfill_ts: float = 0.0

    def process_playback_snapshot(
        self,
        snapshot: Optional[Dict[str, Any]],
        now_ts: Optional[float] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Feeds a playback observation into the state machine.
        Returns a summary dict if a completed/skipped play event was committed to DB.
        """
        now = now_ts if now_ts is not None else time.time()
        settings = self.db.get_settings()
        weights = settings.weights

        if snapshot is None:
            return None

        tid = snapshot["track_id"]
        prog_ms = int(snapshot.get("progress_ms") or 0)
        dur_ms = int(snapshot.get("duration_ms") or 200000)
        is_playing = bool(snapshot.get("is_playing", True))

        # Case 1: First track observed
        if self.active is None:
            self.active = ActiveTrackState(
                track_id=tid,
                title=snapshot.get("title", "Unknown"),
                artist=snapshot.get("artist", "Unknown"),
                album=snapshot.get("album", ""),
                album_art_url=snapshot.get("album_art_url", ""),
                duration_ms=dur_ms,
                spotify_url=snapshot.get("spotify_url", ""),
                source=snapshot.get("source", "spotify_pkce"),
                started_at_ts=now,
                last_progress_ms=prog_ms,
                max_progress_ms=prog_ms,
                is_playing=is_playing,
                repeat_count=0,
                last_poll_ts=now,
            )
            if self.on_track_need_profile:
                self.on_track_need_profile(snapshot)
            return None

        # Case 2: Same track still active
        if self.active.track_id == tid:
            if is_repeat_restart(self.active.max_progress_ms, prog_ms, weights):
                self.active.repeat_count += 1
                self.active.max_progress_ms = prog_ms
            else:
                self.active.max_progress_ms = max(self.active.max_progress_ms, prog_ms)
            self.active.last_progress_ms = prog_ms
            self.active.is_playing = is_playing
            self.active.last_poll_ts = now
            return None

        # Case 3: Track changed! Commit the previous track play event
        committed = self._commit_active_track(now, weights)

        # Start tracking the new track
        self.active = ActiveTrackState(
            track_id=tid,
            title=snapshot.get("title", "Unknown"),
            artist=snapshot.get("artist", "Unknown"),
            album=snapshot.get("album", ""),
            album_art_url=snapshot.get("album_art_url", ""),
            duration_ms=dur_ms,
            spotify_url=snapshot.get("spotify_url", ""),
            source=snapshot.get("source", "spotify_pkce"),
            started_at_ts=now,
            last_progress_ms=prog_ms,
            max_progress_ms=prog_ms,
            is_playing=is_playing,
            repeat_count=0,
            last_poll_ts=now,
        )
        if self.on_track_need_profile:
            self.on_track_need_profile(snapshot)

        return committed

    def flush_active_track(self, now_ts: Optional[float] = None) -> Optional[Dict[str, Any]]:
        """Commits the currently active track (e.g., on shutdown or manual flush)."""
        if self.active is None:
            return None
        now = now_ts if now_ts is not None else time.time()
        weights = self.db.get_settings().weights
        res = self._commit_active_track(now, weights)
        self.active = None
        return res

    def _commit_active_track(self, now_ts: float, weights: TasteWeightsConfig) -> Dict[str, Any]:
        assert self.active is not None
        prev = self.active
        # If the song repeated at least once, it was played fully before restarting
        effective_listened_ms = (
            prev.duration_ms if prev.repeat_count > 0 else prev.max_progress_ms
        )
        skipped = False if prev.repeat_count > 0 else is_track_skipped(
            effective_listened_ms, prev.duration_ms, weights
        )

        # Ensure track profile exists in DB before foreign-key insert
        if not self.db.get_track_profile(prev.track_id) and self.on_track_need_profile:
            self.on_track_need_profile(
                {
                    "track_id": prev.track_id,
                    "title": prev.title,
                    "artist": prev.artist,
                    "album": prev.album,
                    "album_art_url": prev.album_art_url,
                    "duration_ms": prev.duration_ms,
                    "spotify_url": prev.spotify_url,
                }
            )

        event_id = self.db.record_play_event(
            track_id=prev.track_id,
            listened_ms=effective_listened_ms,
            duration_ms=prev.duration_ms,
            was_skipped=skipped,
            repeat_count=prev.repeat_count,
            played_at_ts=now_ts,
            source=prev.source,
            is_demo=False,
        )
        return {
            "event_id": event_id,
            "track_id": prev.track_id,
            "title": prev.title,
            "artist": prev.artist,
            "listened_ms": effective_listened_ms,
            "duration_ms": prev.duration_ms,
            "was_skipped": skipped,
            "repeat_count": prev.repeat_count,
        }

    def backfill_recent_plays(self) -> int:
        """
        Backfills missing plays from Spotify's `current_user_recently_played(limit=50)`.
        Used on startup and after sleep gaps (>15 min).
        """
        items = self.spotify.get_recently_played(limit=50)
        added = 0
        for item in reversed(items):
            tid = item["track_id"]
            played_ts = item["played_at_ts"]
            if self.db.has_play_near_timestamp(tid, played_ts, tolerance_sec=120.0):
                continue
            if not self.db.get_track_profile(tid) and self.on_track_need_profile:
                self.on_track_need_profile(item)
            if self.db.get_track_profile(tid):
                self.db.record_play_event(
                    track_id=tid,
                    listened_ms=item["duration_ms"],
                    duration_ms=item["duration_ms"],
                    was_skipped=False,
                    repeat_count=0,
                    played_at_ts=played_ts,
                    source="recently_played_backfill",
                    is_demo=False,
                )
                added += 1
        self._last_backfill_ts = time.time()
        return added

    def start_background_loop(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._poll_loop, name="PulseMindPoller", daemon=True
        )
        self._thread.start()

    def stop_background_loop(self) -> None:
        self._stop_event.set()

    def poll_once(self, record_initial_if_empty: bool = False) -> Optional[Dict[str, Any]]:
        """
        Immediately checks the user's active Spotify session (via PKCE or Windows GSMTC Desktop session),
        profiles the currently playing track, updates `self.active`, and optionally records an initial
        play event if the user's live history is empty so Taste DNA works immediately on boot.
        """
        if self.paused_by_user:
            return None

        snap = None
        if self.spotify.is_authenticated():
            snap = self.spotify.get_current_playback()
        if not snap:
            snap = get_windows_media_session_track(db=self.db)
            if snap and self.spotify.is_configured() and snap["track_id"].startswith("winmedia_"):
                resolved = self.spotify.search_track(snap["title"], snap["artist"])
                if resolved:
                    snap.update(resolved)

        if not snap:
            return None

        now = time.time()
        committed = self.process_playback_snapshot(snap, now_ts=now)

        # If this is the very first boot with no recorded history yet, log the active song
        # so Taste DNA & Recommendations immediately reflect the user's active Spotify session!
        if record_initial_if_empty and self.active is not None:
            existing = self.db.get_play_events(include_demo=False, limit=1)
            if not existing:
                if not self.db.get_track_profile(self.active.track_id) and self.on_track_need_profile:
                    self.on_track_need_profile(snap)
                self.db.record_play_event(
                    track_id=self.active.track_id,
                    listened_ms=max(45000, self.active.last_progress_ms),
                    duration_ms=self.active.duration_ms,
                    was_skipped=False,
                    repeat_count=0,
                    played_at_ts=now,
                    source=self.active.source,
                    is_demo=False,
                )
        return committed

    def _poll_loop(self) -> None:
        last_tick = time.time()
        # Connect immediately on loop start
        try:
            self.poll_once(record_initial_if_empty=True)
        except Exception:
            pass

        while not self._stop_event.is_set():
            settings = self.db.get_settings()
            interval = max(2, settings.weights.poll_interval_seconds)
            now = time.time()

            # If PC slept (gap > 10 minutes) or never backfilled, backfill recently played
            if (
                self.spotify.is_authenticated()
                and (now - self._last_backfill_ts > 900 or now - last_tick > 180)
            ):
                try:
                    self.backfill_recent_plays()
                except Exception:
                    pass

            last_tick = now
            try:
                self.poll_once(record_initial_if_empty=True)
            except Exception:
                pass

            self._stop_event.wait(timeout=interval)
