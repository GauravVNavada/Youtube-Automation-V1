from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.dependencies import get_current_user
from app.jobs import run_video_job
from app.models import Chat, GenerationFeedback, GenreCalibration, OnboardingState, User, VideoJob, utc_now
from app.schemas import FeedbackIn, FeedbackOut, GenerateVideoIn, JobOut
from app.services.generation_settings import normalize_generation_settings
from app.services.queue import get_queue
from pipeline.agents.master_agent import build_agent_contracts, generation_constraints


router = APIRouter(prefix="/generate", tags=["generation"])


@router.post("", response_model=JobOut)
def generate_video(
    payload: GenerateVideoIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> VideoJob:
    if payload.mode == "custom" and not payload.topic.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Custom mode needs a topic")
    chat = _get_or_create_flow_chat(db, user.id)
    topic = payload.topic.strip() or _auto_topic(payload.genre_id)
    settings = normalize_generation_settings(payload.settings.model_dump(), text=topic, prefer_text=True)
    if chat.title == "New chat":
        chat.title = topic[:80]
    chat.updated_at = utc_now()
    notes = _build_generation_notes(db, user.id, payload.genre_id, settings)
    contracts = build_agent_contracts(settings, genre_id=payload.genre_id, duration=int(settings["duration"]))
    job = VideoJob(
        user_id=user.id,
        chat_id=chat.id,
        topic=topic,
        genre=payload.genre_id,
        duration=settings["duration"],
        notes=notes,
        settings=settings,
        job_type="generation",
        planned_agents=contracts,
    )
    db.add(job)
    db.flush()
    db.commit()
    db.refresh(job)
    get_queue().enqueue(run_video_job, job.id, job_timeout=1200)
    return job


@router.post("/jobs/{job_id}/feedback", response_model=FeedbackOut)
def save_feedback(
    job_id: str,
    payload: FeedbackIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> GenerationFeedback:
    job = db.get(VideoJob, job_id)
    if not job or job.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    feedback = GenerationFeedback(
        user_id=user.id,
        job_id=job.id,
        issue_types=payload.issue_types,
        notes=payload.notes,
    )
    db.add(feedback)
    db.commit()
    db.refresh(feedback)
    return feedback


def _get_or_create_flow_chat(db: Session, user_id: int) -> Chat:
    state = db.get(OnboardingState, user_id)
    chat = db.get(Chat, state.active_chat_id) if state and state.active_chat_id else None
    if chat and chat.user_id == user_id:
        return chat
    chat = db.scalar(select(Chat).where(Chat.user_id == user_id).order_by(Chat.updated_at.desc()))
    if chat:
        if state:
            state.active_chat_id = chat.id
        return chat
    chat = Chat(user_id=user_id, title="New chat")
    db.add(chat)
    db.flush()
    if state:
        state.active_chat_id = chat.id
    return chat


def _build_generation_notes(db: Session, user_id: int, genre_id: str, settings: dict) -> str:
    constraints = generation_constraints(settings, genre_id=genre_id, duration=int(settings["duration"]))
    parts = [
        "Use simple, easy English and short spoken sentences.",
        f"Dynamic controls: {settings}",
        f"Master constraints JSON: {json.dumps(constraints, ensure_ascii=True)}",
        "Pipeline order: Master decides route and constraints; Script writes within constraints; Script self-checks; Validation checks; invalid scripts auto-repair; only then assets, audio, captions, and render continue.",
    ]
    calibration = db.scalar(
        select(GenreCalibration)
        .where(GenreCalibration.user_id == user_id, GenreCalibration.genre_id == genre_id)
        .order_by(GenreCalibration.updated_at.desc())
    )
    if calibration:
        parts.extend(
            [
                f"User genre intent: {calibration.user_intent}",
                f"They liked: {calibration.why_chosen}",
                f"They want improved: {calibration.improvement_notes}",
                f"Reference style script: {calibration.preferred_script[:700]}",
            ]
        )
    feedback_rows = list(
        db.scalars(
            select(GenerationFeedback)
            .where(GenerationFeedback.user_id == user_id)
            .order_by(GenerationFeedback.created_at.desc())
            .limit(5)
        )
    )
    if feedback_rows:
        parts.append("Avoid these repeated mistakes from previous videos:")
        for item in feedback_rows:
            parts.append(f"- {', '.join(item.issue_types)}: {item.notes}")
    return "\n".join(part for part in parts if part.strip())


def _auto_topic(genre_id: str) -> str:
    readable = genre_id.replace("_", " ")
    return f"Auto-generated high-retention {readable} short based on user calibration"
