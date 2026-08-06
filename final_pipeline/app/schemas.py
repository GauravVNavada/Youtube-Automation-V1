from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class ImageCue:
    keyword: str
    timestamp_hint: str
    mood: str = "neutral"
    role: str = "supporting_visual"
    subject_lock: bool = False
    required_subjects: list[str] = field(default_factory=list)
    aliases: list[str] = field(default_factory=list)
    allowed_fallback_level: str = "generic_scene"


@dataclass
class TimedVisualCue:
    start_ms: int
    end_ms: int
    text: str
    search_query: str
    subject_lock: bool = False
    required_subjects: list[str] = field(default_factory=list)
    aliases: list[str] = field(default_factory=list)
    role: str = "timed_segment"
    mood: str = "neutral"
    allowed_fallback_level: str = "generic_scene"
    source: str = "caption_timing"


@dataclass
class SfxCue:
    trigger_word: str
    sfx_type: str
    timestamp_hint: str = "during word"


@dataclass
class ScriptOutput:
    title: str
    narration: str
    hook_line: str
    word_count: int
    estimated_duration: int
    description: str
    hashtags: list[str]
    image_cues: list[ImageCue]
    sfx_cues: list[SfxCue]
    emphasis_words: list[str] = field(default_factory=list)
    provider: str = "unknown"


@dataclass
class GenreConfig:
    genre_id: str
    display_name: str
    word_count_min: int
    word_count_max: int
    tone: str
    layout: str
    caption_preset: str
    voice_rate: float
    music_mood: str
    hook_patterns: list[str] = field(default_factory=list)
    banned_phrases: list[str] = field(default_factory=list)
    visual_style: dict[str, Any] = field(default_factory=dict)
    topic_rules: list[dict[str, Any]] = field(default_factory=list)
    script_profile: dict[str, Any] = field(default_factory=dict)


@dataclass
class AssetBundle:
    image_paths: list[str]
    sfx_paths: list[str]
    music_path: Optional[str]
    sources: list[str]
    sfx_asset_ids: list[str] = field(default_factory=list)
    sfx_asset_names: list[str] = field(default_factory=list)
    video_paths: list[str] = field(default_factory=list)
    media_paths: list[str] = field(default_factory=list)
    media_types: list[str] = field(default_factory=list)
    stock_video_search_terms: list[str] = field(default_factory=list)
    subject_lock_issues: list[str] = field(default_factory=list)
    asset_selection_trace: list[dict[str, Any]] = field(default_factory=list)
    sfx_selection_trace: list[dict[str, Any]] = field(default_factory=list)
    asset_trace_path: str = ""
    media_start_ms: list[int] = field(default_factory=list)
    media_end_ms: list[int] = field(default_factory=list)
    media_durations_ms: list[int] = field(default_factory=list)
    timed_visual_cues: list[TimedVisualCue] = field(default_factory=list)
    timed_visual_cues_path: str = ""


@dataclass
class WordTimestamp:
    word: str
    start_ms: int
    end_ms: int


@dataclass
class AudioBundle:
    narration_path: str
    final_audio_path: str
    duration_ms: int
    word_timestamps: list[WordTimestamp]
    provider: str
    mean_volume_db: Optional[float] = None
    max_volume_db: Optional[float] = None
    longest_silence_seconds: Optional[float] = None
    alignment_source: str = "unknown"


@dataclass
class MusicBundle:
    input_audio_path: str
    final_audio_path: str
    music_path: Optional[str]
    duration_ms: int
    music_volume: float
    mixed: bool
    status: str
    skipped_reason: str = ""
    sfx_paths: list[str] = field(default_factory=list)
    sfx_asset_ids: list[str] = field(default_factory=list)
    sfx_asset_names: list[str] = field(default_factory=list)
    sfx_timings_ms: list[int] = field(default_factory=list)
    sfx_mixed: bool = False
    mean_volume_db: Optional[float] = None
    max_volume_db: Optional[float] = None
    longest_silence_seconds: Optional[float] = None


@dataclass
class CaptionBundle:
    srt_path: str
    ass_path: str
    phrase_count: int
    word_count: int


@dataclass
class RenderResult:
    video_path: str
    width: int
    height: int
    duration_seconds: float
    renderer: str = "ffmpeg"


@dataclass
class ValidationResult:
    passed: bool
    issues: list[str] = field(default_factory=list)
    repair_notes: list[str] = field(default_factory=list)


@dataclass
class PipelineContext:
    topic: str
    genre_id: str
    duration: int
    run_dir: str
    user_notes: str = ""


@dataclass
class NicheProfile:
    genre_id: str
    display_name: str
    hook_templates: list[str] = field(default_factory=list)
    tone_rules: list[str] = field(default_factory=list)
    title_words: list[str] = field(default_factory=list)
    thumbnail_text_rules: list[str] = field(default_factory=list)
    visual_keywords: list[str] = field(default_factory=list)
    negative_visual_keywords: list[str] = field(default_factory=list)
    hashtag_hints: list[str] = field(default_factory=list)
    source: str = "default"


@dataclass
class TopicCandidate:
    topic: str
    angle: str
    hook: str
    score: float
    source: str
    keywords: list[str] = field(default_factory=list)


@dataclass
class TopicDiscoveryOutput:
    original_topic: str
    selected_topic: str
    selected_angle: str
    candidates: list[TopicCandidate]
    niche_profile: NicheProfile
    source_errors: list[str] = field(default_factory=list)
    grounding_plan: dict[str, Any] = field(default_factory=dict)


@dataclass
class ResearchSource:
    title: str
    url: str
    snippet: str
    source: str


@dataclass
class ResearchOutput:
    topic: str
    brief: str
    facts: list[str]
    source_snippets: list[ResearchSource]
    source_errors: list[str] = field(default_factory=list)


@dataclass
class GrowthContext:
    topic_discovery: TopicDiscoveryOutput | None = None
    research: ResearchOutput | None = None
    notes: str = ""


@dataclass
class VisualStylePlan:
    source_policy: str = "stock_video_first"
    visual_keywords: list[str] = field(default_factory=list)
    negative_visual_keywords: list[str] = field(default_factory=list)
    protected_terms: list[str] = field(default_factory=list)
    style_notes: list[str] = field(default_factory=list)


@dataclass
class ThumbnailOutput:
    shorts_cover_path: str
    youtube_thumbnail_path: str
    source_image_path: str
    text_lines: list[str]
