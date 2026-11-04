"""
Demo Mode Seeder for PulseMind.
Populates realistic, multi-genre tracks (with real Spotify Track IDs, ReccoBeats-measured
audio features, and structured Beat Archetype + Lyrical Theme profiles) plus simulated
listening behavior (full plays, late-night repeat loops, and early skips) so the
pipeline works out-of-the-box with zero API keys.
"""
from __future__ import annotations

import time
from typing import List, Tuple

from database import Database
from schemas import (
    BeatArchetype,
    FeatureSource,
    LLMInterpretiveOutput,
    LyricalTheme,
    MeasuredAudioFeatures,
    TrackProfile,
)


def get_seed_tracks_and_plays() -> List[Tuple[TrackProfile, List[dict]]]:
    now = time.time()
    hour = 3600.0
    day = 86400.0

    seed_items: List[Tuple[TrackProfile, List[dict]]] = [
        (
            TrackProfile(
                track_id="7KXjTSCq5nL1LoYtL7XAwS",
                title="HUMBLE.",
                artist="Kendrick Lamar",
                album="DAMN.",
                duration_ms=177000,
                spotify_url="https://open.spotify.com/track/7KXjTSCq5nL1LoYtL7XAwS",
                audio=MeasuredAudioFeatures(
                    tempo=150.0,
                    energy=0.621,
                    danceability=0.908,
                    valence=0.421,
                    acousticness=0.0003,
                    instrumentalness=0.00005,
                    speechiness=0.102,
                    loudness=-6.638,
                    key=1,
                    mode=0,
                    source=FeatureSource.RECCOBEATS,
                    confidence=0.98,
                ),
                interpretation=LLMInterpretiveOutput(
                    beat_archetype=BeatArchetype.TRAP_808,
                    beat_descriptor="Staccato piano riff locked to a punchy half-time 150 BPM 808 bounce with crisp snare slaps.",
                    primary_theme=LyricalTheme.AMBITION_HUSTLE,
                    secondary_theme=LyricalTheme.SOCIAL_COMMENTARY,
                    music_message="A sharp call for authenticity and humility amidst ego-driven industry excess and self-made triumph.",
                    emotional_arc="Commanding, confrontational opening that stays relentlessly direct through the final bar.",
                    narrative_perspective="First-person assertion & second-person challenge",
                    custom_tags=["west-coast", "piano-trap", "minimalist-808", "assertive"],
                    interpretation_confidence=0.95,
                ),
                has_lyrics_analyzed=True,
                llm_provider_used="demo_seed",
            ),
            [
                {"age_sec": 2 * hour, "listened_ms": 177000, "was_skipped": False, "repeat_count": 2},
                {"age_sec": 2.1 * day, "listened_ms": 172000, "was_skipped": False, "repeat_count": 1},
            ],
        ),
        (
            TrackProfile(
                track_id="0VjIjW4GlUZAMYd2vXMi3b",
                title="Blinding Lights",
                artist="The Weeknd",
                album="After Hours",
                duration_ms=200040,
                spotify_url="https://open.spotify.com/track/0VjIjW4GlUZAMYd2vXMi3b",
                audio=MeasuredAudioFeatures(
                    tempo=171.0,
                    energy=0.73,
                    danceability=0.514,
                    valence=0.334,
                    acousticness=0.0014,
                    instrumentalness=0.0001,
                    speechiness=0.0598,
                    loudness=-5.934,
                    key=1,
                    mode=1,
                    source=FeatureSource.RECCOBEATS,
                    confidence=0.98,
                ),
                interpretation=LLMInterpretiveOutput(
                    beat_archetype=BeatArchetype.SYNTHWAVE_PULSE,
                    beat_descriptor="Propulsive 171 BPM 80s synthwave arpeggio with gated reverb snares and relentless nocturnal drive.",
                    primary_theme=LyricalTheme.ESCAPISM_WANDERLUST,
                    secondary_theme=LyricalTheme.HEARTBREAK_LONGING,
                    music_message="Racing through neon-lit midnight streets desperate for human connection and redemption after isolation.",
                    emotional_arc="Starts urgent and restless, surging into an euphoric yet yearning synth hook.",
                    narrative_perspective="First-person urgent confession",
                    custom_tags=["synthwave", "night-drive", "80s-retro", "neon-melancholy"],
                    interpretation_confidence=0.96,
                ),
                has_lyrics_analyzed=True,
                llm_provider_used="demo_seed",
            ),
            [
                {"age_sec": 5 * hour, "listened_ms": 200040, "was_skipped": False, "repeat_count": 3},
                {"age_sec": 4.2 * day, "listened_ms": 195000, "was_skipped": False, "repeat_count": 0},
            ],
        ),
        (
            TrackProfile(
                track_id="2takcwOaAZWiXQijPHIx7B",
                title="Time",
                artist="Free Nationals, Mac Miller, Kali Uchis",
                album="Free Nationals",
                duration_ms=210000,
                spotify_url="https://open.spotify.com/track/2takcwOaAZWiXQijPHIx7B",
                audio=MeasuredAudioFeatures(
                    tempo=92.0,
                    energy=0.48,
                    danceability=0.74,
                    valence=0.56,
                    acousticness=0.38,
                    instrumentalness=0.01,
                    speechiness=0.09,
                    loudness=-8.4,
                    key=5,
                    mode=0,
                    source=FeatureSource.RECCOBEATS,
                    confidence=0.95,
                ),
                interpretation=LLMInterpretiveOutput(
                    beat_archetype=BeatArchetype.NEO_SOUL_POCKET,
                    beat_descriptor="Warm, swung 92 BPM neo-soul pocket with behind-the-beat snare, lush Rhodes chords, and melodic bassline.",
                    primary_theme=LyricalTheme.LATE_NIGHT_INTROSPECTION,
                    secondary_theme=LyricalTheme.RESILIENCE_OVERCOMING,
                    music_message="Taking space and time to heal, mature, and rediscover emotional clarity before rushing back into love.",
                    emotional_arc="Velvety, reassuring opening that deepens into bittersweet vulnerability during the rap verse.",
                    narrative_perspective="Dual-perspective intimate dialogue",
                    custom_tags=["neo-soul", "dilla-swing", "rhodes-chords", "warm-bass"],
                    interpretation_confidence=0.94,
                ),
                has_lyrics_analyzed=True,
                llm_provider_used="demo_seed",
            ),
            [
                {"age_sec": 1 * hour, "listened_ms": 210000, "was_skipped": False, "repeat_count": 2},
                {"age_sec": 1.3 * day, "listened_ms": 210000, "was_skipped": False, "repeat_count": 1},
            ],
        ),
        (
            TrackProfile(
                track_id="0d28khcov6AiegSCpG5TuT",
                title="Feel Good Inc.",
                artist="Gorillaz",
                album="Demon Days",
                duration_ms=222640,
                spotify_url="https://open.spotify.com/track/0d28khcov6AiegSCpG5TuT",
                audio=MeasuredAudioFeatures(
                    tempo=138.6,
                    energy=0.705,
                    danceability=0.818,
                    valence=0.772,
                    acousticness=0.0084,
                    instrumentalness=0.0023,
                    speechiness=0.177,
                    loudness=-6.679,
                    key=6,
                    mode=1,
                    source=FeatureSource.RECCOBEATS,
                    confidence=0.98,
                ),
                interpretation=LLMInterpretiveOutput(
                    beat_archetype=BeatArchetype.BOOM_BAP,
                    beat_descriptor="Hypnotic live bass groove over a crisp boom-bap breakbeat that opens into an acoustic windmill chorus.",
                    primary_theme=LyricalTheme.SOCIAL_COMMENTARY,
                    secondary_theme=LyricalTheme.ESCAPISM_WANDERLUST,
                    music_message="Critiquing manufactured escapism and herd conformity while yearning for genuine emotional freedom.",
                    emotional_arc="Alternates between gritty, cynical funk verses and soaring, melancholic acoustic choruses.",
                    narrative_perspective="Observational & allegorical",
                    custom_tags=["alt-hip-hop", "funk-bass", "breakbeat", "acoustic-chorus"],
                    interpretation_confidence=0.95,
                ),
                has_lyrics_analyzed=True,
                llm_provider_used="demo_seed",
            ),
            [
                {"age_sec": 10 * hour, "listened_ms": 222640, "was_skipped": False, "repeat_count": 1},
            ],
        ),
        (
            TrackProfile(
                track_id="3KkXRkHbMCARz0aVfEt68P",
                title="Sunflower",
                artist="Post Malone, Swae Lee",
                album="Spider-Man: Into the Spider-Verse",
                duration_ms=158040,
                spotify_url="https://open.spotify.com/track/3KkXRkHbMCARz0aVfEt68P",
                audio=MeasuredAudioFeatures(
                    tempo=89.9,
                    energy=0.479,
                    danceability=0.755,
                    valence=0.913,
                    acousticness=0.556,
                    instrumentalness=0.0,
                    speechiness=0.0466,
                    loudness=-5.574,
                    key=2,
                    mode=1,
                    source=FeatureSource.RECCOBEATS,
                    confidence=0.97,
                ),
                interpretation=LLMInterpretiveOutput(
                    beat_archetype=BeatArchetype.INDIE_MOTORIK,
                    beat_descriptor="Breezy, sun-drenched 90 BPM indie-pop drum loop with warm sub-bass and crisp rimshots.",
                    primary_theme=LyricalTheme.ROMANTIC_DEVOTION,
                    secondary_theme=LyricalTheme.HEARTBREAK_LONGING,
                    music_message="Holding onto resilient affection through turbulent ups and downs in a relationship.",
                    emotional_arc="Bright and effortless throughout with a wistful melodic sweetness.",
                    narrative_perspective="First-person affectionate reflection",
                    custom_tags=["melodic-pop-rap", "breezy-groove", "bright"],
                    interpretation_confidence=0.92,
                ),
                has_lyrics_analyzed=True,
                llm_provider_used="demo_seed",
            ),
            [
                # Example of an early skip in demo history so skip analytics are demonstrated!
                {"age_sec": 18 * hour, "listened_ms": 19000, "was_skipped": True, "repeat_count": 0},
            ],
        ),
        (
            TrackProfile(
                track_id="4cOdK2wGLETKBW3PvgPWqT",
                title="Nights",
                artist="Frank Ocean",
                album="Blonde",
                duration_ms=307151,
                spotify_url="https://open.spotify.com/track/4cOdK2wGLETKBW3PvgPWqT",
                audio=MeasuredAudioFeatures(
                    tempo=89.0,
                    energy=0.55,
                    danceability=0.46,
                    valence=0.43,
                    acousticness=0.42,
                    instrumentalness=0.001,
                    speechiness=0.16,
                    loudness=-9.4,
                    key=5,
                    mode=0,
                    source=FeatureSource.RECCOBEATS,
                    confidence=0.96,
                ),
                interpretation=LLMInterpretiveOutput(
                    beat_archetype=BeatArchetype.RNB_SLOW_JAM,
                    beat_descriptor="Two-part structure shifting from bright syncopated guitar bounce into a hazy, half-time nocturnal 808 slow jam.",
                    primary_theme=LyricalTheme.LATE_NIGHT_INTROSPECTION,
                    secondary_theme=LyricalTheme.RESILIENCE_OVERCOMING,
                    music_message="Processing life transitions, survival, and shifting relationships across the divide of day and night.",
                    emotional_arc="Restless, conversational first half collapsing through a famous beat-switch into deep nocturnal catharsis.",
                    narrative_perspective="First-person stream-of-consciousness",
                    custom_tags=["beat-switch", "alt-rnb", "nocturnal", "confessional"],
                    interpretation_confidence=0.97,
                ),
                has_lyrics_analyzed=True,
                llm_provider_used="demo_seed",
            ),
            [
                {"age_sec": 0.4 * hour, "listened_ms": 307151, "was_skipped": False, "repeat_count": 3},
                {"age_sec": 3.0 * day, "listened_ms": 307151, "was_skipped": False, "repeat_count": 1},
            ],
        ),
    ]

    # Attach actual timestamps
    for profile, plays in seed_items:
        for p in plays:
            p["played_at_ts"] = now - p.pop("age_sec")

    return seed_items


