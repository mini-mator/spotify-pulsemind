"""
Taste DNA Engine & Hyper-Personalized Recommender (`recommender.py`).
- Exponential time-decay play weighting (completion, skip penalty, repeat bonus, late-night boost).
- Computes a unified 34-D Taste DNA vector and controlled-vocabulary distributions.
- Generates candidates via ReccoBeats `/v1/track/recommendation`, Last.fm `track.getSimilar`,
  LLM prompt suggestions (verified via Spotify search), and local catalog.
- Scores every candidate deterministically using Cosine Similarity against the user's Taste DNA
  and target Beat Archetype / Lyrical Theme constraints.
"""
from __future__ import annotations

import json
import math
import re
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

import httpx

from analyzer import SongProfiler, _http_get_with_backoff
from config import TasteWeightsConfig, get_secret
from database import Database
from demo_data import get_curated_candidate_catalog
from schemas import (
    BEAT_ARCHETYPE_LABELS,
    LYRICAL_THEME_LABELS,
    ORDERED_BEAT_ARCHETYPES,
    ORDERED_LYRICAL_THEMES,
    VECTOR_DIM,
    BeatArchetype,
    LyricalTheme,
    TrackProfile,
    build_track_vector,
    cosine_similarity,
)
from spotify_client import SpotifyClientWrapper


def is_late_night_hour(hour: int, start_hour: int = 22, end_hour: int = 4) -> bool:
    if start_hour <= end_hour:
        return start_hour <= hour <= end_hour
    return hour >= start_hour or hour <= end_hour


def compute_play_weight(
    played_at_ts: float,
    now_ts: float,
    completion_ratio: float,
    was_skipped: bool,
    repeat_count: int,
    hour_of_day: int,
    weights: TasteWeightsConfig,
) -> float:
    """
    Pure logic function for play event weighting (unit-tested).
    Combines exponential time decay, completion/skip factor, repeat loop bonus,
    and late-night listening multiplier.
    """
    age_days = max(0.0, (now_ts - played_at_ts) / 86400.0)
    half_life = max(0.5, weights.half_life_days)
    decay = math.exp(-math.log(2.0) * age_days / half_life)

    if was_skipped:
        completion_factor = weights.skip_penalty_weight
    else:
        clamped_ratio = max(0.25, min(1.0, completion_ratio))
        completion_factor = clamped_ratio * weights.full_listen_weight

    repeat_multiplier = 1.0 + (max(0, repeat_count) * weights.repeat_bonus_per_loop)
    night_multiplier = (
        weights.late_night_boost
        if is_late_night_hour(hour_of_day, weights.late_night_start_hour, weights.late_night_end_hour)
        else 1.0
    )

    return round(decay * completion_factor * repeat_multiplier * night_multiplier, 6)


def modify_taste_vector_for_constraints(
    base_vector: List[float],
    target_beat: Optional[BeatArchetype] = None,
    target_theme: Optional[LyricalTheme] = None,
    target_bpm: Optional[float] = None,
    target_energy: Optional[float] = None,
    target_valence: Optional[float] = None,
) -> List[float]:
    """
    Blends the user's personal Taste DNA vector with explicit filter constraints
    (Beat Archetype, Lyrical Theme, BPM, Energy, Valence) and normalizes to unit length.
    """
    vec = list(base_vector) if len(base_vector) == VECTOR_DIM else [0.1] * VECTOR_DIM

    if target_bpm is not None:
        vec[0] = max(0.0, min(1.0, (target_bpm - 50.0) / 150.0)) * 1.5
    if target_energy is not None:
        vec[1] = max(0.0, min(1.0, target_energy)) * 1.5
    if target_valence is not None:
        vec[3] = max(0.0, min(1.0, target_valence)) * 1.5

    beat_offset = 8
    if target_beat is not None:
        for idx, b in enumerate(ORDERED_BEAT_ARCHETYPES):
            vec[beat_offset + idx] = 1.8 if b == target_beat else vec[beat_offset + idx] * 0.25

    theme_offset = 8 + len(ORDERED_BEAT_ARCHETYPES)
    if target_theme is not None:
        for idx, t in enumerate(ORDERED_LYRICAL_THEMES):
            vec[theme_offset + idx] = 1.8 if t == target_theme else vec[theme_offset + idx] * 0.25

    norm = math.sqrt(sum(x * x for x in vec))
    if norm > 1e-9:
        return [round(x / norm, 6) for x in vec]
    return vec


