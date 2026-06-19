from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def uuid_str() -> str:
    return str(uuid.uuid4())


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    display_name: Mapped[str] = mapped_column(String(120), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    chats: Mapped[list[Chat]] = relationship(back_populates="user", cascade="all, delete-orphan")
    api_keys: Mapped[list[UserApiKey]] = relationship(back_populates="user", cascade="all, delete-orphan")
    onboarding_state: Mapped[OnboardingState | None] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        uselist=False,
    )
    calibrations: Mapped[list[GenreCalibration]] = relationship(back_populates="user", cascade="all, delete-orphan")
    feedback: Mapped[list[GenerationFeedback]] = relationship(back_populates="user", cascade="all, delete-orphan")


class UserApiKey(Base):
    __tablename__ = "user_api_keys"
    __table_args__ = (UniqueConstraint("user_id", "provider", name="uq_user_api_key_provider"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    provider: Mapped[str] = mapped_column(String(80), index=True)
    encrypted_value: Mapped[str] = mapped_column(Text, default="")
    model_name: Mapped[str] = mapped_column(String(120), default="")
    status: Mapped[str] = mapped_column(String(300), default="untested")
    last_tested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    user: Mapped[User] = relationship(back_populates="api_keys")


class OnboardingState(Base):
    __tablename__ = "onboarding_states"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    step: Mapped[str] = mapped_column(String(60), default="api_setup")
    api_setup_complete: Mapped[bool] = mapped_column(Boolean, default=False)
    genre_id: Mapped[str] = mapped_column(String(80), default="")
    user_intent: Mapped[str] = mapped_column(Text, default="")
    calibration_status: Mapped[str] = mapped_column(String(40), default="not_started")
    selected_sample_job_id: Mapped[str] = mapped_column(String(36), default="")
    active_chat_id: Mapped[str] = mapped_column(String(36), default="")
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    user: Mapped[User] = relationship(back_populates="onboarding_state")

    @property
    def completed(self) -> bool:
        return self.completed_at is not None


class GenreCalibration(Base):
    __tablename__ = "genre_calibrations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    genre_id: Mapped[str] = mapped_column(String(80), index=True)
    user_intent: Mapped[str] = mapped_column(Text, default="")
    preferred_video_id: Mapped[str] = mapped_column(String(36), default="")
    preferred_script: Mapped[str] = mapped_column(Text, default="")
    why_chosen: Mapped[str] = mapped_column(Text, default="")
    improvement_notes: Mapped[str] = mapped_column(Text, default="")
    preferred_config: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    user: Mapped[User] = relationship(back_populates="calibrations")


class GenerationFeedback(Base):
    __tablename__ = "generation_feedback"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("video_jobs.id"), index=True)
    issue_types: Mapped[list] = mapped_column(JSON, default=list)
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    user: Mapped[User] = relationship(back_populates="feedback")


class Chat(Base):
    __tablename__ = "chats"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(160), default="New chat")
    context_summary: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    user: Mapped[User] = relationship(back_populates="chats")
    messages: Mapped[list[Message]] = relationship(back_populates="chat", cascade="all, delete-orphan")
    jobs: Mapped[list[VideoJob]] = relationship(back_populates="chat", cascade="all, delete-orphan")


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    chat_id: Mapped[str] = mapped_column(ForeignKey("chats.id"), index=True)
    role: Mapped[str] = mapped_column(String(32))
    content: Mapped[str] = mapped_column(Text)
    message_metadata: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    chat: Mapped[Chat] = relationship(back_populates="messages")


