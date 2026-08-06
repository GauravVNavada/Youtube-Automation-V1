from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.services.generation_settings import (
    DEFAULT_GENERATION_SETTINGS,
    MAX_DURATION_SECONDS,
    MAX_VOICE_SPEED,
    MIN_DURATION_SECONDS,
    MIN_VOICE_SPEED,
)


MAX_PASSWORD_LENGTH = 256


class OrmModel(BaseModel):
    class Config:
        from_attributes = True
        orm_mode = True


class UserCreate(BaseModel):
    email: str
    password: str = Field(min_length=8, max_length=MAX_PASSWORD_LENGTH)
    display_name: str = ""


class LoginRequest(BaseModel):
    email: str
    password: str = Field(min_length=1, max_length=MAX_PASSWORD_LENGTH)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserOut(OrmModel):
    id: int
    email: str
    display_name: str = ""
    created_at: datetime


class ProfileUpdateIn(BaseModel):
    display_name: str = Field(default="", max_length=120)


class BillingPlanOut(BaseModel):
    code: str
    label: str
    kind: str
    amount_paise: int
    currency: str
    interval: str = ""
    configured: bool = False


class BillingCheckoutIn(BaseModel):
    plan_code: str = Field(min_length=1, max_length=40)


class BillingCheckoutOut(BaseModel):
    checkout_id: str
    key_id: str
    plan_code: str
    label: str
    kind: str
    amount_paise: int
    currency: str
    order_id: str = ""
    subscription_id: str = ""
    prefill: dict[str, str] = {}


class BillingVerifyIn(BaseModel):
    checkout_id: str = Field(min_length=1, max_length=36)
    razorpay_payment_id: str = Field(min_length=1, max_length=120)
    razorpay_signature: str = Field(min_length=1, max_length=500)
    razorpay_order_id: str = Field(default="", max_length=120)
    razorpay_subscription_id: str = Field(default="", max_length=120)


class EntitlementOut(BaseModel):
    active: bool
    source: str = "none"
    status: str = "inactive"
    plan_code: str = ""
    expires_at: datetime | None = None


class ApiKeyIn(BaseModel):
    provider: str = Field(min_length=1, max_length=80)
    value: str = Field(default="", max_length=8000)
    model: str = Field(default="", max_length=120)


class ApiKeyStatusOut(BaseModel):
    provider: str
    status: str
    source: str = "user"
    model: str = ""
    last_tested_at: datetime | None = None


class LLMOptionOut(BaseModel):
    provider: str
    label: str
    default_model: str
    configured: bool = False


class ApiSetupOut(BaseModel):
    required: dict[str, bool]
    statuses: list[ApiKeyStatusOut]
    llm_options: list[LLMOptionOut] = []


class GenreOut(BaseModel):
    genre_id: str
    display_name: str
    category: str = ""
    tone: str = ""
    default_duration_sec: int = 45
    word_count_min: int = 80
    word_count_max: int = 130
    recommended_score: int = 0


class GenerationSettings(BaseModel):
    duration: int = Field(
        default=DEFAULT_GENERATION_SETTINGS["duration"],
        ge=MIN_DURATION_SECONDS,
        le=MAX_DURATION_SECONDS,
    )
    voice_speed: float = Field(
        default=DEFAULT_GENERATION_SETTINGS["voice_speed"],
        ge=MIN_VOICE_SPEED,
        le=MAX_VOICE_SPEED,
    )
    caption_words: int = Field(default=DEFAULT_GENERATION_SETTINGS["caption_words"], ge=1, le=10)
    image_count: int = Field(default=DEFAULT_GENERATION_SETTINGS["image_count"], ge=3, le=24)
    music_volume: float = Field(default=DEFAULT_GENERATION_SETTINGS["music_volume"], ge=0, le=0.8)
    schedule: str = DEFAULT_GENERATION_SETTINGS["schedule"]


class OnboardingStateOut(OrmModel):
    user_id: int
    step: str = "api_setup"
    api_setup_complete: bool = False
    genre_id: str = ""
    user_intent: str = ""
    calibration_status: str = "not_started"
    selected_sample_job_id: str = ""
    active_chat_id: str = ""
    completed: bool = False
    completed_at: datetime | None = None


