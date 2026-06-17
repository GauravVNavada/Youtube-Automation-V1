from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.dependencies import get_current_user
from app.models import Chat, Genre, GenreCalibration, OnboardingState, User, VideoJob
from app.schemas import (
    ApiKeyIn,
    ApiSetupOut,
    CalibrationCompleteIn,
    CalibrationOut,
    CalibrationStartIn,
    ChatOut,
    GenreIntentIn,
    GenreOut,
    OnboardingStateOut,
    ResetFlowOut,
)
from app.services.agent_contracts import build_agent_contracts
from app.services.api_keys import api_key_statuses, llm_options, save_user_api_key
from app.services.generation_settings import normalize_generation_settings
from app.services.master_agent import gemini_provider_for_user
from app.services.queue import get_calibration_queue
from desktop_pipeline.style_sampler_agent import build_style_profiles, style_profile_to_notes


router = APIRouter(prefix="/onboarding", tags=["onboarding"])


@router.get("", response_model=OnboardingStateOut)
def onboarding_state(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> OnboardingState:
    return _state_for(db, user)


@router.post("/reset", response_model=ResetFlowOut)
def reset_onboarding(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> ResetFlowOut:
    state = _state_for(db, user)
    state.step = "api_setup"
    state.api_setup_complete = False
    state.genre_id = ""
    state.user_intent = ""
    state.calibration_status = "not_started"
    state.selected_sample_job_id = ""
    state.completed_at = None
    chat = Chat(user_id=user.id, title="New chat")
    db.add(chat)
    db.flush()
    state.active_chat_id = chat.id
    db.commit()
    db.refresh(chat)
    db.refresh(state)
    return ResetFlowOut(chat=ChatOut.from_orm(chat), onboarding=OnboardingStateOut.from_orm(state))


@router.get("/api-keys", response_model=ApiSetupOut)
def api_keys(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> ApiSetupOut:
    statuses = api_key_statuses(db, user.id)
    required = {item["provider"]: item["status"] == "configured" for item in statuses}
    return ApiSetupOut(required=required, statuses=statuses, llm_options=llm_options())


@router.post("/api-keys", response_model=ApiSetupOut)
def save_api_key(payload: ApiKeyIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> ApiSetupOut:
    save_user_api_key(db, user.id, payload.provider, payload.value, payload.model)
    state = _state_for(db, user)
    state.api_setup_complete = True
    state.step = "genre"
    db.commit()
    return api_keys(user, db)


@router.get("/genres", response_model=list[GenreOut])
def genres(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> list[GenreOut]:
    rows = db.scalars(select(Genre).where(Genre.is_active.is_(True)).order_by(Genre.recommended_score.desc(), Genre.display_name)).all()
    return [
        GenreOut(
            genre_id=row.id,
            display_name=row.display_name,
            category=row.category,
            tone=row.tone,
            default_duration_sec=row.default_duration_sec,
            word_count_min=row.word_count_min,
            word_count_max=row.word_count_max,
            recommended_score=row.recommended_score,
        )
        for row in rows
    ]


@router.post("/genre-intent", response_model=OnboardingStateOut)
def save_genre_intent(
    payload: GenreIntentIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> OnboardingState:
    state = _state_for(db, user)
    state.genre_id = payload.genre_id
    state.user_intent = payload.user_intent
    state.step = "calibration"
    db.commit()
    db.refresh(state)
    return state


@router.post("/calibration/start", response_model=list[dict])
def start_calibration(
    payload: CalibrationStartIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict]:
    state = _state_for(db, user)
    state.genre_id = payload.genre_id
    state.user_intent = payload.user_intent
    state.calibration_status = "running"
    state.step = "calibration"
    chat = _active_chat(db, user, state)
    settings = normalize_generation_settings(payload.settings.model_dump())
    genre = db.get(Genre, payload.genre_id)
    provider = gemini_provider_for_user(db, user.id)
    style_profiles = build_style_profiles(
        payload.user_intent,
        payload.genre_id,
        genre.tone if genre else "",
        provider=provider,
    )
    jobs: list[VideoJob] = []
    for index, profile in enumerate(style_profiles[:3], start=1):
        profile_dict = profile.to_dict()
        job_settings = normalize_generation_settings(
            {
                **settings,
                "sample_index": index,
                "source_prompt": payload.user_intent,
                "style_profile": profile_dict,
                "agent_instructions": {
                    "script_agent": profile.script_angle,
                    "asset_agent": profile.visual_style,
                    "audio_agent": profile.audio_style,
                    "caption_agent": profile.caption_style,
                },
            }
        )
        job = VideoJob(
            user_id=user.id,
            chat_id=chat.id,
            topic=f"{payload.user_intent} sample {index}",
            genre=payload.genre_id,
            duration=int(job_settings["duration"]),
            notes=style_profile_to_notes(profile),
            settings=job_settings,
            job_type="calibration_sample",
            planned_agents=build_agent_contracts(job_settings, genre_id=payload.genre_id, duration=int(job_settings["duration"])),
        )
        db.add(job)
        jobs.append(job)
    db.commit()
    for job in jobs:
        db.refresh(job)
        _enqueue_job(job.id, calibration_index=int(job.settings.get("sample_index", 1)))
    return [_job_dict(job) for job in jobs]


@router.post("/calibration/complete", response_model=CalibrationOut)
def complete_calibration(
    payload: CalibrationCompleteIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> GenreCalibration:
    state = _state_for(db, user)
    job = db.get(VideoJob, payload.preferred_video_id)
    calibration = GenreCalibration(
        user_id=user.id,
        genre_id=state.genre_id or (job.genre if job else "scary_stories"),
        user_intent=state.user_intent,
        preferred_video_id=payload.preferred_video_id,
        why_chosen=payload.why_chosen,
        improvement_notes=payload.improvement_notes,
        preferred_config=(job.settings if job else {}),
    )
    db.add(calibration)
    state.selected_sample_job_id = payload.preferred_video_id
    state.calibration_status = "complete"
    state.step = "studio"
    state.completed_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(calibration)
    return calibration


def _state_for(db: Session, user: User) -> OnboardingState:
    state = db.get(OnboardingState, user.id)
    if state is None:
        chat = Chat(user_id=user.id, title="New chat")
        state = OnboardingState(user_id=user.id)
        db.add(chat)
        db.flush()
        state.active_chat_id = chat.id
        db.add(state)
        db.commit()
        db.refresh(state)
    return state


def _active_chat(db: Session, user: User, state: OnboardingState) -> Chat:
    chat = db.get(Chat, state.active_chat_id) if state.active_chat_id else None
    if chat is None or chat.user_id != user.id:
        chat = Chat(user_id=user.id, title="New chat")
        db.add(chat)
        db.flush()
        state.active_chat_id = chat.id
    return chat


def _enqueue_job(job_id: str, calibration_index: int = 1) -> None:
    try:
        queue = get_calibration_queue(calibration_index)
        queue.enqueue("app.jobs.run_video_job", job_id)
    except Exception:
        return


def _job_dict(job: VideoJob) -> dict:
    return {
        "id": job.id,
        "chat_id": job.chat_id,
        "status": job.status,
        "topic": job.topic,
        "genre": job.genre,
        "duration": job.duration,
        "settings": job.settings,
        "job_type": job.job_type,
        "created_at": job.created_at,
    }
