from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import PlaygroundBase, StaticBase, UserBase


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def uuid_str() -> str:
    return str(uuid.uuid4())


class User(UserBase):
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
    payment_checkouts: Mapped[list[PaymentCheckout]] = relationship(back_populates="user", cascade="all, delete-orphan")
    entitlement: Mapped[UserEntitlement | None] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        uselist=False,
    )


class UserApiKey(UserBase):
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


class OnboardingState(UserBase):
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


class GenreCalibration(UserBase):
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


class GenerationFeedback(UserBase):
    __tablename__ = "generation_feedback"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("video_jobs.id"), index=True)
    issue_types: Mapped[list] = mapped_column(JSON, default=list)
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    user: Mapped[User] = relationship(back_populates="feedback")


class PaymentCheckout(UserBase):
    __tablename__ = "payment_checkouts"
    __table_args__ = (
        Index("ix_payment_checkouts_user_status", "user_id", "status"),
        Index("ix_payment_checkouts_order", "razorpay_order_id"),
        Index("ix_payment_checkouts_subscription", "razorpay_subscription_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    plan_code: Mapped[str] = mapped_column(String(40), index=True)
    kind: Mapped[str] = mapped_column(String(30), default="subscription")
    amount_paise: Mapped[int] = mapped_column(Integer, default=0)
    currency: Mapped[str] = mapped_column(String(8), default="INR")
    status: Mapped[str] = mapped_column(String(40), default="created", index=True)
    razorpay_order_id: Mapped[str] = mapped_column(String(120), default="", index=True)
    razorpay_subscription_id: Mapped[str] = mapped_column(String(120), default="", index=True)
    razorpay_payment_id: Mapped[str] = mapped_column(String(120), default="", index=True)
    razorpay_signature: Mapped[str] = mapped_column(Text, default="")
    checkout_metadata: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped[User] = relationship(back_populates="payment_checkouts")


class UserEntitlement(UserBase):
    __tablename__ = "user_entitlements"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    source: Mapped[str] = mapped_column(String(40), default="none", index=True)
    status: Mapped[str] = mapped_column(String(40), default="inactive", index=True)
    plan_code: Mapped[str] = mapped_column(String(40), default="")
    razorpay_subscription_id: Mapped[str] = mapped_column(String(120), default="", index=True)
    razorpay_payment_id: Mapped[str] = mapped_column(String(120), default="", index=True)
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    user: Mapped[User] = relationship(back_populates="entitlement")


class RazorpayWebhookEvent(UserBase):
    __tablename__ = "razorpay_webhook_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_id: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    event_type: Mapped[str] = mapped_column(String(120), default="", index=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Chat(UserBase):
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


class Message(UserBase):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    chat_id: Mapped[str] = mapped_column(ForeignKey("chats.id"), index=True)
    role: Mapped[str] = mapped_column(String(32))
    content: Mapped[str] = mapped_column(Text)
    message_metadata: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    chat: Mapped[Chat] = relationship(back_populates="messages")


class VideoJob(UserBase):
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


class Genre(StaticBase):
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
    hook_patterns: Mapped[list] = mapped_column(JSON, default=list)
    banned_phrases: Mapped[list] = mapped_column(JSON, default=list)
    visual_style: Mapped[dict] = mapped_column(JSON, default=dict)
    topic_rules: Mapped[list] = mapped_column(JSON, default=list)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

class ReferenceExample(StaticBase):
    __tablename__ = "reference_examples"
    __table_args__ = (
        Index("ix_reference_examples_genre_score", "genre_id", "overall_score"),
        Index("ix_reference_examples_genre_enabled", "genre_id", "usable_as_few_shot"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    genre_id: Mapped[str] = mapped_column(String(80), index=True)
    source_url: Mapped[str] = mapped_column(String(700), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(200), default="")
    source_label: Mapped[str] = mapped_column(String(120), default="")
    script: Mapped[str] = mapped_column(Text, default="")
    description: Mapped[str] = mapped_column(Text, default="")
    tags: Mapped[list] = mapped_column(JSON, default=list)
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    analysis: Mapped[dict] = mapped_column(JSON, default=dict)
    facts: Mapped[list] = mapped_column(JSON, default=list)
    duration_sec: Mapped[int] = mapped_column(Integer, default=0)
    word_count: Mapped[int] = mapped_column(Integer, default=0)
    overall_score: Mapped[float] = mapped_column(Float, default=0.0)
    usable_as_few_shot: Mapped[bool] = mapped_column(Boolean, default=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class StaticAsset(StaticBase):
    __tablename__ = "static_assets"
    __table_args__ = (
        Index("ix_static_assets_type_enabled", "asset_type", "enabled"),
        Index("ix_static_assets_type_source", "asset_type", "source"),
        Index("ix_static_assets_mood_enabled", "mood", "enabled"),
        Index("ix_static_assets_intensity_enabled", "intensity", "enabled"),
    )

    id: Mapped[str] = mapped_column(String(120), primary_key=True)
    asset_type: Mapped[str] = mapped_column(String(30), default="music", index=True)
    name: Mapped[str] = mapped_column(String(180), default="")
    path: Mapped[str] = mapped_column(Text, unique=True)
    description: Mapped[str] = mapped_column(Text, default="")
    tags: Mapped[list] = mapped_column(JSON, default=list)
    aliases: Mapped[list] = mapped_column(JSON, default=list)
    use_cases: Mapped[list] = mapped_column(JSON, default=list)
    mood: Mapped[str] = mapped_column(String(80), default="", index=True)
    intensity: Mapped[str] = mapped_column(String(40), default="", index=True)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    source: Mapped[str] = mapped_column(String(80), default="local", index=True)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class AgentRunSnapshot(PlaygroundBase):
    __tablename__ = "agent_run_snapshots"
    __table_args__ = (
        Index("ix_agent_run_snapshots_surface_updated", "surface", "updated_at"),
        Index("ix_agent_run_snapshots_status_updated", "status", "updated_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    surface: Mapped[str] = mapped_column(String(40), default="playground", index=True)
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    chat_id: Mapped[str] = mapped_column(String(36), default="", index=True)
    job_id: Mapped[str] = mapped_column(String(36), default="", index=True)
    user_message: Mapped[str] = mapped_column(Text, default="")
    genre_id: Mapped[str] = mapped_column(String(80), default="", index=True)
    status: Mapped[str] = mapped_column(String(40), default="running", index=True)
    pipeline_run_dir: Mapped[str] = mapped_column(Text, default="")
    payload_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)
