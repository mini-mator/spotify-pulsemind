"""
Thread-safe SQLite database layer with WAL mode and a single-writer RLock.
Stores track profiles (cached by track_id, never storing raw lyrics),
play history events (with completion ratio, skip flag, repeat loop count),
API response cache, and previewed playlists.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from config import AppSettings, DB_PATH
from schemas import (
    LLMInterpretiveOutput,
    MeasuredAudioFeatures,
    TrackProfile,
    build_track_vector,
)


class Database:
    def __init__(self, db_path: Path = DB_PATH) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._write_lock = threading.RLock()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=30.0, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
        return conn

    def _init_db(self) -> None:
        with self._write_lock:
            conn = self._connect()
            try:
                conn.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS settings (
                        key TEXT PRIMARY KEY,
                        value_json TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS track_profiles (
                        track_id TEXT PRIMARY KEY,
                        title TEXT NOT NULL,
                        artist TEXT NOT NULL,
                        album TEXT DEFAULT '',
                        album_art_url TEXT DEFAULT '',
                        duration_ms INTEGER DEFAULT 200000,
                        spotify_url TEXT DEFAULT '',
                        audio_json TEXT NOT NULL,
                        interpretation_json TEXT NOT NULL,
                        has_lyrics_analyzed INTEGER DEFAULT 0,
                        llm_provider_used TEXT DEFAULT 'heuristic',
                        embedding_json TEXT NOT NULL,
                        updated_at REAL NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS play_events (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        track_id TEXT NOT NULL,
                        played_at_iso TEXT NOT NULL,
                        played_at_ts REAL NOT NULL,
                        listened_ms INTEGER NOT NULL,
                        duration_ms INTEGER NOT NULL,
                        completion_ratio REAL NOT NULL,
                        was_skipped INTEGER NOT NULL DEFAULT 0,
                        repeat_count INTEGER NOT NULL DEFAULT 0,
                        hour_of_day INTEGER NOT NULL DEFAULT 12,
                        source TEXT NOT NULL DEFAULT 'live_poller',
                        is_demo INTEGER NOT NULL DEFAULT 0,
                        FOREIGN KEY (track_id) REFERENCES track_profiles(track_id)
                    );

                    CREATE INDEX IF NOT EXISTS idx_play_events_ts ON play_events(played_at_ts DESC);
                    CREATE INDEX IF NOT EXISTS idx_play_events_track ON play_events(track_id);

                    CREATE TABLE IF NOT EXISTS api_cache (
                        cache_key TEXT PRIMARY KEY,
                        payload_json TEXT NOT NULL,
                        expires_at REAL NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS playlist_drafts (
                        draft_id TEXT PRIMARY KEY,
                        name TEXT NOT NULL,
                        description TEXT NOT NULL,
                        prompt_context TEXT NOT NULL,
                        tracks_json TEXT NOT NULL,
                        exported_spotify_url TEXT DEFAULT '',
                        created_at REAL NOT NULL
                    );
                    """
                )
                conn.commit()
            finally:
                conn.close()

    # -------------------------
    # Settings
    # -------------------------
    def get_settings(self) -> AppSettings:
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT value_json FROM settings WHERE key = 'app_settings'"
            ).fetchone()
            if row:
                data = json.loads(row["value_json"])
                return AppSettings.model_validate(data)
            default = AppSettings()
            self.save_settings(default)
            return default
        finally:
            conn.close()

    def save_settings(self, settings: AppSettings) -> None:
        with self._write_lock:
            conn = self._connect()
            try:
                conn.execute(
                    """
                    INSERT INTO settings (key, value_json)
                    VALUES ('app_settings', ?)
                    ON CONFLICT(key) DO UPDATE SET value_json = excluded.value_json
                    """,
                    (settings.model_dump_json(),),
                )
                conn.commit()
            finally:
                conn.close()

    # -------------------------
    # Track Profiles (Cached by track_id)
    # -------------------------
    def upsert_track_profile(self, profile: TrackProfile) -> TrackProfile:
        if not profile.embedding_vector:
            profile.embedding_vector = build_track_vector(
                profile.audio, profile.interpretation
            )
        with self._write_lock:
            conn = self._connect()
            try:
                conn.execute(
                    """
                    INSERT INTO track_profiles (
                        track_id, title, artist, album, album_art_url, duration_ms,
                        spotify_url, audio_json, interpretation_json,
                        has_lyrics_analyzed, llm_provider_used, embedding_json, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(track_id) DO UPDATE SET
                        title = excluded.title,
                        artist = excluded.artist,
                        album = excluded.album,
                        album_art_url = excluded.album_art_url,
                        duration_ms = excluded.duration_ms,
                        spotify_url = excluded.spotify_url,
                        audio_json = excluded.audio_json,
                        interpretation_json = excluded.interpretation_json,
                        has_lyrics_analyzed = excluded.has_lyrics_analyzed,
                        llm_provider_used = excluded.llm_provider_used,
                        embedding_json = excluded.embedding_json,
                        updated_at = excluded.updated_at
                    """,
                    (
                        profile.track_id,
                        profile.title,
                        profile.artist,
                        profile.album,
                        profile.album_art_url,
                        profile.duration_ms,
                        profile.spotify_url,
                        profile.audio.model_dump_json(),
                        profile.interpretation.model_dump_json(),
                        1 if profile.has_lyrics_analyzed else 0,
                        profile.llm_provider_used,
                        json.dumps(profile.embedding_vector),
                        time.time(),
                    ),
                )
                conn.commit()
            finally:
                conn.close()
        return profile

    def get_track_profile(self, track_id: str) -> Optional[TrackProfile]:
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM track_profiles WHERE track_id = ?", (track_id,)
            ).fetchone()
            if not row:
                return None
            return self._row_to_profile(row)
        finally:
            conn.close()

    def get_all_track_profiles(self) -> Dict[str, TrackProfile]:
        conn = self._connect()
        try:
            rows = conn.execute("SELECT * FROM track_profiles").fetchall()
            return {row["track_id"]: self._row_to_profile(row) for row in rows}
        finally:
            conn.close()

    def _row_to_profile(self, row: sqlite3.Row) -> TrackProfile:
        audio = MeasuredAudioFeatures.model_validate_json(row["audio_json"])
        interp = LLMInterpretiveOutput.model_validate_json(row["interpretation_json"])
        emb = json.loads(row["embedding_json"])
        if not emb:
            emb = build_track_vector(audio, interp)
        return TrackProfile(
            track_id=row["track_id"],
            title=row["title"],
            artist=row["artist"],
            album=row["album"] or "",
            album_art_url=row["album_art_url"] or "",
            duration_ms=row["duration_ms"],
            spotify_url=row["spotify_url"] or f"https://open.spotify.com/track/{row['track_id']}",
            audio=audio,
            interpretation=interp,
            has_lyrics_analyzed=bool(row["has_lyrics_analyzed"]),
            llm_provider_used=row["llm_provider_used"] or "heuristic",
            embedding_vector=emb,
        )

    # -------------------------
    # Play Events
    # -------------------------
    def record_play_event(
        self,
        track_id: str,
        listened_ms: int,
        duration_ms: int,
        was_skipped: bool,
        repeat_count: int = 0,
        played_at_ts: Optional[float] = None,
        source: str = "live_poller",
        is_demo: bool = False,
    ) -> int:
        now_ts = played_at_ts if played_at_ts is not None else time.time()
        dt = datetime.fromtimestamp(now_ts, tz=timezone.utc).astimezone()
        ratio = max(0.0, min(1.0, listened_ms / max(1, duration_ms)))
        with self._write_lock:
            conn = self._connect()
            try:
                cur = conn.execute(
                    """
                    INSERT INTO play_events (
                        track_id, played_at_iso, played_at_ts, listened_ms, duration_ms,
                        completion_ratio, was_skipped, repeat_count, hour_of_day, source, is_demo
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        track_id,
                        dt.isoformat(),
                        now_ts,
                        int(listened_ms),
                        int(duration_ms),
                        round(ratio, 4),
                        1 if was_skipped else 0,
                        int(repeat_count),
                        dt.hour,
                        source,
                        1 if is_demo else 0,
                    ),
                )
                conn.commit()
                return int(cur.lastrowid)
            finally:
                conn.close()

    def increment_latest_repeat(self, track_id: str) -> bool:
        """If the most recent play event is for this track_id, increment its repeat_count."""
        with self._write_lock:
            conn = self._connect()
            try:
                row = conn.execute(
                    "SELECT id, repeat_count FROM play_events WHERE track_id = ? ORDER BY played_at_ts DESC LIMIT 1",
                    (track_id,),
                ).fetchone()
                if not row:
                    return False
                conn.execute(
                    "UPDATE play_events SET repeat_count = repeat_count + 1, was_skipped = 0, completion_ratio = 1.0 WHERE id = ?",
                    (row["id"],),
                )
                conn.commit()
                return True
            finally:
                conn.close()

    def has_play_near_timestamp(self, track_id: str, played_at_ts: float, tolerance_sec: float = 120.0) -> bool:
        """Prevents duplicate backfill records when reconciling Spotify recently_played."""
        conn = self._connect()
        try:
            row = conn.execute(
                """
                SELECT id FROM play_events
                WHERE track_id = ? AND ABS(played_at_ts - ?) <= ?
                LIMIT 1
                """,
                (track_id, played_at_ts, tolerance_sec),
            ).fetchone()
            return row is not None
        finally:
            conn.close()

    def get_play_events(self, include_demo: bool = False, limit: int = 250) -> List[Dict[str, Any]]:
        conn = self._connect()
        try:
            where = "" if include_demo else "WHERE p.is_demo = 0"
            rows = conn.execute(
                f"""
                SELECT p.*, t.title, t.artist, t.album, t.album_art_url, t.spotify_url,
                       t.audio_json, t.interpretation_json, t.has_lyrics_analyzed, t.llm_provider_used
                FROM play_events p
                JOIN track_profiles t ON p.track_id = t.track_id
                {where}
                ORDER BY p.played_at_ts DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            results = []
            for r in rows:
                d = dict(r)
                d["audio"] = json.loads(d.pop("audio_json"))
                d["interpretation"] = json.loads(d.pop("interpretation_json"))
                d["was_skipped"] = bool(d["was_skipped"])
                d["is_demo"] = bool(d["is_demo"])
                results.append(d)
            return results
        finally:
            conn.close()

    def purge_demo_data(self) -> None:
        """Removes any demo play events and disables demo_mode in persisted settings."""
        with self._write_lock:
            conn = self._connect()
            try:
                conn.execute("DELETE FROM play_events WHERE is_demo = 1")
                conn.commit()
            finally:
                conn.close()
        s = self.get_settings()
        if s.demo_mode or not s.enable_windows_media_fallback:
            s.demo_mode = False
            s.enable_windows_media_fallback = True
            self.save_settings(s)

    # -------------------------
    # Generic API Cache
    # -------------------------
    def get_cache(self, cache_key: str) -> Optional[Any]:
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT payload_json, expires_at FROM api_cache WHERE cache_key = ?",
                (cache_key,),
            ).fetchone()
            if not row:
                return None
            if row["expires_at"] < time.time():
                return None
            return json.loads(row["payload_json"])
        finally:
            conn.close()

    def set_cache(self, cache_key: str, payload: Any, ttl_seconds: int = 86400) -> None:
        with self._write_lock:
            conn = self._connect()
            try:
                conn.execute(
                    """
                    INSERT INTO api_cache (cache_key, payload_json, expires_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(cache_key) DO UPDATE SET
                        payload_json = excluded.payload_json,
                        expires_at = excluded.expires_at
                    """,
                    (cache_key, json.dumps(payload), time.time() + ttl_seconds),
                )
                conn.commit()
            finally:
                conn.close()

    # -------------------------
    # Playlist Preview Drafts (Preview -> Confirm Export)
    # -------------------------
    def save_playlist_draft(
        self,
        draft_id: str,
        name: str,
        description: str,
        prompt_context: Dict[str, Any],
        tracks: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        created = time.time()
        with self._write_lock:
            conn = self._connect()
            try:
                conn.execute(
                    """
                    INSERT INTO playlist_drafts (
                        draft_id, name, description, prompt_context, tracks_json, exported_spotify_url, created_at
                    ) VALUES (?, ?, ?, ?, ?, '', ?)
                    ON CONFLICT(draft_id) DO UPDATE SET
                        name = excluded.name,
                        description = excluded.description,
                        prompt_context = excluded.prompt_context,
                        tracks_json = excluded.tracks_json
                    """,
                    (
                        draft_id,
                        name,
                        description,
                        json.dumps(prompt_context),
                        json.dumps(tracks),
                        created,
                    ),
                )
                conn.commit()
            finally:
                conn.close()
        return self.get_playlist_draft(draft_id)  # type: ignore

    def mark_draft_exported(self, draft_id: str, spotify_url: str) -> None:
        with self._write_lock:
            conn = self._connect()
            try:
                conn.execute(
                    "UPDATE playlist_drafts SET exported_spotify_url = ? WHERE draft_id = ?",
                    (spotify_url, draft_id),
                )
                conn.commit()
            finally:
                conn.close()

    def get_playlist_draft(self, draft_id: str) -> Optional[Dict[str, Any]]:
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM playlist_drafts WHERE draft_id = ?", (draft_id,)
            ).fetchone()
            if not row:
                return None
            return {
                "draft_id": row["draft_id"],
                "name": row["name"],
                "description": row["description"],
                "prompt_context": json.loads(row["prompt_context"]),
                "tracks": json.loads(row["tracks_json"]),
                "exported_spotify_url": row["exported_spotify_url"],
                "created_at": row["created_at"],
            }
        finally:
            conn.close()

    def list_playlist_drafts(self, limit: int = 20) -> List[Dict[str, Any]]:
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT * FROM playlist_drafts ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [
                {
                    "draft_id": r["draft_id"],
                    "name": r["name"],
                    "description": r["description"],
                    "prompt_context": json.loads(r["prompt_context"]),
                    "tracks": json.loads(r["tracks_json"]),
                    "exported_spotify_url": r["exported_spotify_url"],
                    "created_at": r["created_at"],
                }
                for r in rows
            ]
        finally:
            conn.close()
