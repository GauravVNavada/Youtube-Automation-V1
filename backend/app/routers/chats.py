from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.dependencies import get_current_user
from app.models import Chat, Message, OnboardingState, User, VideoJob
from app.schemas import ChatCreate, ChatOut, ChatReply, MessageCreate, MessageOut
from app.services.agent_contracts import build_agent_contracts
from app.services.generation_settings import normalize_generation_settings
from app.services.master_agent import decide_next_action
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
    user_message = Message(chat_id=chat.id, role="user", content=payload.content)
    db.add(user_message)
    state = _state_for(db, user)
    decision = decide_next_action(payload.content, state.genre_id or "scary_stories")
    metadata = {"ai_master_decision": decision}
    job_id: str | None = None
    if decision["intent"] == "generate_video" and not decision.get("needs_clarification"):
        settings = normalize_generation_settings({})
        contracts = build_agent_contracts(settings, genre_id=decision["genre"], duration=int(settings["duration"]))
        job = VideoJob(
            user_id=user.id,
            chat_id=chat.id,
            status="queued",
            topic=decision["topic"],
            genre=decision["genre"],
            duration=int(settings["duration"]),
            notes=decision.get("notes", ""),
            settings=settings,
            planned_agents=contracts,
        )
        db.add(job)
        db.flush()
        job_id = job.id
        metadata.update({"job_id": job.id, "settings": settings, "planned_agents": contracts})
        reply_text = f"I queued a grounded short for: {decision['topic']}"
    elif decision.get("needs_clarification"):
        reply_text = "Tell me one more concrete detail for the video topic, like place, person, time, or exact incident."
    else:
        reply_text = "Tell me the video idea and I will turn it into a grounded short."
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
