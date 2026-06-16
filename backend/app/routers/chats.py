from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.dependencies import get_current_user
from app.jobs import run_video_job
from app.models import Chat, GenerationFeedback, GenreCalibration, Message, OnboardingState, User, VideoJob, utc_now
from app.schemas import ChatCreate, ChatOut, ChatReply, MessageCreate, MessageOut
from app.services.master_llm import create_master_llm_client
from app.services.queue import get_queue
from pipeline.agents.master_agent import MasterAgent, MasterContext


router = APIRouter(prefix="/chats", tags=["chats"])


@router.post("", response_model=ChatOut)
def create_chat(
    payload: ChatCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Chat:
    chat = Chat(user_id=user.id, title=payload.title.strip() or "New chat")
    db.add(chat)
    db.commit()
    db.refresh(chat)
    return chat


@router.get("", response_model=list[ChatOut])
def list_chats(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[Chat]:
    return list(
        db.scalars(
            select(Chat)
            .where(Chat.user_id == user.id)
            .order_by(Chat.updated_at.desc())
        )
    )


@router.get("/{chat_id}/messages", response_model=list[MessageOut])
def list_messages(
    chat_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[Message]:
    chat = _get_owned_chat(db, chat_id, user.id)
    return list(db.scalars(select(Message).where(Message.chat_id == chat.id).order_by(Message.created_at.asc())))


@router.post("/{chat_id}/activate", response_model=ChatOut)
def activate_chat(
    chat_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Chat:
    chat = _get_owned_chat(db, chat_id, user.id)
    state = db.get(OnboardingState, user.id)
    if not state:
        state = OnboardingState(user_id=user.id)
        db.add(state)
    state.active_chat_id = chat.id
    state.updated_at = utc_now()
    db.commit()
    db.refresh(chat)
    return chat


@router.post("/{chat_id}/messages", response_model=ChatReply)
def send_message(
    chat_id: str,
    payload: MessageCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ChatReply:
    chat = _get_owned_chat(db, chat_id, user.id)
    history = list(db.scalars(select(Message).where(Message.chat_id == chat.id).order_by(Message.created_at.asc())))
    user_message = Message(chat_id=chat.id, role="user", content=payload.content, message_metadata={})
    db.add(user_message)
    db.flush()

    master_context = _build_master_context(db, user.id, chat.id)
    decision = MasterAgent(create_master_llm_client(db, user.id)).decide(
        payload.content,
        history + [user_message],
        master_context,
    )
    job_id = None
    queued_job_id = None
    assistant_metadata = {"intent": decision.intent}

    if decision.intent == "generate_video":
        job = VideoJob(
            user_id=user.id,
            chat_id=chat.id,
            topic=decision.topic,
            genre=decision.genre,
            duration=decision.duration,
            notes=decision.notes,
            settings=decision.settings or {"duration": decision.duration},
            parent_job_id=decision.parent_job_id,
            job_type="generation",
            planned_agents=decision.planned_agents or [],
        )
        db.add(job)
        db.flush()
        job_id = job.id
        queued_job_id = job.id
        assistant_metadata.update(
            {
                "job_id": job.id,
                "planned_agents": job.planned_agents,
                "constraints": decision.constraints or {},
                "agent_contracts": decision.agent_contracts or [],
                "ai_master_decision": decision.ai_master_decision or {},
                "parent_job_id": job.parent_job_id,
                "settings": job.settings,
            }
        )
    elif decision.ai_master_decision:
        assistant_metadata["ai_master_decision"] = decision.ai_master_decision

    assistant_message = Message(
        chat_id=chat.id,
        role="assistant",
        content=decision.assistant_message,
        message_metadata=assistant_metadata,
    )
    chat.updated_at = utc_now()
    if chat.title == "New chat":
        chat.title = _title_from_message(payload.content)
    chat.context_summary = _updated_summary(chat.context_summary, payload.content, decision.assistant_message)
    db.add(assistant_message)
    db.commit()
    if queued_job_id:
        get_queue().enqueue(run_video_job, queued_job_id, job_timeout=1200)
    db.refresh(assistant_message)
    return ChatReply(message=assistant_message, job_id=job_id)


def _get_owned_chat(db: Session, chat_id: str, user_id: int) -> Chat:
    chat = db.get(Chat, chat_id)
    if not chat or chat.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chat not found")
    return chat


def _title_from_message(message: str) -> str:
    title = " ".join(message.strip().split())
    return title[:80] if title else "New chat"


def _build_master_context(db: Session, user_id: int, chat_id: str) -> MasterContext:
    state = db.get(OnboardingState, user_id)
    genre_id = state.genre_id if state and state.genre_id else "scary_stories"
    calibration = db.scalar(
        select(GenreCalibration)
        .where(GenreCalibration.user_id == user_id, GenreCalibration.genre_id == genre_id)
        .order_by(GenreCalibration.updated_at.desc())
    )
    latest_job = db.scalar(
        select(VideoJob)
        .where(
            VideoJob.user_id == user_id,
            VideoJob.chat_id == chat_id,
            VideoJob.job_type == "generation",
        )
        .order_by(VideoJob.created_at.desc())
    )
    feedback_rows = list(
        db.scalars(
            select(GenerationFeedback)
            .where(GenerationFeedback.user_id == user_id)
            .order_by(GenerationFeedback.created_at.desc())
            .limit(5)
        )
    )
    feedback_notes = [
        f"{', '.join(item.issue_types)}: {item.notes}".strip(": ")
        for item in feedback_rows
        if item.notes or item.issue_types
    ]
    return MasterContext(
        onboarding_complete=bool(state and state.calibration_status == "completed"),
        genre_id=genre_id,
        user_intent=state.user_intent if state else "",
        preferred_script=calibration.preferred_script if calibration else "",
        calibration_notes=_calibration_notes(calibration),
        preferred_settings=calibration.preferred_config if calibration else {},
        latest_generation_topic=latest_job.topic if latest_job else "",
        latest_generation_job_id=latest_job.id if latest_job else "",
        latest_generation_settings=latest_job.settings if latest_job else {},
        feedback_notes=feedback_notes,
    )


def _calibration_notes(calibration: GenreCalibration | None) -> str:
    if not calibration:
        return ""
    parts = [
        f"User picked sample {calibration.preferred_video_id}.",
        f"Liked because: {calibration.why_chosen}",
        f"Improve next time: {calibration.improvement_notes}",
    ]
    return "\n".join(part for part in parts if part.strip())


def _updated_summary(previous: str, user_text: str, assistant_text: str) -> str:
    lines = [line for line in (previous or "").splitlines()[-8:] if line.strip()]
    lines.append(f"User: {user_text[:240]}")
    lines.append(f"Assistant: {assistant_text[:240]}")
    return "\n".join(lines)[-3000:]
