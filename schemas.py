"""
Controlled macro vocabularies (for 46-D vector math) + Unconstrained Song-Specific
Lyrical Theme Headlines & Music Message schemas (`schemas.py`).
"""
from __future__ import annotations

import math
from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field, field_validator


class BeatArchetype(str, Enum):
    BOOM_BAP = "boom_bap"
    TRAP_808 = "trap_808"
    FOUR_ON_THE_FLOOR = "four_on_the_floor"
    SYNTHWAVE_PULSE = "synthwave_pulse"
    BREAKBEAT_DNB = "breakbeat_dnb"
    NEO_SOUL_POCKET = "neo_soul_pocket"
    INDIE_MOTORIK = "indie_motorik"
    ACOUSTIC_FINGERSTYLE = "acoustic_fingerstyle"
    ALT_ROCK_DRIVE = "alt_rock_drive"
    AMBIENT_DRONE = "ambient_drone"
    AFROBEATS_CLAV = "afrobeats_clav"
    RNB_SLOW_JAM = "rnb_slow_jam"
    LATIN_REGGAETON_DEMBOW = "latin_reggaeton_dembow"
    DANCE_POP_SYNCOPATION = "dance_pop_syncopation"
    OTHER = "other"


BEAT_ARCHETYPE_LABELS = {
    BeatArchetype.BOOM_BAP: "Boom-Bap / Swung Hip-Hop",
    BeatArchetype.TRAP_808: "Half-Time Trap / 808 Bounce",
    BeatArchetype.FOUR_ON_THE_FLOOR: "Four-on-the-Floor House / Club",
    BeatArchetype.SYNTHWAVE_PULSE: "Synthwave / Nocturnal Electronic Pulse",
    BeatArchetype.BREAKBEAT_DNB: "Breakbeat / Drum & Bass",
    BeatArchetype.NEO_SOUL_POCKET: "Neo-Soul / Laid-Back Pocket",
    BeatArchetype.INDIE_MOTORIK: "Indie / Mid-Tempo Alt Groove",
    BeatArchetype.ACOUSTIC_FINGERSTYLE: "Acoustic / Organic Unplugged",
    BeatArchetype.ALT_ROCK_DRIVE: "Driving Alt-Rock / Live Band",
    BeatArchetype.AMBIENT_DRONE: "Ambient / Beatless Textural",
    BeatArchetype.AFROBEATS_CLAV: "Afrobeats / Syncopated Clave",
    BeatArchetype.RNB_SLOW_JAM: "Late-Night R&B / Dark Pop Slow Jam",
    BeatArchetype.LATIN_REGGAETON_DEMBOW: "Tropical / Reggaeton / Balkan Dance",
    BeatArchetype.DANCE_POP_SYNCOPATION: "Syncopated Dance-Pop Groove",
    BeatArchetype.OTHER: "Eclectic / Custom Groove",
}


class LyricalTheme(str, Enum):
    AMBITION_HUSTLE = "ambition_hustle"
    LATE_NIGHT_INTROSPECTION = "late_night_introspection"
    HEARTBREAK_LONGING = "heartbreak_longing"
    EUPHORIA_CELEBRATION = "euphoria_celebration"
    RESILIENCE_OVERCOMING = "resilience_overcoming"
    SOCIAL_COMMENTARY = "social_commentary"
    ESCAPISM_WANDERLUST = "escapism_wanderlust"
    ROMANTIC_DEVOTION = "romantic_devotion"
    MELANCHOLY_GRIEF = "melancholy_grief"
    REBELLION_DEFIANCE = "rebellion_defiance"
    MINDFULNESS_PEACE = "mindfulness_peace"
    SACRIFICE_MARTYRDOM = "sacrifice_martyrdom"
    TOXIC_DESIRE_OBSESSION = "toxic_desire_obsession"
    FAME_ALIENATION = "fame_alienation"
    NOSTALGIA_YOUTH = "nostalgia_youth"
    SPIRITUAL_REDEMPTION = "spiritual_redemption"
    BETRAYAL_DISTRUST = "betrayal_distrust"
    CONFIDENCE_SWAGGER = "confidence_swagger"
    EXISTENTIAL_DOUBT = "existential_doubt"
    PASSION_SENSUALITY = "passion_sensuality"
    LOYALTY_BROTHERHOOD = "loyalty_brotherhood"
    INSTRUMENTAL_NO_LYRICS = "instrumental_no_lyrics"
    OTHER = "other"


