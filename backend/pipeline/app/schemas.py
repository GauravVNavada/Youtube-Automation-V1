from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ImageCue:
    keyword: str
    timestamp_hint: str
    mood: str = "neutral"


@dataclass
class SfxCue:
    trigger_word: str
    sfx_type: str
    timestamp_hint: str = "during word"


@dataclass
class ScriptSection:
    name: str
    purpose: str
    narration: str
    word_count: int = 0


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
    script_sections: list[ScriptSection] = field(default_factory=list)
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


@dataclass
class AssetBundle:
    image_paths: list[str]
    sfx_paths: list[str]
    music_path: Optional[str]
    sources: list[str]
    video_paths: list[str] = field(default_factory=list)
    video_sources: list[str] = field(default_factory=list)
    visual_style: str = "natural"
    asset_strategy: str = "hybrid_video"


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
    hashtag_hints: list[str] = field(default_factory=list)
    source: str = "fallback"


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
    grounding_plan: dict = field(default_factory=dict)
    source_errors: list[str] = field(default_factory=list)


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
    selected_topic: str
    selected_angle: str
    candidate_topics: list[dict]
    research_brief: str
    source_snippets: list[dict]
    niche_profile: dict
    thumbnail_hints: list[str]
    title_hints: list[str]


@dataclass
class VisualStylePlan:
    original_topic: str
    sanitized_topic: str
    mode: str = "stock_video"
    render_style: str = "natural"
    asset_strategy: str = "hybrid_video"
    search_style_terms: list[str] = field(default_factory=list)
    blocked_terms: list[str] = field(default_factory=list)
    replacements: dict[str, str] = field(default_factory=dict)
    prompt_guidance: list[str] = field(default_factory=list)
    source_policy: str = "stock_video_first"


@dataclass
class ThumbnailOutput:
    shorts_cover_path: str
    youtube_thumbnail_path: str
    source_image_path: str
    text_lines: list[str]
    provider: str = "pillow"