class TasteAndRecommendationEngine:
    def __init__(
        self,
        db: Database,
        profiler: SongProfiler,
        spotify: SpotifyClientWrapper,
    ) -> None:
        self.db = db
        self.profiler = profiler
        self.spotify = spotify

    def compute_taste_dna(self, now_ts: Optional[float] = None) -> Dict[str, Any]:
        """
        Computes the user's weighted Taste DNA vector, top Beat Archetypes,
        top Lyrical Themes, sonic sweet spots, and listening behavior stats.
        """
        now = now_ts if now_ts is not None else time.time()
        settings = self.db.get_settings()
        weights = settings.weights
        plays = self.db.get_play_events(include_demo=False, limit=500)
        profiles = self.db.get_all_track_profiles()

        if not plays:
            return {
                "total_plays": 0,
                "skip_rate": 0.0,
                "repeat_rate": 0.0,
                "late_night_share": 0.0,
                "avg_bpm": 120.0,
                "avg_energy": 0.5,
                "avg_danceability": 0.5,
                "avg_valence": 0.5,
                "taste_vector": [0.0] * VECTOR_DIM,
                "beat_distribution": [],
                "theme_distribution": [],
                "top_seed_track_ids": [],
                "top_tracks": [],
            }

        accum_vec = [0.0] * VECTOR_DIM
        total_weight = 0.0
        beat_weights: Dict[str, float] = {}
        theme_weights: Dict[str, float] = {}
        track_weights: Dict[str, float] = {}

        weighted_bpm = 0.0
        weighted_energy = 0.0
        weighted_dance = 0.0
        weighted_valence = 0.0

        skipped_count = 0
        repeat_events = 0
        late_night_count = 0

        for ev in plays:
            tid = ev["track_id"]
            prof = profiles.get(tid)
            if not prof:
                continue

            was_skipped = bool(ev["was_skipped"])
            repeats = int(ev["repeat_count"])
            hour = int(ev["hour_of_day"])
            if was_skipped:
                skipped_count += 1
            if repeats > 0:
                repeat_events += 1
            if is_late_night_hour(hour, weights.late_night_start_hour, weights.late_night_end_hour):
                late_night_count += 1

            w = compute_play_weight(
                played_at_ts=float(ev["played_at_ts"]),
                now_ts=now,
                completion_ratio=float(ev["completion_ratio"]),
                was_skipped=was_skipped,
                repeat_count=repeats,
                hour_of_day=hour,
                weights=weights,
            )
            total_weight += w
            track_weights[tid] = track_weights.get(tid, 0.0) + w

            vec = prof.embedding_vector
            if len(vec) != VECTOR_DIM:
                vec = build_track_vector(prof.audio, prof.interpretation)
            for i in range(VECTOR_DIM):
                accum_vec[i] += vec[i] * w

            weighted_bpm += prof.audio.tempo * w
            weighted_energy += prof.audio.energy * w
            weighted_dance += prof.audio.danceability * w
            weighted_valence += prof.audio.valence * w

            b_key = prof.interpretation.beat_archetype.value
            beat_weights[b_key] = beat_weights.get(b_key, 0.0) + w

            t1_key = prof.interpretation.primary_theme.value
            theme_weights[t1_key] = theme_weights.get(t1_key, 0.0) + w
            if prof.interpretation.secondary_theme:
                t2_key = prof.interpretation.secondary_theme.value
                theme_weights[t2_key] = theme_weights.get(t2_key, 0.0) + (w * 0.5)

        norm = math.sqrt(sum(x * x for x in accum_vec))
        taste_vector = [round(x / norm, 6) for x in accum_vec] if norm > 1e-9 else accum_vec
        denom = max(1e-6, total_weight)

        beat_dist = [
            {
                "id": k,
                "label": BEAT_ARCHETYPE_LABELS.get(BeatArchetype(k), k),
                "weight": round(v, 3),
                "share": round((v / denom) * 100.0, 1),
            }
            for k, v in sorted(beat_weights.items(), key=lambda x: x[1], reverse=True)
        ]

        theme_total = max(1e-6, sum(theme_weights.values()))
        theme_dist = [
            {
                "id": k,
                "label": LYRICAL_THEME_LABELS.get(LyricalTheme(k), k),
                "weight": round(v, 3),
                "share": round((v / theme_total) * 100.0, 1),
            }
            for k, v in sorted(theme_weights.items(), key=lambda x: x[1], reverse=True)
        ]

        sorted_tracks = sorted(track_weights.items(), key=lambda x: x[1], reverse=True)
        top_seed_ids = [
            tid for tid, _ in sorted_tracks
            if not tid.startswith("winmedia_") and not tid.startswith("local_")
        ][:5]

        top_tracks_summary = []
        for tid, tw in sorted_tracks[:6]:
            p = profiles[tid]
            top_tracks_summary.append(
                {
                    "track_id": tid,
                    "title": p.title,
                    "artist": p.artist,
                    "weight": round(tw, 2),
                    "bpm": round(p.audio.tempo, 1),
                    "beat_label": BEAT_ARCHETYPE_LABELS.get(p.interpretation.beat_archetype, ""),
                    "theme_label": LYRICAL_THEME_LABELS.get(p.interpretation.primary_theme, ""),
                }
            )

        total_plays = len(plays)
        return {
            "total_plays": total_plays,
            "skip_rate": round((skipped_count / total_plays) * 100.0, 1),
            "repeat_rate": round((repeat_events / total_plays) * 100.0, 1),
            "late_night_share": round((late_night_count / total_plays) * 100.0, 1),
            "avg_bpm": round(weighted_bpm / denom, 1),
            "avg_energy": round(weighted_energy / denom, 2),
            "avg_danceability": round(weighted_dance / denom, 2),
            "avg_valence": round(weighted_valence / denom, 2),
            "taste_vector": taste_vector,
            "beat_distribution": beat_dist,
            "theme_distribution": theme_dist,
            "top_seed_track_ids": top_seed_ids,
            "top_tracks": top_tracks_summary,
        }

    def _fetch_reccobeats_candidates(self, seed_track_ids: List[str], size: int = 10) -> List[Dict[str, Any]]:
        if not seed_track_ids:
            return []
        seeds_csv = ",".join(seed_track_ids[:5])
        cache_key = f"reccobeats_rec::{seeds_csv}::{size}"
        cached = self.db.get_cache(cache_key)
        if cached:
            return cached

        data = _http_get_with_backoff(
            "https://api.reccobeats.com/v1/track/recommendation",
            params={"seeds": seeds_csv, "size": size},
            timeout=10.0,
        )
        if not data or not isinstance(data.get("content"), list):
            return []

        candidates = []
        for item in data["content"]:
            href = item.get("href") or ""
            m = re.search(r"spotify\.com/track/([A-Za-z0-9]+)", href)
            if not m:
                continue
            spotify_tid = m.group(1)
            artists = ", ".join(a.get("name", "") for a in item.get("artists", []) if a.get("name"))
            candidates.append(
                {
                    "track_id": spotify_tid,
                    "title": item.get("trackTitle") or "Unknown",
                    "artist": artists or "Unknown Artist",
                    "album": "",
                    "duration_ms": int(item.get("durationMs") or 200000),
                    "spotify_url": f"https://open.spotify.com/track/{spotify_tid}",
                    "candidate_origin": "reccobeats_seed",
                }
            )
        if candidates:
            self.db.set_cache(cache_key, candidates, ttl_seconds=3600 * 6)
        return candidates

    def _fetch_lastfm_candidates(self, seed_tracks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        api_key = get_secret("lastfm_api_key")
        if not api_key or not seed_tracks:
            return []
        results = []
        for seed in seed_tracks[:2]:
            data = _http_get_with_backoff(
                "https://ws.audioscrobbler.com/2.0/",
                params={
                    "method": "track.getSimilar",
                    "artist": seed["artist"].split(",")[0].strip(),
                    "track": seed["title"],
                    "api_key": api_key,
                    "format": "json",
                    "limit": 5,
                },
                timeout=8.0,
            )
            sim_tracks = (data or {}).get("similartracks", {}).get("track", [])
            for st in sim_tracks:
                title = st.get("name")
                artist = (st.get("artist") or {}).get("name")
                if title and artist and self.spotify.is_authenticated():
                    verified = self.spotify.search_track(title, artist)
                    if verified:
                        verified["candidate_origin"] = "lastfm_similar"
                        results.append(verified)
        return results

    def _parse_prompt_intent(
        self, prompt: str
    ) -> Tuple[Optional[BeatArchetype], Optional[LyricalTheme]]:
        if not prompt:
            return None, None
        low = prompt.lower()
        beat_match: Optional[BeatArchetype] = None
        theme_match: Optional[LyricalTheme] = None

        beat_keywords = {
            BeatArchetype.BOOM_BAP: ["boom bap", "boom-bap", "90s hip hop", "swung", "jazz rap"],
            BeatArchetype.TRAP_808: ["trap", "808", "half-time", "bounce", "hard"],
            BeatArchetype.SYNTHWAVE_PULSE: ["synthwave", "80s", "neon", "synth", "arpeggio", "retro"],
            BeatArchetype.NEO_SOUL_POCKET: ["neo-soul", "neo soul", "dilla", "laid back", "rhodes", "warm pocket"],
            BeatArchetype.RNB_SLOW_JAM: ["r&b", "rnb", "slow jam", "nocturnal"],
            BeatArchetype.FOUR_ON_THE_FLOOR: ["house", "four on the floor", "4-on-the-floor", "club", "techno"],
            BeatArchetype.INDIE_MOTORIK: ["indie", "motorik", "dream pop", "breezy"],
            BeatArchetype.ACOUSTIC_FINGERSTYLE: ["acoustic", "unplugged", "guitar", "folk"],
            BeatArchetype.BREAKBEAT_DNB: ["dnb", "drum and bass", "breakbeat", "jungle"],
        }
        for archetype, kw_list in beat_keywords.items():
            if any(k in low for k in kw_list):
                beat_match = archetype
                break

        theme_keywords = {
            LyricalTheme.RESILIENCE_OVERCOMING: ["overcoming", "resilience", "self-doubt", "hope", "hopeful", "strong", "healing"],
            LyricalTheme.AMBITION_HUSTLE: ["ambition", "hustle", "focus", "grind", "motivation", "drive", "success"],
            LyricalTheme.LATE_NIGHT_INTROSPECTION: ["late night", "late-night", "introspection", "solitude", "3am", "reflective", "deep"],
            LyricalTheme.ESCAPISM_WANDERLUST: ["night drive", "escapism", "freedom", "highway", "wanderlust", "city lights"],
            LyricalTheme.ROMANTIC_DEVOTION: ["love", "romantic", "devotion", "intimate", "affection"],
            LyricalTheme.HEARTBREAK_LONGING: ["heartbreak", "missing", "longing", "breakup", "nostalgia"],
            LyricalTheme.SOCIAL_COMMENTARY: ["social", "conscious", "system", "political", "truth"],
            LyricalTheme.MINDFULNESS_PEACE: ["peace", "calm", "mindfulness", "serenity", "chill", "gratitude"],
            LyricalTheme.EUPHORIA_CELEBRATION: ["euphoria", "joy", "celebration", "party", "upbeat"],
        }
        for theme, kw_list in theme_keywords.items():
            if any(k in low for k in kw_list):
                theme_match = theme
                break

        return beat_match, theme_match

    def generate_personalized_playlist(
        self,
        prompt: str = "",
        beat_archetype: Optional[str] = None,
        lyrical_theme: Optional[str] = None,
        target_bpm: Optional[float] = None,
        target_energy: Optional[float] = None,
        target_valence: Optional[float] = None,
        playlist_size: int = 8,
    ) -> Dict[str, Any]:
        """
        Builds a hyper-personalized playlist draft ranked by Cosine Similarity against the
        user's Taste DNA + prompt/filter constraints.
        Returns a preview draft object ready for user inspection and optional Spotify export.
        """
        dna = self.compute_taste_dna()
        inferred_beat, inferred_theme = self._parse_prompt_intent(prompt)

        chosen_beat: Optional[BeatArchetype] = None
        if beat_archetype and beat_archetype != "any":
            try:
                chosen_beat = BeatArchetype(beat_archetype)
            except ValueError:
                chosen_beat = inferred_beat
        else:
            chosen_beat = inferred_beat

        chosen_theme: Optional[LyricalTheme] = None
        if lyrical_theme and lyrical_theme != "any":
            try:
                chosen_theme = LyricalTheme(lyrical_theme)
            except ValueError:
                chosen_theme = inferred_theme
        else:
            chosen_theme = inferred_theme

        target_vec = modify_taste_vector_for_constraints(
            base_vector=dna["taste_vector"],
            target_beat=chosen_beat,
            target_theme=chosen_theme,
            target_bpm=target_bpm,
            target_energy=target_energy,
            target_valence=target_valence,
        )

        # Gather candidate pool from multiple verified sources
        candidate_profiles: Dict[str, Tuple[TrackProfile, str]] = {}

        # 1. Curated verified catalog + existing profiled tracks in DB
        for cat_p in get_curated_candidate_catalog():
            p = self.db.get_track_profile(cat_p.track_id) or self.db.upsert_track_profile(cat_p)
            candidate_profiles[p.track_id] = (p, "verified_catalog")

        for tid, prof in self.db.get_all_track_profiles().items():
            if tid not in candidate_profiles:
                candidate_profiles[tid] = (prof, "listening_history")

        # 2. Live ReccoBeats seed recommendations from user's top seed tracks
        seed_ids = dna.get("top_seed_track_ids", [])
        rb_cands = self._fetch_reccobeats_candidates(seed_ids, size=8)
        for rc in rb_cands:
            tid = rc["track_id"]
            if tid not in candidate_profiles:
                prof = self.profiler.profile_track(rc)
                candidate_profiles[tid] = (prof, "reccobeats_seed")

        # 3. Optional Last.fm similar tracks
        lfm_cands = self._fetch_lastfm_candidates(dna.get("top_tracks", []))
        for lc in lfm_cands:
            tid = lc["track_id"]
            if tid not in candidate_profiles:
                prof = self.profiler.profile_track(lc)
                candidate_profiles[tid] = (prof, "lastfm_similar")

        # Score every candidate via Cosine Similarity + exact archetype/theme match boost
        scored_items: List[Dict[str, Any]] = []
        for tid, (prof, origin) in candidate_profiles.items():
            cand_vec = (
                prof.embedding_vector
                if len(prof.embedding_vector) == VECTOR_DIM
                else build_track_vector(prof.audio, prof.interpretation)
            )
            sim = cosine_similarity(target_vec, cand_vec)
            bonus = 0.0
            reasons = []

            if chosen_beat and prof.interpretation.beat_archetype == chosen_beat:
                bonus += 0.14
                reasons.append(f"Exact Beat Match: {BEAT_ARCHETYPE_LABELS[chosen_beat]}")
            else:
                reasons.append(f"Groove: {BEAT_ARCHETYPE_LABELS.get(prof.interpretation.beat_archetype, 'Custom')}")

            headline_or_theme = (
                prof.interpretation.specific_theme_headline
                or LYRICAL_THEME_LABELS.get(prof.interpretation.primary_theme, "Custom")
            )
            if chosen_theme and (
                prof.interpretation.primary_theme == chosen_theme
                or prof.interpretation.secondary_theme == chosen_theme
            ):
                bonus += 0.14
                reasons.append(f"Exact Theme Match: {headline_or_theme}")
            else:
                reasons.append(f"Theme: {headline_or_theme}")

            if target_bpm is not None:
                bpm_diff = abs(prof.audio.tempo - target_bpm)
                if bpm_diff <= 10:
                    bonus += 0.06
                    reasons.append(f"BPM Locked ({prof.audio.tempo:.0f} BPM)")
                elif bpm_diff > 35:
                    bonus -= 0.08

            final_score = max(0.05, min(0.99, (sim * 0.82) + bonus))
            match_pct = int(round(final_score * 100))

            scored_items.append(
                {
                    "track_id": prof.track_id,
                    "title": prof.title,
                    "artist": prof.artist,
                    "album": prof.album,
                    "spotify_url": prof.spotify_url,
                    "match_score": round(final_score, 4),
                    "match_percent": match_pct,
                    "cosine_similarity": round(sim, 4),
                    "candidate_origin": origin,
                    "bpm": round(prof.audio.tempo, 1),
                    "energy": round(prof.audio.energy, 2),
                    "danceability": round(prof.audio.danceability, 2),
                    "valence": round(prof.audio.valence, 2),
                    "feature_source": prof.audio.source.value,
                    "feature_confidence": prof.audio.confidence,
                    "beat_archetype": prof.interpretation.beat_archetype.value,
                    "beat_label": BEAT_ARCHETYPE_LABELS.get(prof.interpretation.beat_archetype, ""),
                    "beat_descriptor": prof.interpretation.beat_descriptor,
                    "primary_theme": prof.interpretation.primary_theme.value,
                    "theme_label": LYRICAL_THEME_LABELS.get(prof.interpretation.primary_theme, ""),
                    "specific_theme_headline": prof.interpretation.specific_theme_headline,
                    "key_lyric_motif": prof.interpretation.key_lyric_motif,
                    "music_message": prof.interpretation.music_message,
                    "emotional_arc": prof.interpretation.emotional_arc,
                    "custom_tags": prof.interpretation.custom_tags,
                    "why_matched": " • ".join(reasons),
                }
            )

        scored_items.sort(key=lambda x: x["match_score"], reverse=True)
        selected = scored_items[: max(1, min(25, playlist_size))]

        # Construct Playlist Title & Description
        beat_title = BEAT_ARCHETYPE_LABELS.get(chosen_beat, "Personal Sonic DNA").split("/")[0].strip() if chosen_beat else "Sonic DNA"
        theme_title = LYRICAL_THEME_LABELS.get(chosen_theme, "Deep Message").split("&")[0].strip() if chosen_theme else "Curated Flow"
        playlist_name = f"PulseMind: {beat_title} × {theme_title}"
        playlist_desc = (
            f"Hyper-personalized by PulseMind. Prompt: '{prompt or 'Taste DNA Blend'}' | "
            f"Avg Tempo: {dna['avg_bpm']} BPM."
        )

        draft_id = f"draft_{uuid.uuid4().hex[:10]}"
        prompt_ctx = {
            "prompt": prompt,
            "beat_archetype": chosen_beat.value if chosen_beat else "any",
            "lyrical_theme": chosen_theme.value if chosen_theme else "any",
            "target_bpm": target_bpm,
            "target_energy": target_energy,
            "target_valence": target_valence,
        }
        return self.db.save_playlist_draft(
            draft_id=draft_id,
            name=playlist_name,
            description=playlist_desc,
            prompt_context=prompt_ctx,
            tracks=selected,
        )