LYRICAL_THEME_LABELS = {
    LyricalTheme.AMBITION_HUSTLE: "Ambition, Relentless Grind & Self-Made Ascent",
    LyricalTheme.LATE_NIGHT_INTROSPECTION: "Nocturnal Solitude & Self-Examination",
    LyricalTheme.HEARTBREAK_LONGING: "Heartbreak, Unspoken Regret & Lingering Echoes",
    LyricalTheme.EUPHORIA_CELEBRATION: "Euphoric Liberation & Ecstatic Release",
    LyricalTheme.RESILIENCE_OVERCOMING: "Resilience, Survival & Weathering the Storm",
    LyricalTheme.SOCIAL_COMMENTARY: "Systemic Critique & Cultural Truth-Telling",
    LyricalTheme.ESCAPISM_WANDERLUST: "Midnight Escapism, Neon Highways & Flight",
    LyricalTheme.ROMANTIC_DEVOTION: "Unconditional Devotion & Ride-or-Die Romance",
    LyricalTheme.MELANCHOLY_GRIEF: "Vulnerability, Grief & Emotional Catharsis",
    LyricalTheme.REBELLION_DEFIANCE: "Defiance, Autonomy & Breaking the Mold",
    LyricalTheme.MINDFULNESS_PEACE: "Stillness, Gratitude & Inner Sanctuary",
    LyricalTheme.SACRIFICE_MARTYRDOM: "Heroic Sacrifice, Duty & Carrying Heavy Burdens",
    LyricalTheme.TOXIC_DESIRE_OBSESSION: "Intoxicating Obsession, Temptation & Dark Desire",
    LyricalTheme.FAME_ALIENATION: "The Hollowness of Fame, Paranoia & Isolation",
    LyricalTheme.NOSTALGIA_YOUTH: "Bittersweet Nostalgia, Memory & Fading Youth",
    LyricalTheme.SPIRITUAL_REDEMPTION: "Moral Reckoning, Faith & Seeking Forgiveness",
    LyricalTheme.BETRAYAL_DISTRUST: "Betrayal, Guarded Hearts & Broken Trust",
    LyricalTheme.CONFIDENCE_SWAGGER: "Unapologetic Confidence, Charisma & Dominance",
    LyricalTheme.EXISTENTIAL_DOUBT: "Existential Searching, Mortality & Meaning",
    LyricalTheme.PASSION_SENSUALITY: "Magnetic Attraction, Sensuality & Chemistry",
    LyricalTheme.LOYALTY_BROTHERHOOD: "Devotion to the Circle, Loyalty & Solidarity",
    LyricalTheme.INSTRUMENTAL_NO_LYRICS: "Purely Instrumental / Sonic Storytelling",
    LyricalTheme.OTHER: "Nuanced Multi-Layered Narrative",
}


class FeatureSource(str, Enum):
    RECCOBEATS = "reccobeats"
    LOCAL_LIBROSA = "local_librosa"
    HEURISTIC_FALLBACK = "heuristic_fallback"


class MeasuredAudioFeatures(BaseModel):
    tempo: float = Field(default=120.0, ge=30.0, le=260.0)
    energy: float = Field(default=0.5, ge=0.0, le=1.0)
    danceability: float = Field(default=0.5, ge=0.0, le=1.0)
    valence: float = Field(default=0.5, ge=0.0, le=1.0)
    acousticness: float = Field(default=0.2, ge=0.0, le=1.0)
    instrumentalness: float = Field(default=0.05, ge=0.0, le=1.0)
    speechiness: float = Field(default=0.08, ge=0.0, le=1.0)
    loudness: float = Field(default=-8.0, ge=-60.0, le=5.0)
    key: int = Field(default=0, ge=-1, le=11)
    mode: int = Field(default=1, ge=0, le=1)
    source: FeatureSource = Field(default=FeatureSource.RECCOBEATS)
    confidence: float = Field(default=0.95, ge=0.0, le=1.0)


