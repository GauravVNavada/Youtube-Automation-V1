from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.dependencies import get_current_user
from app.models import Chat, GenerationFeedback, GenreCalibration, Message, OnboardingState, User, VideoJob
from app.schemas import ChatCreate, ChatOut, ChatReply, MessageCreate, MessageOut
from app.services.agent_contracts import build_agent_contracts
from app.services.generation_settings import normalize_generation_settings
from app.services.master_agent import decide_next_action, gemini_provider_for_user
from app.services.queue import get_queue


router = APIRouter(prefix="/chats", tags=["chats"])


@router.get("", response_model=list[ChatOut])
def list_chats(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[Chat]:
    return db.scalars(select(Chat).where(Chat.user_id == user.id).order_by(Chat.updated_at.desc())).all()


@router.post("", response_model=ChatOut)
def create_chat(payload: ChatCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> Chat:
    chat = Chat(user_id=user.id, title=payload.title or "New chat")
    db.add(chat)
    state = _state_for(db, user)
    db.flush()
    state.active_chat_id = chat.id
    db.commit()
    db.refresh(chat)
    return chat


@router.post("/{chat_id}/activate", response_model=ChatOut)
def activate_chat(chat_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> Chat:
    chat = _chat_for(db, user, chat_id)
    state = _state_for(db, user)
    state.active_chat_id = chat.id
    db.commit()
    return chat


@router.get("/{chat_id}/messages", response_model=list[MessageOut])
def messages(chat_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[Message]:
    _chat_for(db, user, chat_id)
    return db.scalars(select(Message).where(Message.chat_id == chat_id).order_by(Message.created_at)).all()


@router.post("/{chat_id}/messages", response_model=ChatReply)
def send_message(
    chat_id: str,
    payload: MessageCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ChatReply:
    chat = _chat_for(db, user, chat_id)
    state = _state_for(db, user)
    latest_job = _latest_generation_job(db, chat.id, user.id)
    calibration = _latest_calibration(db, user.id, state.genre_id or (latest_job.genre if latest_job else ""))
    history = _chat_history(db, chat.id)
    provider = gemini_provider_for_user(db, user.id)
    feedback = _feedback_for_job(db, user.id, latest_job.id if latest_job else "")
    user_message = Message(chat_id=chat.id, role="user", content=payload.content)
    db.add(user_message)
    decision = decide_next_action(
        payload.content,
        state.genre_id or (latest_job.genre if latest_job else "scary_stories"),
        chat_history=[*history, {"role": "user", "content": payload.content}],
        latest_job=_job_context(latest_job),
        calibration=_calibration_context(calibration),
        feedback=feedback,
        provider=provider,
        require_provider=True,
    )
    metadata = {"ai_master_decision": decision}
    job_id: str | None = None
    if decision["intent"] in {"generate_video", "edit_video"} and not decision.get("needs_clarification"):
        parent_job = latest_job if decision["intent"] == "edit_video" else None
        settings = _settings_for_decision(decision, calibration, parent_job)
        genre_id = parent_job.genre if parent_job else decision.get("genre") or state.genre_id or "scary_stories"
        topic = _job_topic_for_decision(decision, parent_job)
        contracts = build_agent_contracts(settings, genre_id=genre_id, duration=int(settings["duration"]))
        job = VideoJob(
            user_id=user.id,
            chat_id=chat.id,
            status="queued",
            topic=topic,
            genre=genre_id,
            duration=int(settings["duration"]),
            notes=decision.get("notes", ""),
            settings=settings,
            parent_job_id=parent_job.id if parent_job else "",
            job_type="remake" if parent_job else "generation",
            planned_agents=contracts,
        )
        db.add(job)
        db.flush()
        job_id = job.id
        metadata.update(
            {
                "job_id": job.id,
                "settings": settings,
                "parent_job_id": job.parent_job_id,
                "target_agent": decision.get("target_agent", ""),
                "style_profile": settings.get("style_profile", {}),
                "planned_agents": contracts,
            }
        )
        reply_text = decision.get("reply_text") or f"I queued one video for: {topic}"
    elif decision.get("needs_clarification"):
        reply_text = decision.get("reply_text") or "Tell me one more concrete detail for the video topic, like place, person, time, or exact incident."
    else:
        reply_text = decision.get("reply_text") or "Tell me the video idea and I will turn it into a grounded short."
    assistant = Message(chat_id=chat.id, role="assistant", content=reply_text, message_metadata=metadata)
    db.add(assistant)
    db.commit()
    db.refresh(assistant)
    if job_id:
        _enqueue_job(job_id)
    return ChatReply(message=MessageOut.from_orm(assistant), job_id=job_id)


def _chat_for(db: Session, user: User, chat_id: str) -> Chat:
    chat = db.get(Chat, chat_id)
    if chat is None or chat.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chat not found")
    return chat


def _state_for(db: Session, user: User) -> OnboardingState:
    state = db.get(OnboardingState, user.id)
    if state is None:
        state = OnboardingState(user_id=user.id)
        db.add(state)
        db.flush()
    return state


def _enqueue_job(job_id: str) -> None:
    try:
        get_queue().enqueue("app.jobs.run_video_job", job_id)
    except Exception:
        return


def _chat_history(db: Session, chat_id: str) -> list[dict]:
    rows = db.scalars(select(Message).where(Message.chat_id == chat_id).order_by(Message.created_at)).all()
    return [{"role": row.role, "content": row.content} for row in rows[-12:]]


def _latest_generation_job(db: Session, chat_id: str, user_id: int) -> VideoJob | None:
    return db.scalar(
        select(VideoJob)
        .where(
            VideoJob.chat_id == chat_id,
            VideoJob.user_id == user_id,
            VideoJob.job_type != "calibration_sample",
        )
        .order_by(VideoJob.created_at.desc())
    )


def _latest_calibration(db: Session, user_id: int, genre_id: str) -> GenreCalibration | None:
    query = select(GenreCalibration).where(GenreCalibration.user_id == user_id)
    if genre_id:
        query = query.where(GenreCalibration.genre_id == genre_id)
    return db.scalar(query.order_by(GenreCalibration.created_at.desc()))


def _feedback_for_job(db: Session, user_id: int, job_id: str) -> list[dict]:
    if not job_id:
        return []
    rows = db.scalars(
        select(GenerationFeedback)
        .where(GenerationFeedback.user_id == user_id, GenerationFeedback.job_id == job_id)
        .order_by(GenerationFeedback.created_at.desc())
    ).all()
    return [{"issue_types": row.issue_types, "notes": row.notes} for row in rows[:5]]


def _job_context(job: VideoJob | None) -> dict:
    if job is None:
        return {}
    return {
        "id": job.id,
        "topic": job.topic,
        "genre": job.genre,
        "duration": job.duration,
        "notes": job.notes,
        "settings": job.settings or {},
        "status": job.status,
        "parent_job_id": job.parent_job_id,
    }


def _calibration_context(calibration: GenreCalibration | None) -> dict:
    if calibration is None:
        return {}
    return {
        "genre_id": calibration.genre_id,
        "user_intent": calibration.user_intent,
        "preferred_video_id": calibration.preferred_video_id,
        "why_chosen": calibration.why_chosen,
        "improvement_notes": calibration.improvement_notes,
        "preferred_config": calibration.preferred_config or {},
        "style_profile": (calibration.preferred_config or {}).get("style_profile", {}),
    }


def _settings_for_decision(decision: dict, calibration: GenreCalibration | None, parent_job: VideoJob | None) -> dict:
    if parent_job:
        base = dict(parent_job.settings or {})
    else:
        base = dict((calibration.preferred_config if calibration else {}) or {})
        base.pop("sample_index", None)
    if decision.get("style_profile"):
        base["style_profile"] = decision["style_profile"]
    elif "style_profile" not in base and calibration and calibration.preferred_config:
        base["style_profile"] = calibration.preferred_config.get("style_profile", {})
    source_prompt = decision.get("source_prompt") or decision.get("topic") or base.get("source_prompt") or ""
    if source_prompt:
        base["source_prompt"] = source_prompt
    base.update(decision.get("settings_patch") or {})
    base["settings_patch"] = decision.get("settings_patch") or {}
    base["agent_instructions"] = _merge_agent_instructions(base.get("agent_instructions", {}), decision.get("agent_instructions", {}))
    return normalize_generation_settings(base)


def _job_topic_for_decision(decision: dict, parent_job: VideoJob | None) -> str:
    if parent_job:
        return decision.get("topic") or parent_job.topic
    return decision.get("topic") or decision.get("source_prompt") or "grounded short video"


def _merge_agent_instructions(*items: dict) -> dict[str, str]:
    merged: dict[str, str] = {}
    for item in items:
        for key, value in dict(item or {}).items():
            text = str(value or "").strip()
            if not text:
                continue
            merged[key] = f"{merged[key]}\n{text}".strip() if key in merged else text
    return merged
