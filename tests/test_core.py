"""
Unit tests for PulseMind's core pure logic & state machines:
1. Skip detection thresholds (< 30s OR < 50% completion).
2. Repeat-loop restart detection (progress dropping near 0 after >=30s).
3. PlaybackTracker state transitions (normal play, early skip, repeat loop).
4. Exponential time decay, completion penalty, repeat bonus, and late-night multiplier.
5. Controlled vocabulary vector encoding and cosine similarity ranking.
"""
from __future__ import annotations

import math
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import TasteWeightsConfig
from database import Database
from demo_data import ensure_demo_seeded
from recommender import (
    TasteAndRecommendationEngine,
    compute_play_weight,
    is_late_night_hour,
    modify_taste_vector_for_constraints,
)
from schemas import (
    VECTOR_DIM,
    BeatArchetype,
    FeatureSource,
    LLMInterpretiveOutput,
    LyricalTheme,
    MeasuredAudioFeatures,
    TrackProfile,
    build_track_vector,
    cosine_similarity,
)
from spotify_client import SpotifyClientWrapper
from tracker import PlaybackTracker, is_repeat_restart, is_track_skipped
from analyzer import SongProfiler


def test_skip_detection_thresholds() -> None:
    w = TasteWeightsConfig(skip_min_ms=30000, skip_min_ratio=0.50)

    # 1. Under 30 seconds on a 200s track -> SKIPPED
    assert is_track_skipped(listened_ms=18000, duration_ms=200000, weights=w) is True

    # 2. Over 30 seconds (45s) on a 200s track (22.5% < 50%) -> SKIPPED
    assert is_track_skipped(listened_ms=45000, duration_ms=200000, weights=w) is True

    # 3. 25 seconds on a 40s interlude (62.5% >= 50%, but < 30s) -> SKIPPED
    assert is_track_skipped(listened_ms=25000, duration_ms=40000, weights=w) is True

    # 4. 110 seconds on a 200s track (55% >= 50% and >= 30s) -> NOT SKIPPED
    assert is_track_skipped(listened_ms=110000, duration_ms=200000, weights=w) is False

    # 5. Full listen (200s / 200s) -> NOT SKIPPED
    assert is_track_skipped(listened_ms=200000, duration_ms=200000, weights=w) is False


def test_repeat_loop_detection() -> None:
    w = TasteWeightsConfig(skip_min_ms=30000, repeat_restart_threshold_ms=15000)

    # Track was at 165s and restarted at 3s -> REPEAT LOOP
    assert is_repeat_restart(previous_max_progress_ms=165000, current_progress_ms=3000, weights=w) is True

    # Track was only at 12s and scrubbed back to 2s -> NOT a full repeat loop
    assert is_repeat_restart(previous_max_progress_ms=12000, current_progress_ms=2000, weights=w) is False

    # Normal forward progression from 45s to 50s -> NOT a repeat restart
    assert is_repeat_restart(previous_max_progress_ms=45000, current_progress_ms=50000, weights=w) is False


