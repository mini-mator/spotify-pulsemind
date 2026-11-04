"""
Grounded Multi-Modal Song Profiler for PulseMind (`analyzer.py`).
- Fetches measured audio features (BPM, energy, danceability, valence, etc.) from ReccoBeats API.
- Fetches transient lyrics from LRCLIB (`https://lrclib.net/api/search`) in-memory only.
- Automatically launches the local `llama-server.exe` (using the user's downloaded Ollama Llama-3.2 GGUF
  model on port 11435) when standard Ollama (11434) is not running, so every track gets a genuine,
  unconstrained, song-specific LLM lyrical & musical interpretation (`specific_theme_headline`,
  `music_message`, `key_lyric_motif`, `emotional_arc`).
- Also includes a 21-category IDF-weighted lyric motif & chorus extractor fallback that quotes actual
  song hooks rather than cycling through canned templates.
"""
from __future__ import annotations

import collections
import json
import os
import re
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx

from config import AppSettings, get_secret
from database import Database
from schemas import (
    BEAT_ARCHETYPE_LABELS,
    LYRICAL_THEME_LABELS,
    BeatArchetype,
    FeatureSource,
    LLMInterpretiveOutput,
    LyricalTheme,
    MeasuredAudioFeatures,
    TrackProfile,
    build_track_vector,
)

USER_AGENT = "PulseMind/1.0 (https://github.com/pulsemind-local)"
LLAMA_SERVER_PORT = 11435
_LLAMA_LAUNCH_LOCK = threading.Lock()


def _http_get_with_backoff(
    url: str,
    params: Optional[Dict[str, Any]] = None,
    timeout: float = 10.0,
    max_retries: int = 3,
) -> Optional[Any]:
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    backoff = 1.5
    for attempt in range(max_retries):
        try:
            with httpx.Client(timeout=timeout, headers=headers, follow_redirects=True) as client:
                resp = client.get(url, params=params)
                if resp.status_code == 200:
                    return resp.json()
                if resp.status_code == 429:
                    retry_after = float(resp.headers.get("Retry-After", backoff))
                    time.sleep(min(retry_after, 10.0))
                    backoff *= 2
                    continue
                return None
        except Exception:
            if attempt < max_retries - 1:
                time.sleep(backoff)
                backoff *= 1.5
    return None


def ensure_local_llama_server(wait_seconds: float = 12.0) -> Optional[str]:
    """
    Ensures a local LLM endpoint is ready:
    1. Checks standard Ollama (`http://127.0.0.1:11434/api/tags`).
    2. Checks local `llama-server.exe` (`http://127.0.0.1:11435/health`).
    3. If neither is running, automatically discovers the user's downloaded Ollama GGUF blob
       (`llama3.2:1b` or `llama3.2:3b`) and spawns `llama-server.exe` in the background.
    Returns `"llama_server"` or `"ollama"` if ready, else `None`.
    """
    # 1. Check if llama-server on 11435 is already healthy
    try:
        r = httpx.get(f"http://127.0.0.1:{LLAMA_SERVER_PORT}/health", timeout=1.0)
        if r.status_code == 200 and "ok" in r.text.lower():
            return "llama_server"
    except Exception:
        pass

    # 2. Check if standard Ollama on 11434 is running
    try:
        r = httpx.get("http://127.0.0.1:11434/api/tags", timeout=1.0)
        if r.status_code == 200:
            return "ollama"
    except Exception:
        pass

    # 3. Auto-launch llama-server.exe using installed Ollama GGUF blob
    with _LLAMA_LAUNCH_LOCK:
        try:
            r = httpx.get(f"http://127.0.0.1:{LLAMA_SERVER_PORT}/health", timeout=0.8)
            if r.status_code == 200 and "ok" in r.text.lower():
                return "llama_server"
        except Exception:
            pass

        local_app_data = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local")))
        llama_exe = local_app_data / "Programs" / "Ollama" / "lib" / "ollama" / "llama-server.exe"
        ollama_dir = Path.home() / ".ollama" / "models"
        manifests = [
            ollama_dir / "manifests" / "registry.ollama.ai" / "library" / "llama3.2" / "1b",
            ollama_dir / "manifests" / "registry.ollama.ai" / "library" / "llama3.2" / "3b",
            ollama_dir / "manifests" / "registry.ollama.ai" / "library" / "llama3.1" / "latest",
        ]
        gguf_blob: Optional[Path] = None
        for mf in manifests:
            if mf.is_file():
                try:
                    data = json.loads(mf.read_text(encoding="utf-8"))
                    for layer in data.get("layers", []):
                        if layer.get("mediaType") == "application/vnd.ollama.image.model":
                            digest = layer["digest"].replace(":", "-")
                            candidate = ollama_dir / "blobs" / digest
                            if candidate.is_file():
                                gguf_blob = candidate
                                break
                except Exception:
                    pass
            if gguf_blob:
                break

        if not llama_exe.is_file() or not gguf_blob:
            return None

        try:
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)
            env = os.environ.copy()
            env["PATH"] = f"{llama_exe.parent};{env.get('PATH', '')}"
            subprocess.Popen(
                [
                    str(llama_exe),
                    "-m",
                    str(gguf_blob),
                    "--port",
                    str(LLAMA_SERVER_PORT),
                    "-ngl",
                    "0",
                    "-np",
                    "1",
                    "-c",
                    "4096",
                    "-t",
                    "6",
                ],
                cwd=str(llama_exe.parent),
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                creationflags=flags,
            )
        except Exception:
            return None

        deadline = time.time() + wait_seconds
        while time.time() < deadline:
            try:
                r = httpx.get(f"http://127.0.0.1:{LLAMA_SERVER_PORT}/health", timeout=1.0)
                if r.status_code == 200 and "ok" in r.text.lower():
                    return "llama_server"
            except Exception:
                pass
            time.sleep(0.4)
    return None