class GenreIntentIn(BaseModel):
    genre_id: str = Field(min_length=1, max_length=80)
    user_intent: str = Field(min_length=1, max_length=3000)


class CalibrationStartIn(BaseModel):
    genre_id: str = Field(min_length=1, max_length=80)
    user_intent: str = Field(min_length=1, max_length=3000)
    settings: GenerationSettings = Field(default_factory=GenerationSettings)


class CalibrationCompleteIn(BaseModel):
    preferred_video_id: str = Field(min_length=1, max_length=36)
    why_chosen: str = Field(min_length=1, max_length=3000)
    improvement_notes: str = Field(default="", max_length=3000)


class CalibrationOut(OrmModel):
    id: int
    genre_id: str
    user_intent: str
    preferred_video_id: str = ""
    preferred_config: dict[str, Any] = {}


class GenerateVideoIn(BaseModel):
    genre_id: str = Field(min_length=1, max_length=80)
    mode: str = "auto"
    topic: str = Field(default="", max_length=1000)
    settings: GenerationSettings = Field(default_factory=GenerationSettings)


class FeedbackIn(BaseModel):
    issue_types: list[str] = Field(default_factory=list)
    notes: str = Field(default="", max_length=3000)


class FeedbackOut(OrmModel):
    id: int
    job_id: str
    issue_types: list[str]
    notes: str
    created_at: datetime


class ChatCreate(BaseModel):
    title: str = "New chat"


class ChatOut(OrmModel):
    id: str
    title: str
    context_summary: str = ""
    created_at: datetime
    updated_at: datetime


class ResetFlowOut(BaseModel):
    chat: ChatOut
    onboarding: OnboardingStateOut


class MessageCreate(BaseModel):
    content: str = Field(min_length=1)


class MessageOut(OrmModel):
    id: int
    chat_id: str
    role: str
    content: str
    message_metadata: dict[str, Any] = {}
    created_at: datetime


class ChatReply(BaseModel):
    message: MessageOut
    job_id: str | None = None


class JobOut(OrmModel):
    id: str
    user_id: int
    chat_id: str
    status: str
    topic: str
    genre: str
    duration: int
    notes: str = ""
    settings: dict[str, Any] = {}
    parent_job_id: str = ""
    job_type: str = "generation"
    planned_agents: list[dict[str, Any]] = []
    run_dir: str = ""
    video_path: str = ""
    logs_path: str = ""
    error_message: str = ""
    stdout: str = ""
    stderr: str = ""
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    download_url: str | None = None
    preview_url: str | None = None
    shorts_cover_url: str | None = None
    youtube_thumbnail_url: str | None = None
    render_plan_url: str | None = None


class JobRetryIn(BaseModel):
    stage_name: str = Field(default="", max_length=80)
    notes: str = Field(default="", max_length=2000)


class AgentProgressOut(BaseModel):
    name: str
    label: str
    status: str = "queued"
    message: str = ""


class JobProgressOut(BaseModel):
    job_id: str
    status: str
    percent: int
    current_agent: str = ""
    agents: list[AgentProgressOut] = []
    events: list[dict[str, Any]] = []
    error_message: str = ""


class JobLogsOut(BaseModel):
    job_id: str
    events: list[dict[str, Any]] = []
    stdout: str = ""
    stderr: str = ""
    error_message: str = ""


class StageLogsOut(BaseModel):
    job_id: str
    stage_name: str
    label: str = ""
    status: str = "queued"
    message: str = ""
    events: list[dict[str, Any]] = []
    input_json: dict[str, Any] | list[Any] | None = None
    output_json: dict[str, Any] | list[Any] | None = None
    error_json: dict[str, Any] | None = None
    error_message: str = ""
    stdout_lines: list[str] = []


try:
    from final_pipeline.app.schemas import (  # type: ignore[F401]
        AssetBundle,
        AudioBundle,
        CaptionBundle,
        GenreConfig,
        GrowthContext,
        ImageCue,
        MusicBundle,
        NicheProfile,
        PipelineContext,
        RenderResult,
        ResearchOutput,
        ResearchSource,
        ScriptOutput,
        SfxCue,
        ThumbnailOutput,
        TimedVisualCue,
        TopicCandidate,
        TopicDiscoveryOutput,
        ValidationResult,
        VisualStylePlan,
        WordTimestamp,
    )
except Exception:
    pass