def test_tracker_state_machine_commits_skips_and_repeats() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        db = Database(Path(tmpdir) / "test.db")
        sp = SpotifyClientWrapper()
        profiler = SongProfiler(db)

        # Seed two dummy profiles so foreign key is satisfied without network
        for tid, title in [("track_A", "Song A"), ("track_B", "Song B"), ("track_C", "Song C")]:
            db.upsert_track_profile(
                TrackProfile(
                    track_id=tid,
                    title=title,
                    artist="Test Artist",
                    duration_ms=200000,
                    audio=MeasuredAudioFeatures(tempo=100.0, source=FeatureSource.RECCOBEATS),
                    interpretation=LLMInterpretiveOutput(
                        beat_archetype=BeatArchetype.BOOM_BAP,
                        primary_theme=LyricalTheme.AMBITION_HUSTLE,
                    ),
                )
            )

        tracker = PlaybackTracker(db=db, spotify=sp, on_track_need_profile=None)

        # Start Track A at 5s, advance to 140s, then restart at 4s (1 repeat loop!)
        assert tracker.process_playback_snapshot(
            {"track_id": "track_A", "title": "Song A", "artist": "Test Artist", "duration_ms": 200000, "progress_ms": 5000},
            now_ts=1000.0,
        ) is None
        assert tracker.process_playback_snapshot(
            {"track_id": "track_A", "title": "Song A", "artist": "Test Artist", "duration_ms": 200000, "progress_ms": 140000},
            now_ts=1135.0,
        ) is None
        assert tracker.process_playback_snapshot(
            {"track_id": "track_A", "title": "Song A", "artist": "Test Artist", "duration_ms": 200000, "progress_ms": 4000},
            now_ts=1205.0,
        ) is None
        assert tracker.active is not None
        assert tracker.active.repeat_count == 1

        # Switch to Track B -> commits Track A as NOT skipped with repeat_count == 1
        committed_a = tracker.process_playback_snapshot(
            {"track_id": "track_B", "title": "Song B", "artist": "Test Artist", "duration_ms": 200000, "progress_ms": 2000},
            now_ts=1300.0,
        )
        assert committed_a is not None
        assert committed_a["track_id"] == "track_A"
        assert committed_a["was_skipped"] is False
        assert committed_a["repeat_count"] == 1

        # Advance Track B only to 14s, then switch to Track C -> commits Track B as SKIPPED!
        tracker.process_playback_snapshot(
            {"track_id": "track_B", "title": "Song B", "artist": "Test Artist", "duration_ms": 200000, "progress_ms": 14000},
            now_ts=1312.0,
        )
        committed_b = tracker.process_playback_snapshot(
            {"track_id": "track_C", "title": "Song C", "artist": "Test Artist", "duration_ms": 200000, "progress_ms": 1000},
            now_ts=1315.0,
        )
        assert committed_b is not None
        assert committed_b["track_id"] == "track_B"
        assert committed_b["was_skipped"] is True
        assert committed_b["repeat_count"] == 0


def test_taste_weighting_and_exponential_decay() -> None:
    w = TasteWeightsConfig(
        half_life_days=14.0,
        full_listen_weight=1.0,
        skip_penalty_weight=0.15,
        repeat_bonus_per_loop=0.45,
        late_night_boost=1.35,
        late_night_start_hour=22,
        late_night_end_hour=4,
    )
    now = 1_700_000_000.0

    # 1. Fresh full play during daytime (14:00)
    w_fresh = compute_play_weight(
        played_at_ts=now,
        now_ts=now,
        completion_ratio=1.0,
        was_skipped=False,
        repeat_count=0,
        hour_of_day=14,
        weights=w,
    )
    assert math.isclose(w_fresh, 1.0, rel_tol=1e-4)

    # 2. Exactly 1 half-life old (14 days ago) -> weight should be 0.5
    w_half_life = compute_play_weight(
        played_at_ts=now - (14.0 * 86400.0),
        now_ts=now,
        completion_ratio=1.0,
        was_skipped=False,
        repeat_count=0,
        hour_of_day=14,
        weights=w,
    )
    assert math.isclose(w_half_life, 0.5, rel_tol=1e-4)

    # 3. Skipped play gets penalized to 0.15
    w_skipped = compute_play_weight(
        played_at_ts=now,
        now_ts=now,
        completion_ratio=0.10,
        was_skipped=True,
        repeat_count=0,
        hour_of_day=14,
        weights=w,
    )
    assert math.isclose(w_skipped, 0.15, rel_tol=1e-4)

    # 4. Late-night (23:00) with 2 repeat loops -> 1.0 * (1 + 2*0.45) * 1.35 = 1.9 * 1.35 = 2.565
    w_night_repeat = compute_play_weight(
        played_at_ts=now,
        now_ts=now,
        completion_ratio=1.0,
        was_skipped=False,
        repeat_count=2,
        hour_of_day=23,
        weights=w,
    )
    assert math.isclose(w_night_repeat, 2.565, rel_tol=1e-4)
    assert is_late_night_hour(23) is True
    assert is_late_night_hour(2) is True
    assert is_late_night_hour(15) is False


