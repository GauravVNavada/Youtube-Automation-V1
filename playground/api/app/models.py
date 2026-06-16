from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def uuid_str() -> str:
    return str(uuid.uuid4())


class PlaygroundRun(Base):
    __tablename__ = "playground_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    user_message: Mapped[str] = mapped_column(Text)
    route_summary: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(32), default="queued", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    stages: Mapped[list["PlaygroundStage"]] = relationship(back_populates="run", cascade="all, delete-orphan")
    events: Mapped[list["PlaygroundEvent"]] = relationship(back_populates="run", cascade="all, delete-orphan")
    artifacts: Mapped[list["PlaygroundArtifact"]] = relationship(back_populates="run", cascade="all, delete-orphan")


class PlaygroundStage(Base):
    __tablename__ = "playground_stages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    run_id: Mapped[str] = mapped_column(ForeignKey("playground_runs.id"), index=True)
    agent_name: Mapped[str] = mapped_column(String(80), index=True)
    order_index: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    input_json: Mapped[dict] = mapped_column(JSON, default=dict)
    prompt_text: Mapped[str] = mapped_column(Text, default="")
    output_json: Mapped[dict] = mapped_column(JSON, default=dict)
    error_text: Mapped[str] = mapped_column(Text, default="")

    run: Mapped[PlaygroundRun] = relationship(back_populates="stages")
    events: Mapped[list["PlaygroundEvent"]] = relationship(back_populates="stage", cascade="all, delete-orphan")
    artifacts: Mapped[list["PlaygroundArtifact"]] = relationship(back_populates="stage", cascade="all, delete-orphan")


class PlaygroundEvent(Base):
    __tablename__ = "playground_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("playground_runs.id"), index=True)
    stage_id: Mapped[str | None] = mapped_column(ForeignKey("playground_stages.id"), nullable=True, index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)
    level: Mapped[str] = mapped_column(String(32), default="info")
    message: Mapped[str] = mapped_column(Text)
    payload_json: Mapped[dict] = mapped_column(JSON, default=dict)

    run: Mapped[PlaygroundRun] = relationship(back_populates="events")
    stage: Mapped[PlaygroundStage | None] = relationship(back_populates="events")


class PlaygroundArtifact(Base):
    __tablename__ = "playground_artifacts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    run_id: Mapped[str] = mapped_column(ForeignKey("playground_runs.id"), index=True)
    stage_id: Mapped[str | None] = mapped_column(ForeignKey("playground_stages.id"), nullable=True, index=True)
    kind: Mapped[str] = mapped_column(String(80), default="file")
    path: Mapped[str] = mapped_column(Text)
    mime_type: Mapped[str] = mapped_column(String(160), default="application/octet-stream")
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    previewable: Mapped[bool] = mapped_column(default=False)

    run: Mapped[PlaygroundRun] = relationship(back_populates="artifacts")
    stage: Mapped[PlaygroundStage | None] = relationship(back_populates="artifacts")