class VideoJob(Base):
    __tablename__ = "video_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    chat_id: Mapped[str] = mapped_column(ForeignKey("chats.id"), index=True)
    status: Mapped[str] = mapped_column(String(32), default="queued", index=True)
    topic: Mapped[str] = mapped_column(Text)
    genre: Mapped[str] = mapped_column(String(80), default="scary_stories")
    duration: Mapped[int] = mapped_column(Integer, default=45)
    notes: Mapped[str] = mapped_column(Text, default="")
    settings: Mapped[dict] = mapped_column(JSON, default=dict)
    parent_job_id: Mapped[str] = mapped_column(String(36), default="")
    job_type: Mapped[str] = mapped_column(String(40), default="generation", index=True)
    planned_agents: Mapped[list] = mapped_column(JSON, default=list)
    run_dir: Mapped[str] = mapped_column(Text, default="")
    video_path: Mapped[str] = mapped_column(Text, default="")
    logs_path: Mapped[str] = mapped_column(Text, default="")
    error_message: Mapped[str] = mapped_column(Text, default="")
    stdout: Mapped[str] = mapped_column(Text, default="")
    stderr: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    chat: Mapped[Chat] = relationship(back_populates="jobs")


class Genre(Base):
    __tablename__ = "genres"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(120))
    category: Mapped[str] = mapped_column(String(80), default="")
    tone: Mapped[str] = mapped_column(Text, default="")
    audience_size: Mapped[str] = mapped_column(String(40), default="")
    competition_level: Mapped[str] = mapped_column(String(40), default="")
    content_difficulty: Mapped[str] = mapped_column(String(40), default="")
    recommended_score: Mapped[int] = mapped_column(Integer, default=0)
    default_duration_sec: Mapped[int] = mapped_column(Integer, default=45)
    word_count_min: Mapped[int] = mapped_column(Integer, default=80)
    word_count_max: Mapped[int] = mapped_column(Integer, default=130)
    layout: Mapped[str] = mapped_column(String(80), default="full_image")
    caption_preset: Mapped[str] = mapped_column(String(80), default="default")
    voice_rate: Mapped[float] = mapped_column(Float, default=1.0)
    music_mood: Mapped[str] = mapped_column(String(80), default="")
    realism_mode: Mapped[str] = mapped_column(String(60), default="inspired_by_real_events")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    rules: Mapped[list[GenreRule]] = relationship(back_populates="genre", cascade="all, delete-orphan")
    hooks: Mapped[list[GenreHook]] = relationship(back_populates="genre", cascade="all, delete-orphan")
    reference_videos: Mapped[list[ReferenceVideo]] = relationship(back_populates="genre", cascade="all, delete-orphan")
    visual_style: Mapped[VisualStyleRule | None] = relationship(
        back_populates="genre",
        cascade="all, delete-orphan",
        uselist=False,
    )