def test_vector_encoding_and_cosine_similarity() -> None:
    audio_boom = MeasuredAudioFeatures(tempo=92.0, energy=0.65, danceability=0.78, valence=0.55)
    interp_boom = LLMInterpretiveOutput(
        beat_archetype=BeatArchetype.BOOM_BAP,
        primary_theme=LyricalTheme.AMBITION_HUSTLE,
        secondary_theme=LyricalTheme.RESILIENCE_OVERCOMING,
    )
    vec_boom_1 = build_track_vector(audio_boom, interp_boom)
    assert len(vec_boom_1) == VECTOR_DIM

    # Slightly different BPM (95 BPM) but same BeatArchetype and primary theme
    audio_boom_2 = MeasuredAudioFeatures(tempo=95.0, energy=0.62, danceability=0.75, valence=0.58)
    vec_boom_2 = build_track_vector(audio_boom_2, interp_boom)

    # Completely different style: Ambient Drone & Melancholy Grief
    audio_ambient = MeasuredAudioFeatures(tempo=65.0, energy=0.15, danceability=0.20, valence=0.15, acousticness=0.85)
    interp_ambient = LLMInterpretiveOutput(
        beat_archetype=BeatArchetype.AMBIENT_DRONE,
        primary_theme=LyricalTheme.MELANCHOLY_GRIEF,
    )
    vec_ambient = build_track_vector(audio_ambient, interp_ambient)

    sim_same_style = cosine_similarity(vec_boom_1, vec_boom_2)
    sim_diff_style = cosine_similarity(vec_boom_1, vec_ambient)
    assert sim_same_style > 0.98
    assert sim_diff_style < 0.25

    # Constraint blending shifts vector toward target beat + theme
    constrained = modify_taste_vector_for_constraints(
        vec_ambient,
        target_beat=BeatArchetype.BOOM_BAP,
        target_theme=LyricalTheme.AMBITION_HUSTLE,
        target_bpm=92.0,
    )
    assert cosine_similarity(constrained, vec_boom_1) > cosine_similarity(vec_ambient, vec_boom_1)


def test_demo_seed_and_playlist_draft_pipeline() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        db = Database(Path(tmpdir) / "demo_test.db")
        ensure_demo_seeded(db)
        # Mark seeded events as live plays (is_demo=0) since demo_mode is removed
        with db._write_lock:
            conn = db._connect()
            conn.execute("UPDATE play_events SET is_demo = 0")
            conn.commit()
            conn.close()
        sp = SpotifyClientWrapper()
        profiler = SongProfiler(db)
        engine = TasteAndRecommendationEngine(db, profiler, sp)

        dna = engine.compute_taste_dna()
        assert dna["total_plays"] >= 8
        assert len(dna["beat_distribution"]) >= 4
        assert len(dna["theme_distribution"]) >= 4

        draft = engine.generate_personalized_playlist(
            prompt="gritty boom-bap beat with a hopeful message about overcoming self-doubt",
            playlist_size=5,
        )
        assert draft["draft_id"].startswith("draft_")
        assert len(draft["tracks"]) == 5
        top_track = draft["tracks"][0]
        assert top_track["match_percent"] >= 70


def test_fastapi_endpoints_end_to_end() -> None:
    from fastapi.testclient import TestClient
    from app import app, db
    from demo_data import get_curated_candidate_catalog

    cat = get_curated_candidate_catalog()[0]
    db.upsert_track_profile(cat)
    db.record_play_event(
        track_id=cat.track_id,
        listened_ms=cat.duration_ms,
        duration_ms=cat.duration_ms,
        was_skipped=False,
        repeat_count=1,
        is_demo=False,
    )

    client = TestClient(app)

    r_status = client.get("/api/status")
    assert r_status.status_code == 200
    st = r_status.json()
    assert "now_playing" in st
    assert st["privacy_mode"] == "local_only"

    r_dna = client.get("/api/taste-dna")
    assert r_dna.status_code == 200
    dna = r_dna.json()
    assert dna["total_plays"] > 0
    assert len(dna["taste_vector"]) == VECTOR_DIM

    r_prev = client.post(
        "/api/playlist/preview",
        json={
            "prompt": "synthwave night drive with escapism theme",
            "beat_archetype": "synthwave_pulse",
            "lyrical_theme": "escapism_wanderlust",
            "playlist_size": 4,
        },
    )
    assert r_prev.status_code == 200
    draft = r_prev.json()["draft"]
    assert len(draft["tracks"]) == 4
    assert draft["tracks"][0]["beat_archetype"] == "synthwave_pulse"