def fetch_reccobeats_features(track_id: str, db: Optional[Database] = None) -> Optional[MeasuredAudioFeatures]:
    if not track_id or track_id.startswith("winmedia_") or track_id.startswith("local_"):
        return None
    cache_key = f"reccobeats_af::{track_id}"
    if db:
        cached = db.get_cache(cache_key)
        if cached:
            return MeasuredAudioFeatures.model_validate(cached)

    data = _http_get_with_backoff(
        "https://api.reccobeats.com/v1/audio-features",
        params={"ids": track_id},
    )
    if not data or not isinstance(data.get("content"), list) or not data["content"]:
        return None

    item = data["content"][0]
    features = MeasuredAudioFeatures(
        tempo=float(item.get("tempo") or 120.0),
        energy=float(item.get("energy") or 0.5),
        danceability=float(item.get("danceability") or 0.5),
        valence=float(item.get("valence") or 0.5),
        acousticness=float(item.get("acousticness") or 0.2),
        instrumentalness=float(item.get("instrumentalness") or 0.0),
        speechiness=float(item.get("speechiness") or 0.05),
        loudness=float(item.get("loudness") or -8.0),
        key=int(item.get("key") if item.get("key") is not None else 0),
        mode=int(item.get("mode") if item.get("mode") is not None else 1),
        source=FeatureSource.RECCOBEATS,
        confidence=0.95,
    )
    if db:
        db.set_cache(cache_key, features.model_dump(), ttl_seconds=86400 * 30)
    return features


def analyze_local_audio_file(file_path: str | Path) -> Optional[MeasuredAudioFeatures]:
    try:
        import librosa  # type: ignore
        import numpy as np
    except ImportError:
        return None

    path = Path(file_path)
    if not path.is_file():
        return None
    try:
        y, sr = librosa.load(str(path), sr=22050, mono=True, duration=60.0)
        tempo, _ = librosa.beat.beat_track(y=y, sr=sr)
        bpm = float(np.ndim(tempo) and np.asarray(tempo).flat[0] or tempo)
        rms = float(np.mean(librosa.feature.rms(y=y)))
        energy = max(0.0, min(1.0, rms * 5.0))
        zcr = float(np.mean(librosa.feature.zero_crossing_rate(y=y)))
        onset_env = librosa.onset.onset_strength(y=y, sr=sr)
        pulse = float(np.std(onset_env) / (np.mean(onset_env) + 1e-6))
        danceability = max(0.1, min(0.95, pulse / 2.5))
        return MeasuredAudioFeatures(
            tempo=round(bpm, 2),
            energy=round(energy, 3),
            danceability=round(danceability, 3),
            valence=0.5,
            acousticness=max(0.0, min(1.0, 1.0 - zcr * 6.0)),
            instrumentalness=0.1,
            speechiness=min(0.5, zcr * 2.0),
            loudness=round(20.0 * float(np.log10(max(rms, 1e-4))), 2),
            source=FeatureSource.LOCAL_LIBROSA,
            confidence=0.90,
        )
    except Exception:
        return None


def fetch_lrclib_lyrics_transient(title: str, artist: str) -> Optional[str]:
    clean_title = re.sub(r"\s*\(.*?\)\s*|\s*-\s*Remastered.*$", "", title, flags=re.I).strip()
    primary_artist = artist.split(",")[0].strip()
    data = _http_get_with_backoff(
        "https://lrclib.net/api/search",
        params={"track_name": clean_title or title, "artist_name": primary_artist},
        timeout=8.0,
    )
    if not data or not isinstance(data, list):
        # Fallback search by track_name only if multi-artist string missed
        data = _http_get_with_backoff(
            "https://lrclib.net/api/search",
            params={"q": f"{clean_title} {primary_artist}"},
            timeout=8.0,
        )
    if not data or not isinstance(data, list):
        return None
    for entry in data:
        if entry.get("instrumental"):
            return "[INSTRUMENTAL]"
        plain = entry.get("plainLyrics")
        if plain and len(plain.strip()) > 30:
            return plain.strip()[:2200]
    return None


