"""
Configuration & Secure Credential Storage for PulseMind.
Stores sensitive API keys (Spotify Client ID, LLM API keys, Last.fm API key)
in the OS Credential Manager via `keyring` with an in-memory/SQLite fallback
for non-secret preferences and taste weighting parameters.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, Optional
from pydantic import BaseModel, Field

try:
    import keyring
    KEYRING_AVAILABLE = True
except Exception:
    KEYRING_AVAILABLE = False

SERVICE_NAME = "PulseMind_Spotify_Tracker"
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "pulsemind.db"
SPOTIFY_CACHE_PATH = DATA_DIR / ".spotify_token_cache"

SECRET_KEYS = (
    "spotify_client_id",
    "llm_api_key",
    "lastfm_api_key",
)

# Fallback in-memory store if OS keyring is unavailable in headless test environments
_MEMORY_SECRETS: Dict[str, str] = {}


def set_secret(key: str, value: str) -> None:
    """Stores a secret in Windows Credential Manager via keyring."""
    if key not in SECRET_KEYS:
        raise ValueError(f"Unknown secret key: {key}")
    clean = (value or "").strip()
    _MEMORY_SECRETS[key] = clean
    if KEYRING_AVAILABLE:
        try:
            if clean:
                keyring.set_password(SERVICE_NAME, key, clean)
            else:
                try:
                    keyring.delete_password(SERVICE_NAME, key)
                except Exception:
                    pass
        except Exception:
            pass


def get_secret(key: str) -> str:
    """Retrieves a secret from Windows Credential Manager or environment fallback."""
    env_map = {
        "spotify_client_id": "SPOTIFY_CLIENT_ID",
        "llm_api_key": "PULSEMIND_LLM_API_KEY",
        "lastfm_api_key": "LASTFM_API_KEY",
    }
    if key in _MEMORY_SECRETS and _MEMORY_SECRETS[key]:
        return _MEMORY_SECRETS[key]
    if KEYRING_AVAILABLE:
        try:
            val = keyring.get_password(SERVICE_NAME, key)
            if val:
                return val
        except Exception:
            pass
    env_name = env_map.get(key)
    if env_name and os.environ.get(env_name):
        return os.environ[env_name]
    return ""


class TasteWeightsConfig(BaseModel):
    """Tunable parameters for Taste DNA calculation & skip/repeat tracking."""
    # Tracking thresholds
    poll_interval_seconds: int = Field(default=4, ge=2, le=30)
    skip_min_ms: int = Field(default=30000, description="Under 30s is considered a skip")
    skip_min_ratio: float = Field(default=0.50, description="Under 50% completion is considered a skip")
    repeat_restart_threshold_ms: int = Field(
        default=15000,
        description="If same track restarts below 15s after playing >=30s, count as repeat loop"
    )

    # Exponential decay
    half_life_days: float = Field(default=14.0, ge=1.0, le=365.0)

    # Multipliers
    full_listen_weight: float = Field(default=1.0)
    skip_penalty_weight: float = Field(default=0.15, description="Skipped tracks contribute very little or negative")
    repeat_bonus_per_loop: float = Field(default=0.45, description="Bonus weight per repeat loop")
    late_night_boost: float = Field(default=1.35, description="Multiplier for plays between 22:00 and 04:00")
    late_night_start_hour: int = Field(default=22, ge=0, le=23)
    late_night_end_hour: int = Field(default=4, ge=0, le=23)


class AppSettings(BaseModel):
    host: str = "127.0.0.1"
    port: int = 8765
    redirect_uri: str = "http://127.0.0.1:8765/callback"
    llm_provider: str = Field(
        default="ollama",
        description="One of: 'ollama' (local/private), 'gemini', 'openai', 'heuristic'"
    )
    llm_model: str = Field(
        default="llama3.2",
        description="Model name (e.g. 'llama3.2', 'gemini-2.5-flash', 'gpt-4o-mini')"
    )
    ollama_base_url: str = "http://127.0.0.1:11434"
    send_lyrics_to_cloud_llm: bool = Field(
        default=False,
        description="Privacy toggle: only send LRCLIB lyrics to cloud LLMs if explicitly enabled; Ollama is local."
    )
    enable_windows_media_fallback: bool = Field(default=True)
    demo_mode: bool = Field(default=False)
    weights: TasteWeightsConfig = Field(default_factory=TasteWeightsConfig)
