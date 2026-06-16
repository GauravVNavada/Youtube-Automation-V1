from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.dependencies import get_current_user
from app.models import Chat, GenerationFeedback, OnboardingState, User, VideoJob
from app.schemas import FeedbackIn, FeedbackOut, GenerateVideoIn, JobOut
from app.services.agent_contracts import build_agent_contracts
from app.services.generation_settings import normalize_generation_settings
from app.services.queue import get_queue


router = APIRouter(prefix="/generate", tags=["generation"])


@router.post("", response_model=JobOut)
def generate_video(
    payload: GenerateVideoIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> VideoJob:
    state = _state_for(db, user)
    chat = _active_chat(db, user, state)
    settings = normalize_generation_settings(payload.settings.model_dump())
    topic = payload.topic.strip() or state.user_intent or "grounded short video"
    job = VideoJob(
        user_id=user.id,
        chat_id=chat.id,
        status="queued",
        topic=topic,
        genre=payload.genre_id,
        duration=int(settings["duration"]),
        settings=settings,
        planned_agents=build_agent_contracts(settings, genre_id=payload.genre_id, duration=int(settings["duration"])),
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    _enqueue_job(job.id)
    return job


@router.post("/jobs/{job_id}/feedback", response_model=FeedbackOut)
def save_feedback(
    job_id: str,
    payload: FeedbackIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> GenerationFeedback:
    job = db.get(VideoJob, job_id)
    if job is None or job.user_id != user.id:
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


def _state_for(db: Session, user: User) -> OnboardingState:
    state = db.get(OnboardingState, user.id)
    if state is None:
        state = OnboardingState(user_id=user.id)
        db.add(state)
        db.flush()
    return state


def _active_chat(db: Session, user: User, state: OnboardingState) -> Chat:
    chat = db.get(Chat, state.active_chat_id) if state.active_chat_id else None
    if chat is None or chat.user_id != user.id:
        chat = Chat(user_id=user.id, title="Studio")
        db.add(chat)
        db.flush()
        state.active_chat_id = chat.id
    return chat


def _enqueue_job(job_id: str) -> None:
    try:
        get_queue().enqueue("app.jobs.run_video_job", job_id)
    except Exception:
        return
