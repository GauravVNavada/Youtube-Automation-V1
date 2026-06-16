from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class RunCreate(BaseModel):
    message: str = Field(min_length=1, max_length=3000)
    genre_id: str = Field(default="scary_stories", max_length=80)
    llm_provider: str = Field(default="env", max_length=40)
    llm_model: str = Field(default="", max_length=120)
    llm_api_key: str = Field(default="", max_length=8000)


class GenreOut(BaseModel):
    genre_id: str
    display_name: str
    tone: str
    word_count_min: int
    word_count_max: int


class LLMOptionOut(BaseModel):
    provider: str
    label: str
    models: list[str]
    default_model: str


class ArtifactOut(BaseModel):
    id: str
    stage_id: str | None
    kind: str
    path: str
    mime_type: str
    size_bytes: int
    previewable: bool

    class Config:
        from_attributes = True


class EventOut(BaseModel):
    id: int
    run_id: str
    stage_id: str | None
    timestamp: datetime
    level: str
    message: str
    payload_json: dict[str, Any]

    class Config:
        from_attributes = True


class StageSummaryOut(BaseModel):
    id: str
    agent_name: str
    order_index: int
    status: str
    execution_mode: str = ""
    started_at: datetime | None
    completed_at: datetime | None
    error_text: str

    class Config:
        from_attributes = True


class StageDetailOut(StageSummaryOut):
    input_json: dict[str, Any]
    prompt_text: str
    output_json: dict[str, Any]
    events: list[EventOut]
    artifacts: list[ArtifactOut]


class GraphEdgeOut(BaseModel):
    source: str
    target: str


class RunSummaryOut(BaseModel):
    id: str
    user_message: str
    route_summary: str
    status: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class RunDetailOut(RunSummaryOut):
    stages: list[StageSummaryOut]
    edges: list[GraphEdgeOut]