class GenreRule(Base):
    __tablename__ = "genre_rules"
    __table_args__ = (UniqueConstraint("genre_id", "rule_type", "value", name="uq_genre_rule"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    genre_id: Mapped[str] = mapped_column(ForeignKey("genres.id"), index=True)
    rule_type: Mapped[str] = mapped_column(String(60), index=True)
    value: Mapped[str] = mapped_column(String(300))
    weight: Mapped[int] = mapped_column(Integer, default=0)
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    genre: Mapped[Genre] = relationship(back_populates="rules")


class GenreHook(Base):
    __tablename__ = "genre_hooks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    genre_id: Mapped[str] = mapped_column(ForeignKey("genres.id"), index=True)
    hook_type: Mapped[str] = mapped_column(String(80), default="")
    template: Mapped[str] = mapped_column(String(500))
    emotional_trigger: Mapped[str] = mapped_column(String(80), default="")
    avg_score: Mapped[float] = mapped_column(Float, default=0.0)
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    genre: Mapped[Genre] = relationship(back_populates="hooks")


class ReferenceVideo(Base):
    __tablename__ = "reference_videos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    genre_id: Mapped[str] = mapped_column(ForeignKey("genres.id"), index=True)
    video_url: Mapped[str] = mapped_column(String(500), unique=True, index=True)
    channel_name: Mapped[str] = mapped_column(String(120), default="")
    channel_subscribers: Mapped[int] = mapped_column(Integer, default=0)
    views: Mapped[int] = mapped_column(Integer, default=0)
    likes: Mapped[int] = mapped_column(Integer, default=0)
    comments: Mapped[int] = mapped_column(Integer, default=0)
    upload_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    duration_sec: Mapped[int] = mapped_column(Integer, default=0)
    title: Mapped[str] = mapped_column(String(160), default="")
    description_first_line: Mapped[str] = mapped_column(String(300), default="")
    hashtags: Mapped[str] = mapped_column(String(500), default="")
    full_script: Mapped[str] = mapped_column(Text, default="")
    word_count: Mapped[int] = mapped_column(Integer, default=0)
    sentence_count: Mapped[int] = mapped_column(Integer, default=0)
    words_per_second: Mapped[float] = mapped_column(Float, default=0.0)
    overall_score: Mapped[float] = mapped_column(Float, default=0.0)
    usable_as_few_shot: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    genre: Mapped[Genre] = relationship(back_populates="reference_videos")
    script_analysis: Mapped[ScriptAnalysis | None] = relationship(
        back_populates="reference_video",
        cascade="all, delete-orphan",
        uselist=False,
    )


class ScriptAnalysis(Base):
    __tablename__ = "script_analysis"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    reference_video_id: Mapped[int] = mapped_column(ForeignKey("reference_videos.id"), unique=True, index=True)
    hook_first_sentence: Mapped[str] = mapped_column(String(500), default="")
    hook_type: Mapped[str] = mapped_column(String(80), default="")
    hook_emotional_trigger: Mapped[str] = mapped_column(String(80), default="")
    hook_speed_sec: Mapped[float] = mapped_column(Float, default=0.0)
    opening_words: Mapped[str] = mapped_column(String(200), default="")
    body_sentence_count: Mapped[int] = mapped_column(Integer, default=0)
    has_twist_reveal: Mapped[bool] = mapped_column(Boolean, default=False)
    twist_line: Mapped[str] = mapped_column(String(700), default="")
    ending_type: Mapped[str] = mapped_column(String(80), default="")
    last_sentence: Mapped[str] = mapped_column(String(500), default="")
    tense_used: Mapped[str] = mapped_column(String(60), default="")
    pov_person: Mapped[str] = mapped_column(String(60), default="")
    narrative_technique: Mapped[str] = mapped_column(String(120), default="")
    emotional_arc: Mapped[str] = mapped_column(String(300), default="")
    power_words: Mapped[str] = mapped_column(String(700), default="")
    emphasis_words: Mapped[str] = mapped_column(String(700), default="")
    sensory_language_used: Mapped[str] = mapped_column(Text, default="")
    retention_hook: Mapped[str] = mapped_column(String(500), default="")
    likely_share_trigger: Mapped[str] = mapped_column(String(500), default="")
    why_it_worked: Mapped[str] = mapped_column(Text, default="")
    what_to_improve: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    reference_video: Mapped[ReferenceVideo] = relationship(back_populates="script_analysis")


class VisualStyleRule(Base):
    __tablename__ = "visual_style_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    genre_id: Mapped[str] = mapped_column(ForeignKey("genres.id"), unique=True, index=True)
    layout_type: Mapped[str] = mapped_column(String(80), default="")
    image_or_video_count: Mapped[int] = mapped_column(Integer, default=0)
    image_change_timing: Mapped[str] = mapped_column(String(120), default="")
    transition_type: Mapped[str] = mapped_column(String(80), default="")
    image_style: Mapped[str] = mapped_column(String(160), default="")
    visual_keywords: Mapped[str] = mapped_column(Text, default="")
    negative_visual_keywords: Mapped[str] = mapped_column(Text, default="")
    caption_style: Mapped[str] = mapped_column(String(120), default="")
    caption_font: Mapped[str] = mapped_column(String(120), default="")
    caption_primary_color: Mapped[str] = mapped_column(String(80), default="")
    caption_highlight_color: Mapped[str] = mapped_column(String(80), default="")
    caption_position: Mapped[str] = mapped_column(String(80), default="")
    music_mood: Mapped[str] = mapped_column(String(80), default="")
    sfx_rules: Mapped[str] = mapped_column(Text, default="")
    source_policy: Mapped[str] = mapped_column(String(80), default="stock_video_first")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    genre: Mapped[Genre] = relationship(back_populates="visual_style")


class TopicExpansionRule(Base):
    __tablename__ = "topic_expansion_rules"
    __table_args__ = (UniqueConstraint("genre_id", "trigger_term", name="uq_topic_expansion_rule"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    genre_id: Mapped[str] = mapped_column(ForeignKey("genres.id"), index=True)
    trigger_term: Mapped[str] = mapped_column(String(120), index=True)
    search_queries: Mapped[str] = mapped_column(Text)
    required_words: Mapped[str] = mapped_column(String(700), default="")
    forbidden_words: Mapped[str] = mapped_column(String(700), default="")
    realism_mode: Mapped[str] = mapped_column(String(60), default="inspired_by_real_events")
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class TopicResearchSource(Base):
    __tablename__ = "topic_research_sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    topic: Mapped[str] = mapped_column(String(300), index=True)
    genre_id: Mapped[str] = mapped_column(ForeignKey("genres.id"), index=True)
    title: Mapped[str] = mapped_column(String(300), default="")
    url: Mapped[str] = mapped_column(String(700), default="")
    source_type: Mapped[str] = mapped_column(String(80), default="")
    snippet: Mapped[str] = mapped_column(Text, default="")
    extracted_facts: Mapped[str] = mapped_column(Text, default="")
    credibility_score: Mapped[float] = mapped_column(Float, default=0.0)
    relevance_score: Mapped[float] = mapped_column(Float, default=0.0)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class GenerationRun(Base):
    __tablename__ = "generation_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_topic: Mapped[str] = mapped_column(String(300), index=True)
    selected_genre_id: Mapped[str] = mapped_column(ForeignKey("genres.id"), index=True)
    selected_angle: Mapped[str] = mapped_column(String(300), default="")
    research_brief: Mapped[str] = mapped_column(Text, default="")
    generated_title: Mapped[str] = mapped_column(String(160), default="")
    generated_script: Mapped[str] = mapped_column(Text, default="")
    relevance_score: Mapped[float] = mapped_column(Float, default=0.0)
    factual_grounding_score: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(60), default="created")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class AiSuggestion(Base):
    __tablename__ = "ai_suggestions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    target_table: Mapped[str] = mapped_column(String(80), index=True)
    target_id: Mapped[str] = mapped_column(String(120), default="")
    suggestion_type: Mapped[str] = mapped_column(String(80), default="")
    old_value: Mapped[str] = mapped_column(Text, default="")
    suggested_value: Mapped[str] = mapped_column(Text, default="")
    reason: Mapped[str] = mapped_column(Text, default="")
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(40), default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class KnowledgeImportBatch(Base):
    __tablename__ = "knowledge_import_batches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_file: Mapped[str] = mapped_column(String(500), default="")
    row_counts: Mapped[dict] = mapped_column(JSON, default=dict)
    errors: Mapped[list] = mapped_column(JSON, default=list)
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class AgentRunSnapshot(Base):
    __tablename__ = "agent_run_snapshots"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    surface: Mapped[str] = mapped_column(String(40), default="playground", index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    chat_id: Mapped[str] = mapped_column(String(36), default="", index=True)
    job_id: Mapped[str] = mapped_column(String(36), default="", index=True)
    user_message: Mapped[str] = mapped_column(Text, default="")
    genre_id: Mapped[str] = mapped_column(String(80), default="", index=True)
    status: Mapped[str] = mapped_column(String(40), default="running", index=True)
    pipeline_run_dir: Mapped[str] = mapped_column(Text, default="")
    payload_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)