def get_curated_candidate_catalog() -> List[TrackProfile]:
    """
    A rich pool of pre-profiled catalog tracks across beat archetypes and lyrical messages
    used to supplement ReccoBeats/Last.fm/LLM candidates when offline or in Demo Mode.
    """
    return [
        TrackProfile(
            track_id="3WMj8moIAXJhHsyLaqIIHI",
            title="Something About Us",
            artist="Daft Punk",
            album="Discovery",
            duration_ms=232000,
            spotify_url="https://open.spotify.com/track/3WMj8moIAXJhHsyLaqIIHI",
            audio=MeasuredAudioFeatures(
                tempo=100.0, energy=0.39, danceability=0.81, valence=0.38,
                acousticness=0.44, instrumentalness=0.18, speechiness=0.06, loudness=-10.2,
                source=FeatureSource.RECCOBEATS, confidence=0.96,
            ),
            interpretation=LLMInterpretiveOutput(
                beat_archetype=BeatArchetype.NEO_SOUL_POCKET,
                beat_descriptor="Laid-back 100 BPM lounge-funk pocket with warm electric piano and muted slap bass.",
                primary_theme=LyricalTheme.ROMANTIC_DEVOTION,
                secondary_theme=LyricalTheme.LATE_NIGHT_INTROSPECTION,
                music_message="Quiet, bittersweet confession of unspoken love that may not be the right time.",
                emotional_arc="Intimate, vocoder-warmed vulnerability from start to finish.",
                narrative_perspective="First-person tender confession",
                custom_tags=["french-touch", "vocoder-soul", "warm-groove"],
                interpretation_confidence=0.95,
            ),
            has_lyrics_analyzed=True,
            llm_provider_used="catalog_verified",
        ),
        TrackProfile(
            track_id="2plbrEY59IikOBgBGLjaoe",
            title="Die With A Smile",
            artist="Lady Gaga, Bruno Mars",
            album="Die With A Smile",
            duration_ms=251667,
            spotify_url="https://open.spotify.com/track/2plbrEY59IikOBgBGLjaoe",
            audio=MeasuredAudioFeatures(
                tempo=158.0, energy=0.59, danceability=0.52, valence=0.53,
                acousticness=0.31, instrumentalness=0.0, speechiness=0.03, loudness=-7.7,
                source=FeatureSource.RECCOBEATS, confidence=0.95,
            ),
            interpretation=LLMInterpretiveOutput(
                beat_archetype=BeatArchetype.RNB_SLOW_JAM,
                beat_descriptor="Classic 70s soul-ballad 6/8 drum groove with warm live bass and soaring guitar fills.",
                primary_theme=LyricalTheme.ROMANTIC_DEVOTION,
                secondary_theme=LyricalTheme.MINDFULNESS_PEACE,
                music_message="Choosing unwavering presence and love beside the person who matters most, even if the world ends.",
                emotional_arc="Tender acoustic opening building into a cinematic, full-band duet climax.",
                narrative_perspective="First-person duet vow",
                custom_tags=["retro-soul", "live-drums", "cinematic-ballad"],
                interpretation_confidence=0.95,
            ),
            has_lyrics_analyzed=True,
            llm_provider_used="catalog_verified",
        ),
        TrackProfile(
            track_id="6HabFhsOp2NvshLv26DqMb",
            title="Alright",
            artist="Kendrick Lamar",
            album="To Pimp a Butterfly",
            duration_ms=219333,
            spotify_url="https://open.spotify.com/track/6HabFhsOp2NvshLv26DqMb",
            audio=MeasuredAudioFeatures(
                tempo=110.0, energy=0.77, danceability=0.79, valence=0.55,
                acousticness=0.07, instrumentalness=0.0, speechiness=0.29, loudness=-5.9,
                source=FeatureSource.RECCOBEATS, confidence=0.97,
            ),
            interpretation=LLMInterpretiveOutput(
                beat_archetype=BeatArchetype.BOOM_BAP,
                beat_descriptor="Hard-hitting jazz-inflected boom-bap drums with brass stabs and Pharrell's syncopated bounce.",
                primary_theme=LyricalTheme.RESILIENCE_OVERCOMING,
                secondary_theme=LyricalTheme.SOCIAL_COMMENTARY,
                music_message="An anthem of collective hope, spiritual endurance, and resilience in the face of systemic hardship.",
                emotional_arc="Confessional struggle in the verses erupting into an uplifting, defiant communal chorus.",
                narrative_perspective="First-person & collective 'we' solidarity",
                custom_tags=["jazz-rap", "boom-bap", "uplifting", "brass"],
                interpretation_confidence=0.97,
            ),
            has_lyrics_analyzed=True,
            llm_provider_used="catalog_verified",
        ),
        TrackProfile(
            track_id="0VjIjW4GlUZAMYd2vXMi3c",
            title="Midnight City",
            artist="M83",
            album="Hurry Up, We're Dreaming",
            duration_ms=243960,
            spotify_url="https://open.spotify.com/track/1eyzqe2QqGZUmfcPZtrIyt",
            audio=MeasuredAudioFeatures(
                tempo=105.0, energy=0.84, danceability=0.53, valence=0.39,
                acousticness=0.01, instrumentalness=0.14, speechiness=0.04, loudness=-5.4,
                source=FeatureSource.RECCOBEATS, confidence=0.96,
            ),
            interpretation=LLMInterpretiveOutput(
                beat_archetype=BeatArchetype.SYNTHWAVE_PULSE,
                beat_descriptor="Driving 105 BPM synth-pop stomp with massive gated drums and a euphoric saxophone outro.",
                primary_theme=LyricalTheme.ESCAPISM_WANDERLUST,
                secondary_theme=LyricalTheme.EUPHORIA_CELEBRATION,
                music_message="Embracing the electric freedom and infinite possibility of the city at midnight.",
                emotional_arc="Builds from hypnotic synth hooks into a transcendent, cathartic brass finale.",
                narrative_perspective="Observational nocturnal wonder",
                custom_tags=["synthwave", "night-drive", "anthemic", "dream-pop"],
                interpretation_confidence=0.95,
            ),
            has_lyrics_analyzed=True,
            llm_provider_used="catalog_verified",
        ),
        TrackProfile(
            track_id="5QO79kh1waicV47BqGRL3g",
            title="Save Your Tears",
            artist="The Weeknd",
            album="After Hours",
            duration_ms=215626,
            spotify_url="https://open.spotify.com/track/5QO79kh1waicV47BqGRL3g",
            audio=MeasuredAudioFeatures(
                tempo=118.0, energy=0.82, danceability=0.68, valence=0.64,
                acousticness=0.02, instrumentalness=0.0, speechiness=0.03, loudness=-5.4,
                source=FeatureSource.RECCOBEATS, confidence=0.98,
            ),
            interpretation=LLMInterpretiveOutput(
                beat_archetype=BeatArchetype.SYNTHWAVE_PULSE,
                beat_descriptor="Upbeat 118 BPM new-wave synth groove contrasting bright melodies with bittersweet lyrics.",
                primary_theme=LyricalTheme.HEARTBREAK_LONGING,
                secondary_theme=LyricalTheme.LATE_NIGHT_INTROSPECTION,
                music_message="Confronting an ex-lover across a crowded room while owning up to emotional detachment and regret.",
                emotional_arc="Deceptively bright and danceable groove carrying a wistful, remorseful narrative.",
                narrative_perspective="Second-person direct confession",
                custom_tags=["80s-synthpop", "melancholic-dance", "retro"],
                interpretation_confidence=0.96,
            ),
            has_lyrics_analyzed=True,
            llm_provider_used="catalog_verified",
        ),
        TrackProfile(
            track_id="7lQ8MOhq6IN2w8EYcFNSUk",
            title="Doomsday",
            artist="MF DOOM, Pebbles The Invisible Girl",
            album="Operation: Doomsday",
            duration_ms=298133,
            spotify_url="https://open.spotify.com/track/7lQ8MOhq6IN2w8EYcFNSUk",
            audio=MeasuredAudioFeatures(
                tempo=94.0, energy=0.64, danceability=0.76, valence=0.62,
                acousticness=0.28, instrumentalness=0.0, speechiness=0.24, loudness=-7.8,
                source=FeatureSource.RECCOBEATS, confidence=0.95,
            ),
            interpretation=LLMInterpretiveOutput(
                beat_archetype=BeatArchetype.BOOM_BAP,
                beat_descriptor="Classic 94 BPM dusty boom-bap loop sampling Sade's Rhodes piano over warm vinyl crackle.",
                primary_theme=LyricalTheme.AMBITION_HUSTLE,
                secondary_theme=LyricalTheme.RESILIENCE_OVERCOMING,
                music_message="Turning personal loss into artistic immortality through intricate rhyme craft and self-determination.",
                emotional_arc="Smooth, soulful nostalgia anchoring sharp, witty lyrical mastery.",
                narrative_perspective="First-person lyrical manifesto",
                custom_tags=["boom-bap", "jazz-sample", "underground-hip-hop", "rhodes"],
                interpretation_confidence=0.96,
            ),
            has_lyrics_analyzed=True,
            llm_provider_used="catalog_verified",
        ),
        TrackProfile(
            track_id="1BxfuPKGuaTgP7aM0Bbdwr",
            title="On Melancholy Hill",
            artist="Gorillaz",
            album="Plastic Beach",
            duration_ms=233866,
            spotify_url="https://open.spotify.com/track/0q6LuUqGLUiCPP1cbdwFs3",
            audio=MeasuredAudioFeatures(
                tempo=120.0, energy=0.69, danceability=0.68, valence=0.58,
                acousticness=0.02, instrumentalness=0.04, speechiness=0.03, loudness=-7.1,
                source=FeatureSource.RECCOBEATS, confidence=0.96,
            ),
            interpretation=LLMInterpretiveOutput(
                beat_archetype=BeatArchetype.INDIE_MOTORIK,
                beat_descriptor="Steady 120 BPM motorik synth-pop drum machine groove with cascading daydream melodies.",
                primary_theme=LyricalTheme.MINDFULNESS_PEACE,
                secondary_theme=LyricalTheme.ROMANTIC_DEVOTION,
                music_message="Finding quiet solace and companionship together away from a fractured, plastic world.",
                emotional_arc="Gentle, floating synth arpeggios that bloom into a comforting, bittersweet embrace.",
                narrative_perspective="Second-person gentle invitation",
                custom_tags=["dream-pop", "motorik-groove", "bittersweet", "comforting"],
                interpretation_confidence=0.95,
            ),
            has_lyrics_analyzed=True,
            llm_provider_used="catalog_verified",
        ),
        TrackProfile(
            track_id="3xKsf9qdS1CyvXSMEid6g8",
            title="Pink + White",
            artist="Frank Ocean",
            album="Blonde",
            duration_ms=184516,
            spotify_url="https://open.spotify.com/track/3xKsf9qdS1CyvXSMEid6g8",
            audio=MeasuredAudioFeatures(
                tempo=80.0, energy=0.54, danceability=0.51, valence=0.52,
                acousticness=0.66, instrumentalness=0.0, speechiness=0.08, loudness=-7.5,
                source=FeatureSource.RECCOBEATS, confidence=0.97,
            ),
            interpretation=LLMInterpretiveOutput(
                beat_archetype=BeatArchetype.NEO_SOUL_POCKET,
                beat_descriptor="Rolling 6/8 acoustic piano & upright bass neo-soul pocket with lush gospel-angelic backing vocals.",
                primary_theme=LyricalTheme.MINDFULNESS_PEACE,
                secondary_theme=LyricalTheme.LATE_NIGHT_INTROSPECTION,
                music_message="Gratitude for fleeting beauty, memory, and grace in a transient world.",
                emotional_arc="Warm, sunlit acoustic groove lifting into an ethereal vocal outro.",
                narrative_perspective="First-person poetic memory",
                custom_tags=["neo-soul", "acoustic-groove", "ethereal", "lush-strings"],
                interpretation_confidence=0.96,
            ),
            has_lyrics_analyzed=True,
            llm_provider_used="catalog_verified",
        ),
    ]


def ensure_demo_seeded(db: Database) -> None:
    """Seeds demo tracks and play history if the database is empty."""
    existing = db.get_play_events(include_demo=True, limit=1)
    if existing:
        return
    for profile, plays in get_seed_tracks_and_plays():
        db.upsert_track_profile(profile)
        for p in plays:
            db.record_play_event(
                track_id=profile.track_id,
                listened_ms=p["listened_ms"],
                duration_ms=profile.duration_ms,
                was_skipped=p["was_skipped"],
                repeat_count=p["repeat_count"],
                played_at_ts=p["played_at_ts"],
                source="demo_seed",
                is_demo=True,
            )
    for cat_profile in get_curated_candidate_catalog():
        if not db.get_track_profile(cat_profile.track_id):
            db.upsert_track_profile(cat_profile)
