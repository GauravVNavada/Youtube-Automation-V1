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


class UserOut(BaseModel):
    id: int
    email: str
    display_name: str
    created_at: datetime

    class Config:
        from_attributes = True


class ApiKeyIn(BaseModel):
    provider: str = Field(min_length=1, max_length=80)
    value: str = Field(default="", max_length=8000)
    model: str = Field(default="", max_length=120)


class ApiKeyStatusOut(BaseModel):
    provider: str
    configured: bool
    status: str
    source: str = "user"
    model: str = ""
    last_tested_at: datetime | None = None


class LLMOptionOut(BaseModel):
    provider: str
    label: str
    models: list[str]
    default_model: str


class ApiSetupOut(BaseModel):
    keys: list[ApiKeyStatusOut]
    complete: bool
    required: dict[str, bool]
    llm_options: list[LLMOptionOut] = []


class GenreOut(BaseModel):
    genre_id: str
    display_name: str
    tone: str
    word_count_min: int
    word_count_max: int


class GenerationSettings(BaseModel):
    duration: int = Field(default=DEFAULT_GENERATION_SETTINGS["duration"], ge=MIN_DURATION_SECONDS, le=MAX_DURATION_SECONDS)
    voice_speed: float = Field(default=DEFAULT_GENERATION_SETTINGS["voice_speed"], ge=MIN_VOICE_SPEED, le=MAX_VOICE_SPEED)
    caption_words: int = Field(default=DEFAULT_GENERATION_SETTINGS["caption_words"], ge=1, le=10)
    image_count: int = Field(default=DEFAULT_GENERATION_SETTINGS["image_count"], ge=3, le=24)
    music_volume: float = Field(default=DEFAULT_GENERATION_SETTINGS["music_volume"], ge=0.0, le=0.8)
    schedule: str = "now"


class OnboardingStateOut(BaseModel):
    step: str
    api_setup_complete: bool
    genre_id: str
    user_intent: str
    calibration_status: str
    selected_sample_job_id: str
    active_chat_id: str = ""
    completed: bool


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


class CalibrationOut(BaseModel):
    genre_id: str
    user_intent: str
    preferred_video_id: str
    why_chosen: str
    improvement_notes: str
    preferred_config: dict[str, Any]

    class Config:
        from_attributes = True


class GenerateVideoIn(BaseModel):
    genre_id: str = Field(min_length=1, max_length=80)
    mode: str = "auto"
    topic: str = Field(default="", max_length=1000)
    settings: GenerationSettings = Field(default_factory=GenerationSettings)


class FeedbackIn(BaseModel):
    issue_types: list[str] = Field(default_factory=list)
    notes: str = Field(default="", max_length=3000)


class FeedbackOut(BaseModel):
    id: int
    job_id: str
    issue_types: list[str]
    notes: str
    created_at: datetime

    class Config:
        from_attributes = True


class ChatCreate(BaseModel):
    title: str = "New chat"


class ChatOut(BaseModel):
    id: str
    title: str
    context_summary: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ResetFlowOut(BaseModel):
    state: OnboardingStateOut
    chat: ChatOut


class MessageCreate(BaseModel):
    content: str = Field(min_length=1)


class MessageOut(BaseModel):
    id: int
    role: str
    content: str
    message_metadata: dict[str, Any]
    created_at: datetime

    class Config:
        from_attributes = True


class ChatReply(BaseModel):
    message: MessageOut
    job_id: str | None = None


class JobOut(BaseModel):
    id: str
    chat_id: str
    status: str
    topic: str
    genre: str
    duration: int
    notes: str
    settings: dict[str, Any] = {}
    parent_job_id: str = ""
    job_type: str = "generation"
    planned_agents: list[Any]
    run_dir: str
    video_path: str
    logs_path: str
    error_message: str
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    download_url: str | None = None
    preview_url: str | None = None
    shorts_cover_url: str | None = None
    youtube_thumbnail_url: str | None = None
    render_plan_url: str | None = None

    class Config:
        from_attributes = True


class AgentProgressOut(BaseModel):
    name: str
    label: str
    status: str
    message: str = ""
    events: list[dict[str, Any]] = []


class JobProgressOut(BaseModel):
    job_id: str
    status: str
    job_type: str
    topic: str
    percent: int
    current_agent: str
    agents: list[AgentProgressOut]
    events: list[dict[str, Any]]
    error_message: str = ""


class JobLogsOut(BaseModel):
    job_id: str
    status: str
    run_dir: str
    events: list[dict[str, Any]]
    stdout: str = ""
    stderr: str = ""
    error_message: str = ""