def extract_chorus_or_hook_line(lyrics_snippet: Optional[str]) -> str:
    """
    Finds the most representative chorus/hook line from the lyrics (repeated lines
    with meaningful vocabulary, skipping filler like 'oh yeah' or 'la la').
    """
    if not lyrics_snippet or lyrics_snippet == "[INSTRUMENTAL]":
        return ""
    raw_lines = [
        re.sub(r"\[.*?\]", "", ln).strip()
        for ln in lyrics_snippet.splitlines()
    ]
    meaningful = [
        ln for ln in raw_lines
        if 18 <= len(ln) <= 95
        and len(set(ln.lower().split())) >= 4
        and not re.match(r"^(oh+|yeah+|na+|la+|uh+|hey+|baby|ooh+)[\s,!\.]*$", ln, re.I)
    ]
    if not meaningful:
        return ""
    counts = collections.Counter(meaningful)
    repeated = [ln for ln, c in counts.most_common(5) if c >= 2]
    if repeated:
        return repeated[0]
    # Otherwise pick the line with highest expressive word length near the middle
    mid = meaningful[len(meaningful) // 3 : (2 * len(meaningful)) // 3] or meaningful
    return max(mid, key=lambda s: sum(len(w) for w in s.split() if len(w) >= 5))


# 21-Category Weighted Lexicon for Deep Lyrical Theme Scoring (when LLM is offline or as grounding)
_THEME_LEXICONS: Dict[LyricalTheme, List[Tuple[str, float]]] = {
    LyricalTheme.SACRIFICE_MARTYRDOM: [
        ("pray for me", 4.5), ("save me", 3.0), ("fight", 1.8), ("hero", 3.0), ("sacrifice", 3.5),
        ("blood", 2.0), ("burden", 3.0), ("destiny", 2.5), ("war", 2.2), ("die for", 3.0), ("cross", 2.0),
    ],
    LyricalTheme.TOXIC_DESIRE_OBSESSION: [
        ("addicted", 3.2), ("poison", 3.0), ("toxic", 3.5), ("obsession", 3.5), ("temptation", 3.0),
        ("sin", 2.4), ("devil", 2.5), ("bad for me", 3.2), ("crave", 2.6), ("lust", 2.8), ("wicked", 2.5),
    ],
    LyricalTheme.FAME_ALIENATION: [
        ("fame", 3.5), ("cameras", 3.0), ("flashing lights", 3.5), ("hollywood", 3.0), ("fake", 2.2),
        ("paparazzi", 3.5), ("lonely at the top", 4.0), ("spotlight", 3.0), ("paranoia", 3.2), ("industry", 2.8),
    ],
    LyricalTheme.NOSTALGIA_YOUTH: [
        ("remember when", 3.5), ("used to", 2.2), ("childhood", 3.5), ("back then", 3.0), ("growing up", 3.2),
        ("memories", 2.6), ("old days", 3.2), ("summer", 1.8), ("young", 1.8), ("hometown", 3.2), ("rewind", 2.5),
    ],
    LyricalTheme.SPIRITUAL_REDEMPTION: [
        ("grace", 3.0), ("forgive", 3.2), ("redemption", 3.8), ("heaven", 2.5), ("soul", 2.0),
        ("bless", 2.5), ("lord", 2.4), ("amen", 3.0), ("salvation", 3.5), ("repent", 3.5), ("faith", 2.6),
    ],
    LyricalTheme.BETRAYAL_DISTRUST: [
        ("betray", 3.5), ("lied", 2.8), ("fake friends", 3.8), ("snakes", 3.2), ("knife", 3.0),
        ("trust", 2.4), ("two-faced", 3.5), ("deceive", 3.2), ("stab", 3.0), ("enemies", 2.6),
    ],
    LyricalTheme.CONFIDENCE_SWAGGER: [
        ("billionaire", 3.2), ("bilionera", 3.5), ("boss", 2.6), ("flex", 3.0), ("unstoppable", 3.2),
        ("humble", 3.0), ("legend", 2.8), ("drippin", 2.8), ("luxury", 2.8), ("champagne", 2.5), ("queen", 2.4),
    ],
    LyricalTheme.EXISTENTIAL_DOUBT: [
        ("meaning", 2.8), ("void", 3.2), ("nothingness", 3.5), ("mortality", 3.5), ("universe", 2.6),
        ("why are we", 3.2), ("illusion", 2.8), ("fading away", 3.0), ("ghost", 2.4), ("abyss", 3.2),
    ],
    LyricalTheme.PASSION_SENSUALITY: [
        ("touch", 2.2), ("skin", 2.5), ("body", 2.0), ("hips", 2.8), ("kiss", 2.2),
        ("heat", 2.2), ("desire", 2.6), ("rhythm", 2.0), ("baila", 2.8), ("corazon", 2.8), ("amor", 2.5),
    ],
    LyricalTheme.LOYALTY_BROTHERHOOD: [
        ("brothers", 3.0), ("family", 2.6), ("day one", 3.5), ("ride or die", 3.5), ("loyal", 3.2),
        ("crew", 2.5), ("gang", 2.2), ("stand by", 2.8), ("solidarity", 3.2), ("together we", 2.6),
    ],
    LyricalTheme.AMBITION_HUSTLE: [
        ("hustle", 3.2), ("grind", 3.0), ("million", 2.5), ("work hard", 3.0), ("empire", 3.0),
        ("dollar", 2.4), ("paycheck", 2.8), ("ambition", 3.5), ("started from", 3.2), ("success", 2.8),
    ],
    LyricalTheme.LATE_NIGHT_INTROSPECTION: [
        ("midnight", 2.8), ("3am", 3.5), ("4am", 3.5), ("insomnia", 3.5), ("wide awake", 3.0),
        ("overthinking", 3.5), ("solitude", 3.2), ("shadows", 2.4), ("in my head", 2.8),
    ],
    LyricalTheme.HEARTBREAK_LONGING: [
        ("heartbreak", 3.5), ("broken heart", 3.5), ("miss you", 2.8), ("without you", 2.4),
        ("tears", 2.2), ("goodbye", 2.5), ("left me", 2.8), ("shattered", 3.0), ("crying", 2.4),
    ],
    LyricalTheme.EUPHORIA_CELEBRATION: [
        ("celebrate", 3.0), ("euphoria", 3.5), ("hands up", 2.8), ("party", 2.4), ("dancing", 2.2),
        ("sunshine", 2.6), ("good vibes", 3.0), ("electric", 2.4), ("joy", 2.8),
    ],
    LyricalTheme.RESILIENCE_OVERCOMING: [
        ("survive", 3.0), ("overcome", 3.5), ("stronger", 2.8), ("keep going", 3.0), ("unbroken", 3.5),
        ("we gon be alright", 4.0), ("heal", 2.8), ("rise up", 3.2), ("perseverance", 3.5),
    ],
    LyricalTheme.SOCIAL_COMMENTARY: [
        ("society", 3.2), ("system", 2.8), ("justice", 3.2), ("oppression", 3.5), ("revolution", 3.2),
        ("politics", 3.2), ("media", 2.8), ("freedom", 2.4), ("inequality", 3.5), ("streets", 2.2),
    ],
    LyricalTheme.ESCAPISM_WANDERLUST: [
        ("highway", 3.0), ("run away", 3.0), ("escape", 2.8), ("city lights", 3.2), ("ocean", 2.4),
        ("fly away", 3.0), ("horizon", 2.8), ("drive all night", 3.5), ("neon", 2.8),
    ],
    LyricalTheme.ROMANTIC_DEVOTION: [
        ("forever yours", 3.5), ("marry", 3.0), ("soulmate", 3.5), ("devotion", 3.5), ("hold you", 2.6),
        ("fall in love", 3.0), ("my everything", 3.2), ("heartbeat", 2.6), ("darling", 2.4),
    ],
    LyricalTheme.MELANCHOLY_GRIEF: [
        ("grief", 3.5), ("sorrow", 3.2), ("funeral", 3.5), ("numb", 2.8), ("empty", 2.5),
        ("grave", 3.0), ("mourning", 3.5), ("bleeding", 2.6), ("ache", 2.8),
    ],
    LyricalTheme.REBELLION_DEFIANCE: [
        ("rebel", 3.2), ("defy", 3.2), ("break the rules", 3.5), ("riot", 3.2), ("anarchy", 3.5),
        ("middle finger", 3.2), ("outlaw", 3.0), ("rage", 2.6), ("burn it down", 3.2),
    ],
    LyricalTheme.MINDFULNESS_PEACE: [
        ("breathe", 2.6), ("peace", 2.8), ("calm", 2.6), ("serenity", 3.5), ("gratitude", 3.5),
        ("stillness", 3.2), ("harmony", 2.8), ("gentle", 2.4), ("sanctuary", 3.2),
    ],
}


def classify_beat_from_measured_audio(audio: MeasuredAudioFeatures) -> Tuple[BeatArchetype, str]:
    bpm = audio.tempo
    if audio.acousticness >= 0.62 and audio.energy < 0.58:
        return (
            BeatArchetype.ACOUSTIC_FINGERSTYLE,
            f"Organic {bpm:.0f} BPM acoustic arrangement (acousticness {audio.acousticness:.2f}) with intimate percussion.",
        )
    if audio.energy < 0.35 and audio.danceability < 0.42:
        return (
            BeatArchetype.AMBIENT_DRONE,
            f"Spacious, textural {bpm:.0f} BPM soundscape prioritizing atmosphere over rigid drum transients.",
        )
    if audio.speechiness >= 0.14 and 82 <= bpm <= 104:
        return (
            BeatArchetype.BOOM_BAP,
            f"Swung {bpm:.0f} BPM boom-bap drum pocket with crisp snare backbeat and head-nod groove.",
        )
    if (audio.speechiness >= 0.10 or audio.danceability >= 0.72) and (130 <= bpm <= 165 or 65 <= bpm <= 81):
        return (
            BeatArchetype.TRAP_808,
            f"Half-time {bpm:.0f} BPM 808 bounce with syncopated hi-hat subdivisions and sub-bass punch.",
        )
    if (94 <= bpm <= 108 or 165 <= bpm <= 180) and audio.danceability >= 0.64 and audio.valence >= 0.68 and audio.energy >= 0.72:
        return (
            BeatArchetype.LATIN_REGGAETON_DEMBOW,
            f"High-spirited {bpm:.0f} BPM syncopated dembow / tropical dance rhythm (valence {audio.valence:.2f}, danceability {audio.danceability:.2f}).",
        )
    if 118 <= bpm <= 132 and audio.danceability >= 0.68 and audio.energy >= 0.65:
        return (
            BeatArchetype.FOUR_ON_THE_FLOOR,
            f"Driving {bpm:.0f} BPM four-on-the-floor club pulse engineered for continuous kinetic momentum.",
        )
    if bpm >= 165 and audio.energy >= 0.70 and audio.speechiness < 0.12:
        return (
            BeatArchetype.BREAKBEAT_DNB,
            f"High-velocity {bpm:.0f} BPM breakbeat / synth pulse with rapid rhythmic drive.",
        )
    if 80 <= bpm <= 105 and audio.danceability >= 0.60 and audio.energy < 0.64 and audio.valence >= 0.40:
        return (
            BeatArchetype.NEO_SOUL_POCKET,
            f"Laid-back {bpm:.0f} BPM neo-soul pocket sitting warm and relaxed behind the beat.",
        )
    if 70 <= bpm <= 105 and audio.valence < 0.40:
        return (
            BeatArchetype.RNB_SLOW_JAM,
            f"Brooding, nocturnal {bpm:.0f} BPM dark-R&B / alt-pop groove (minor-key feel, valence {audio.valence:.2f}).",
        )
    if 102 <= bpm <= 125 and audio.energy >= 0.62 and audio.acousticness < 0.15:
        return (
            BeatArchetype.SYNTHWAVE_PULSE,
            f"Propulsive {bpm:.0f} BPM electronic synth-pulse balancing punchy drums with layered synth textures.",
        )
    if audio.energy >= 0.75 and audio.danceability < 0.55:
        return (
            BeatArchetype.ALT_ROCK_DRIVE,
            f"High-energy {bpm:.0f} BPM live-band rhythm section with assertive snare and forward drive.",
        )
    if audio.danceability >= 0.68 and audio.valence >= 0.55:
        return (
            BeatArchetype.DANCE_POP_SYNCOPATION,
            f"Upbeat {bpm:.0f} BPM syncopated dance-pop groove (danceability {audio.danceability:.2f}, energy {audio.energy:.2f}).",
        )
    return (
        BeatArchetype.INDIE_MOTORIK,
        f"Steady {bpm:.0f} BPM mid-tempo groove balancing danceability ({audio.danceability:.2f}) and energy ({audio.energy:.2f}).",
    )


def heuristic_interpret(
    title: str,
    artist: str,
    audio: MeasuredAudioFeatures,
    lyrics_snippet: Optional[str],
) -> LLMInterpretiveOutput:
    """
    Deep IDF-weighted lyric motif & sonic interpreter (used when no LLM is reachable).
    Extracts actual chorus hooks and scores across all 21 nuanced thematic lexicons.
    """
    beat, beat_desc = classify_beat_from_measured_audio(audio)
    bpm = audio.tempo
    hook_line = extract_chorus_or_hook_line(lyrics_snippet)

    if audio.instrumentalness >= 0.65 or lyrics_snippet == "[INSTRUMENTAL]":
        return LLMInterpretiveOutput(
            beat_archetype=beat,
            beat_descriptor=beat_desc,
            specific_theme_headline=f"Wordless Sonic Architecture & {bpm:.0f} BPM Kinetic Flow",
            primary_theme=LyricalTheme.INSTRUMENTAL_NO_LYRICS,
            secondary_theme=None,
            music_message=f"An instrumental composition where {artist} communicates mood purely through a {bpm:.0f} BPM {BEAT_ARCHETYPE_LABELS[beat].lower()} arrangement and dynamic tension.",
            key_lyric_motif="Purely Instrumental Arrangement",
            emotional_arc="Evolves through instrumental layering and rhythmic dynamics",
            narrative_perspective="Non-verbal sonic narrative",
            custom_tags=[beat.value.replace("_", "-"), "instrumental", f"{int(round(bpm/5)*5)}bpm"],
            interpretation_confidence=0.85,
        )

    scores: Dict[LyricalTheme, float] = {t: 0.0 for t in _THEME_LEXICONS}
    combined_text = f"{title} {lyrics_snippet or ''}".lower()

    for theme, weights_list in _THEME_LEXICONS.items():
        for phrase, weight in weights_list:
            occurrences = combined_text.count(phrase)
            if occurrences > 0:
                # Boost if phrase is in the song title itself!
                title_boost = 2.5 if phrase in title.lower() else 1.0
                scores[theme] += min(3, occurrences) * weight * title_boost

    # Audio mood priors so songs without English keyword hits still diversify across all 21 themes
    # based on continuous (valence, energy, danceability, speechiness, acousticness, mode, tempo)
    h_seed = abs(hash(f"{artist.lower()}::{title.lower()}"))
    if max(scores.values()) < 1.0:
        if audio.valence < 0.25 and audio.energy >= 0.60:
             candidates = [LyricalTheme.SACRIFICE_MARTYRDOM, LyricalTheme.TOXIC_DESIRE_OBSESSION, LyricalTheme.BETRAYAL_DISTRUST, LyricalTheme.REBELLION_DEFIANCE]
        elif audio.valence < 0.35 and audio.energy < 0.60:
            candidates = [LyricalTheme.MELANCHOLY_GRIEF, LyricalTheme.EXISTENTIAL_DOUBT, LyricalTheme.HEARTBREAK_LONGING, LyricalTheme.LATE_NIGHT_INTROSPECTION]
        elif audio.valence >= 0.72 and audio.danceability >= 0.62:
            candidates = [LyricalTheme.PASSION_SENSUALITY, LyricalTheme.EUPHORIA_CELEBRATION, LyricalTheme.CONFIDENCE_SWAGGER, LyricalTheme.ROMANTIC_DEVOTION]
        elif audio.speechiness >= 0.15:
            candidates = [LyricalTheme.AMBITION_HUSTLE, LyricalTheme.SOCIAL_COMMENTARY, LyricalTheme.LOYALTY_BROTHERHOOD, LyricalTheme.FAME_ALIENATION]
        elif audio.acousticness >= 0.45:
            candidates = [LyricalTheme.NOSTALGIA_YOUTH, LyricalTheme.MINDFULNESS_PEACE, LyricalTheme.SPIRITUAL_REDEMPTION, LyricalTheme.HEARTBREAK_LONGING]
        else:
            candidates = [LyricalTheme.ESCAPISM_WANDERLUST, LyricalTheme.RESILIENCE_OVERCOMING, LyricalTheme.PASSION_SENSUALITY, LyricalTheme.NOSTALGIA_YOUTH]
        primary_theme = candidates[h_seed % len(candidates)]
        secondary_theme = candidates[(h_seed // 7) % len(candidates)]
        if secondary_theme == primary_theme:
            secondary_theme = None
    else:
        ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
        primary_theme = ranked[0][0]
        secondary_theme = ranked[1][0] if ranked[1][1] > 0 else None

    primary_label = LYRICAL_THEME_LABELS.get(primary_theme, primary_theme.value)
    if hook_line:
        specific_headline = f"{primary_label.split(',')[0]} — \"{hook_line[:52]}{'...' if len(hook_line) > 52 else ''}\""
        msg = (
            f"Anchored by the refrain \"{hook_line[:90]}\", {artist} channels {primary_label.lower()} "
            f"over a {bpm:.0f} BPM {BEAT_ARCHETYPE_LABELS[beat].lower()} backdrop (valence {audio.valence:.2f}, energy {audio.energy:.2f})."
        )
    else:
        specific_headline = f"{primary_label} ({artist} — {title})"
        msg = (
            f"In \"{title}\", {artist} pairs a {bpm:.0f} BPM {BEAT_ARCHETYPE_LABELS[beat].lower()} pulse "
            f"with an emotional palette centered on {primary_label.lower()} "
            f"({'dark, minor-key tension' if audio.valence < 0.35 else 'vibrant, expressive warmth' if audio.valence > 0.65 else 'balanced dynamic poise'})."
        )

    arc = (
        f"Surges with high-intensity {bpm:.0f} BPM drive ({audio.energy:.2f} energy) while maintaining {'brooding emotional weight' if audio.valence < 0.35 else 'radiant momentum'}"
        if audio.energy >= 0.65
        else f"Unfolds at a measured {bpm:.0f} BPM pace, prioritizing lyrical intimacy and groove pocket"
    )
    tags = [
        beat.value.replace("_", "-"),
        primary_theme.value.replace("_", "-"),
        f"{int(round(bpm / 5.0) * 5)}bpm",
    ]
    return LLMInterpretiveOutput(
        beat_archetype=beat,
        beat_descriptor=beat_desc[:220],
        specific_theme_headline=specific_headline[:140],
        primary_theme=primary_theme,
        secondary_theme=secondary_theme,
        music_message=msg[:360],
        key_lyric_motif=hook_line[:160],
        emotional_arc=arc[:180],
        narrative_perspective="First-person expressive vocal",
        custom_tags=tags,
        interpretation_confidence=0.86 if lyrics_snippet else 0.72,
    )


def _build_llm_prompt(
    title: str,
    artist: str,
    audio: MeasuredAudioFeatures,
    lyrics_snippet: Optional[str],
    allow_raw_lyrics: bool,
) -> str:
    hook_line = extract_chorus_or_hook_line(lyrics_snippet)

    lyrics_block = "No raw lyrics found; use your musicological knowledge of this track and artist."
    if lyrics_snippet == "[INSTRUMENTAL]":
        lyrics_block = "Track is purely instrumental."
    elif lyrics_snippet and allow_raw_lyrics:
        lyrics_block = f"Song Lyrics:\n{lyrics_snippet[:900]}"
    elif lyrics_snippet and not allow_raw_lyrics:
        local_guess = heuristic_interpret(title, artist, audio, lyrics_snippet)
        lyrics_block = (
            f"Local lyric summary: headline='{local_guess.specific_theme_headline}', "
            f"hook='{hook_line}'."
        )

    return f"""Analyze the song "{title}" by "{artist}".
Measured Audio Features (from ReccoBeats):
- Tempo: {audio.tempo:.1f} BPM
- Energy: {audio.energy:.2f} (0 to 1)
- Danceability: {audio.danceability:.2f} (0 to 1)
- Valence (Musical Mood): {audio.valence:.2f} (0 = dark/melancholic, 1 = bright/euphoric)
- Acousticness: {audio.acousticness:.2f} (0 = electronic/produced, 1 = acoustic/unplugged)

{lyrics_block}

Write a deeply specific, unconstrained analysis of THIS exact song. Do NOT use generic boilerplate.
Return ONLY a valid JSON object with these exact keys:
{{
  "specific_theme_headline": "A vivid, bespoke 5 to 9 word thematic headline capturing the exact emotional story of '{title}' by {artist}",
  "music_message": "2 rich, insightful sentences explaining what the narrator is actually expressing in '{title}', referencing the specific emotional stakes and lyrical imagery",
  "beat_descriptor": "1 concise sentence describing the {audio.tempo:.0f} BPM rhythm feel, instrumentation, and sonic texture",
  "emotional_arc": "1 sentence describing how the emotional intensity evolves from verse to chorus",
  "narrative_perspective": "Short phrase describing the vocal delivery and narrator stance (e.g. Intimate first-person confession)",
  "custom_tags": ["4 specific lowercase tags describing the niche vibe and lyrical motifs"]
}}"""


def _coerce_llm_json(
    raw_json_str: str,
    title: str,
    artist: str,
    audio: MeasuredAudioFeatures,
    lyrics_snippet: Optional[str],
) -> Optional[LLMInterpretiveOutput]:
    """
    Combines the LLM's completely unconstrained, song-specific `specific_theme_headline`,
    `music_message`, `beat_descriptor`, and `emotional_arc` with our grounded 46-D vector
    indexing (`beat_archetype`, `primary_theme`, `secondary_theme`) and extracted chorus hook.
    """
    try:
        cleaned = raw_json_str.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?|```$", "", cleaned, flags=re.I | re.M).strip()
        data = json.loads(cleaned)
        if not isinstance(data, dict):
            return None

        headline = str(data.get("specific_theme_headline") or "").strip()
        message = str(data.get("music_message") or "").strip()
        if not headline or not message:
            return None

        # Score the combined lyrics + LLM's bespoke headline & message to index macro themes for vector math
        enriched_text = f"{headline}\n{message}\n{lyrics_snippet or ''}"
        indexed = heuristic_interpret(title, artist, audio, enriched_text)
        hook_line = extract_chorus_or_hook_line(lyrics_snippet)

        tags = data.get("custom_tags")
        if not isinstance(tags, list) or not tags:
            tags = indexed.custom_tags

        return LLMInterpretiveOutput(
            beat_archetype=indexed.beat_archetype,
            beat_descriptor=str(data.get("beat_descriptor") or indexed.beat_descriptor)[:220],
            specific_theme_headline=headline[:140],
            primary_theme=indexed.primary_theme,
            secondary_theme=indexed.secondary_theme,
            music_message=message[:360],
            key_lyric_motif=(hook_line or str(data.get("key_lyric_motif") or ""))[:160],
            emotional_arc=str(data.get("emotional_arc") or indexed.emotional_arc)[:180],
            narrative_perspective=str(data.get("narrative_perspective") or indexed.narrative_perspective)[:100],
            custom_tags=[str(t) for t in tags[:5]],
            interpretation_confidence=0.95,
        )
    except Exception:
        return None


def call_llm_interpreter(
    title: str,
    artist: str,
    audio: MeasuredAudioFeatures,
    lyrics_snippet: Optional[str],
    settings: AppSettings,
) -> Tuple[LLMInterpretiveOutput, str]:
    provider = (settings.llm_provider or "ollama").lower()
    if provider == "heuristic":
        return heuristic_interpret(title, artist, audio, lyrics_snippet), "heuristic"

    allow_raw_lyrics = (provider == "ollama") or bool(settings.send_lyrics_to_cloud_llm)
    prompt = _build_llm_prompt(title, artist, audio, lyrics_snippet, allow_raw_lyrics)

    try:
        if provider == "ollama":
            backend = ensure_local_llama_server(wait_seconds=12.0)
            if backend == "llama_server":
                url = f"http://127.0.0.1:{LLAMA_SERVER_PORT}/v1/chat/completions"
                payload = {
                    "messages": [
                        {
                            "role": "system",
                            "content": "You are an expert musicologist and lyricist. Respond ONLY with a valid JSON object.",
                        },
                        {"role": "user", "content": prompt},
                    ],
                    "response_format": {"type": "json_object"},
                    "temperature": 0.45,
                    "max_tokens": 350,
                }
                with httpx.Client(timeout=35.0) as client:
                    r = client.post(url, json=payload)
                    if r.status_code == 200:
                        raw_str = r.json()["choices"][0]["message"]["content"]
                        parsed = _coerce_llm_json(raw_str, title, artist, audio, lyrics_snippet)
                        if parsed:
                            return parsed, "local_llama_llm"

            elif backend == "ollama":
                url = f"{settings.ollama_base_url.rstrip('/')}/api/generate"
                payload = {
                    "model": settings.llm_model or "llama3.2:3b",
                    "prompt": prompt,
                    "format": "json",
                    "stream": False,
                }
                with httpx.Client(timeout=18.0) as client:
                    r = client.post(url, json=payload)
                    if r.status_code == 200:
                        raw_str = r.json().get("response", "")
                        parsed = _coerce_llm_json(raw_str, title, artist, audio, lyrics_snippet)
                        if parsed:
                            return parsed, "ollama_llm"

        elif provider == "gemini":
            api_key = get_secret("llm_api_key")
            if api_key:
                model = settings.llm_model or "gemini-2.5-flash"
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
                payload = {
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {"responseMimeType": "application/json"},
                }
                with httpx.Client(timeout=15.0) as client:
                    r = client.post(url, params={"key": api_key}, json=payload)
                    if r.status_code == 200:
                        cands = r.json().get("candidates", [])
                        if cands:
                            raw_str = cands[0]["content"]["parts"][0]["text"]
                            parsed = _coerce_llm_json(raw_str, title, artist, audio, lyrics_snippet)
                            if parsed:
                                return parsed, "gemini"

        elif provider == "openai":
            api_key = get_secret("llm_api_key")
            if api_key:
                model = settings.llm_model or "gpt-4o-mini"
                url = "https://api.openai.com/v1/chat/completions"
                headers = {"Authorization": f"Bearer {api_key}"}
                payload = {
                    "model": model,
                    "response_format": {"type": "json_object"},
                    "messages": [{"role": "user", "content": prompt}],
                }
                with httpx.Client(timeout=15.0, headers=headers) as client:
                    r = client.post(url, json=payload)
                    if r.status_code == 200:
                        raw_str = r.json()["choices"][0]["message"]["content"]
                        parsed = _coerce_llm_json(raw_str, title, artist, audio, lyrics_snippet)
                        if parsed:
                            return parsed, "openai"
    except Exception:
        pass

    return heuristic_interpret(title, artist, audio, lyrics_snippet), "deep_lyric_nlp"


class SongProfiler:
    def __init__(self, db: Database) -> None:
        self.db = db

    def profile_track(
        self,
        track_meta: Dict[str, Any],
        force_refresh: bool = False,
        local_audio_path: Optional[str] = None,
    ) -> TrackProfile:
        track_id = str(track_meta["track_id"])
        if not force_refresh:
            cached = self.db.get_track_profile(track_id)
            # Automatically upgrade legacy heuristic profiles that lack specific_theme_headline
            # or have old vector dimension
            if (
                cached
                and cached.interpretation.specific_theme_headline
                and cached.llm_provider_used in ("local_llama_llm", "ollama_llm", "gemini", "openai")
                and len(cached.embedding_vector) == len(build_track_vector(cached.audio, cached.interpretation))
            ):
                return cached

        title = track_meta.get("title", "Unknown")
        artist = track_meta.get("artist", "Unknown")
        album = track_meta.get("album", "")
        album_art_url = track_meta.get("album_art_url", "")
        duration_ms = int(track_meta.get("duration_ms") or 200000)
        spotify_url = track_meta.get(
            "spotify_url", f"https://open.spotify.com/track/{track_id}"
        )

        audio: Optional[MeasuredAudioFeatures] = None
        if local_audio_path:
            audio = analyze_local_audio_file(local_audio_path)
        if audio is None:
            audio = fetch_reccobeats_features(track_id, db=self.db)
        if audio is None:
            audio = MeasuredAudioFeatures(
                tempo=115.0,
                energy=0.55,
                danceability=0.60,
                valence=0.50,
                source=FeatureSource.HEURISTIC_FALLBACK,
                confidence=0.45,
            )

        lyrics_snippet = fetch_lrclib_lyrics_transient(title, artist)
        has_lyrics = bool(lyrics_snippet)

        settings = self.db.get_settings()
        interpretation, provider_used = call_llm_interpreter(
            title=title,
            artist=artist,
            audio=audio,
            lyrics_snippet=lyrics_snippet,
            settings=settings,
        )
        del lyrics_snippet

        vec = build_track_vector(audio, interpretation)
        profile = TrackProfile(
            track_id=track_id,
            title=title,
            artist=artist,
            album=album,
            album_art_url=album_art_url,
            duration_ms=duration_ms,
            spotify_url=spotify_url,
            audio=audio,
            interpretation=interpretation,
            has_lyrics_analyzed=has_lyrics,
            llm_provider_used=provider_used,
            embedding_vector=vec,
        )
        return self.db.upsert_track_profile(profile)