class LLMInterpretiveOutput(BaseModel):
    """
    Combines unconstrained, song-specific lyrical interpretation (`specific_theme_headline`,
    `music_message`, `key_lyric_motif`) with macro taxonomy tags (`beat_archetype`, `primary_theme`)
    used for vector similarity math.
    """
    beat_archetype: BeatArchetype = Field(
        default=BeatArchetype.OTHER,
        description="Macro beat archetype for vector similarity."
    )
    beat_descriptor: str = Field(
        default="Steady rhythmic groove",
        max_length=220,
        description="Specific description of drum pattern, pocket, and bass texture."
    )
    specific_theme_headline: str = Field(
        default="",
        max_length=140,
        description="Unconstrained, song-specific 4-9 word thematic headline tailored to this exact song's lyrics."
    )
    primary_theme: LyricalTheme = Field(
        default=LyricalTheme.OTHER,
        description="Macro lyrical category for taste chart aggregation."
    )
    secondary_theme: Optional[LyricalTheme] = Field(
        default=None,
        description="Optional secondary macro lyrical category."
    )
    music_message: str = Field(
        default="Expressive musical narrative",
        max_length=360,
        description="Specific 2-sentence interpretation of what the song is actually saying and its emotional stakes."
    )
    key_lyric_motif: str = Field(
        default="",
        max_length=160,
        description="Standout lyrical hook, metaphor, or recurring motif from the song."
    )
    emotional_arc: str = Field(
        default="Steady emotional tone",
        max_length=180,
        description="How the mood evolves from intro to outro."
    )
    narrative_perspective: str = Field(
        default="First-person reflection",
        max_length=100,
        description="Perspective and vocal tone."
    )
    custom_tags: List[str] = Field(
        default_factory=list,
        max_length=6,
        description="Up to 5 short lowercase micro-tags for niche subgenres or motifs."
    )
    interpretation_confidence: float = Field(
        default=0.85,
        ge=0.0,
        le=1.0,
    )

    @field_validator("custom_tags")
    @classmethod
    def normalize_tags(cls, v: List[str]) -> List[str]:
        cleaned = []
        for tag in v[:5]:
            t = str(tag).strip().lower().replace("_", "-")
            if t and t not in cleaned:
                cleaned.append(t[:32])
        return cleaned


class TrackProfile(BaseModel):
    track_id: str
    title: str
    artist: str
    album: str = ""
    album_art_url: str = ""
    duration_ms: int = 200000
    spotify_url: str = ""
    audio: MeasuredAudioFeatures
    interpretation: LLMInterpretiveOutput
    has_lyrics_analyzed: bool = False
    llm_provider_used: str = "heuristic"
    embedding_vector: List[float] = Field(default_factory=list)


ORDERED_BEAT_ARCHETYPES: List[BeatArchetype] = list(BeatArchetype)
ORDERED_LYRICAL_THEMES: List[LyricalTheme] = list(LyricalTheme)
VECTOR_DIM = 8 + len(ORDERED_BEAT_ARCHETYPES) + len(ORDERED_LYRICAL_THEMES)


def build_track_vector(
    audio: MeasuredAudioFeatures,
    interp: LLMInterpretiveOutput,
) -> List[float]:
    tempo_norm = max(0.0, min(1.0, (audio.tempo - 50.0) / 150.0))
    loudness_norm = max(0.0, min(1.0, (audio.loudness + 40.0) / 40.0))
    continuous = [
        tempo_norm,
        audio.energy,
        audio.danceability,
        audio.valence,
        audio.acousticness,
        audio.instrumentalness,
        audio.speechiness,
        loudness_norm,
    ]

    beat_vec = [
        1.25 if b == interp.beat_archetype else 0.0
        for b in ORDERED_BEAT_ARCHETYPES
    ]

    theme_vec = []
    for t in ORDERED_LYRICAL_THEMES:
        if t == interp.primary_theme:
            theme_vec.append(1.25)
        elif interp.secondary_theme and t == interp.secondary_theme:
            theme_vec.append(0.65)
        else:
            theme_vec.append(0.0)

    raw = continuous + beat_vec + theme_vec
    norm = math.sqrt(sum(x * x for x in raw))
    if norm > 1e-9:
        return [round(x / norm, 6) for x in raw]
    return raw


def cosine_similarity(vec_a: List[float], vec_b: List[float]) -> float:
    if not vec_a or not vec_b or len(vec_a) != len(vec_b):
        return 0.0
    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = math.sqrt(sum(a * a for a in vec_a))
    norm_b = math.sqrt(sum(b * b for b in vec_b))
    if norm_a < 1e-9 or norm_b < 1e-9:
        return 0.0
    return max(-1.0, min(1.0, dot / (norm_a * norm_b)))
