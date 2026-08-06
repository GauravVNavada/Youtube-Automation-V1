from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db, get_static_db
from app.dependencies import require_active_entitlement
from app.models import Chat, Genre, GenreCalibration, Message, OnboardingState, ReferenceExample, User, VideoJob
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
def onboarding_state(user: User = Depends(require_active_entitlement), db: Session = Depends(get_db)) -> OnboardingState:
    return _state_for(db, user)


@router.post("/reset", response_model=ResetFlowOut)
def reset_onboarding(user: User = Depends(require_active_entitlement), db: Session = Depends(get_db)) -> ResetFlowOut:
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
def api_keys(user: User = Depends(require_active_entitlement), db: Session = Depends(get_db)) -> ApiSetupOut:
    statuses = api_key_statuses(db, user.id)
    required = {item["provider"]: item["status"] == "configured" for item in statuses}
    return ApiSetupOut(required=required, statuses=statuses, llm_options=llm_options())


@router.post("/api-keys", response_model=ApiSetupOut)
def save_api_key(payload: ApiKeyIn, user: User = Depends(require_active_entitlement), db: Session = Depends(get_db)) -> ApiSetupOut:
    save_user_api_key(db, user.id, payload.provider, payload.value, payload.model)
    state = _state_for(db, user)
    state.api_setup_complete = True
    state.step = "genre"
    db.commit()
    return api_keys(user, db)


@router.get("/genres", response_model=list[GenreOut])
def genres(user: User = Depends(require_active_entitlement), static_db: Session = Depends(get_static_db)) -> list[GenreOut]:
    rows = static_db.scalars(
        select(Genre).where(Genre.is_active.is_(True)).order_by(Genre.recommended_score.desc(), Genre.display_name)
    ).all()
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
    user: User = Depends(require_active_entitlement),
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
    user: User = Depends(require_active_entitlement),
    db: Session = Depends(get_db),
    static_db: Session = Depends(get_static_db),
) -> list[dict]:
    state = _state_for(db, user)
    state.genre_id = payload.genre_id
    state.user_intent = payload.user_intent
    state.calibration_status = "running"
    state.step = "calibration"
    chat = _active_chat(db, user, state)
    if _should_rename_chat(chat):
        chat.title = _chat_title(payload.user_intent)
    settings = normalize_generation_settings(payload.settings.model_dump())
    genre = static_db.get(Genre, payload.genre_id)
    shared_context = _prepared_calibration_context(static_db, genre, payload.genre_id)
    provider = gemini_provider_for_user(db, user.id)
    style_profiles = build_style_profiles(
        payload.user_intent,
        payload.genre_id,
        genre.tone if genre else "",
        provider=provider,
    )
    jobs: list[VideoJob] = []
    calibration_batch_id = f"{user.id}:{chat.id}:{datetime.now(timezone.utc).isoformat()}"
    for index, profile in enumerate(style_profiles[:3], start=1):
        profile_dict = profile.to_dict()
        job_settings = normalize_generation_settings(
            {
                **settings,
                **shared_context,
                "calibration_batch_id": calibration_batch_id,
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
    db.flush()
    job_ids = [job.id for job in jobs]
    db.add(
        Message(
            chat_id=chat.id,
            role="user",
            content=payload.user_intent,
            message_metadata={
                "kind": "calibration_prompt",
                "genre_id": payload.genre_id,
                "calibration_batch_id": calibration_batch_id,
            },
        )
    )
    db.add(
        Message(
            chat_id=chat.id,
            role="assistant",
            content="I am making three style videos for you. Each one has its own pipeline, and you can pick the one that feels best when they finish.",
            message_metadata={
                "kind": "calibration_started",
                "genre_id": payload.genre_id,
                "calibration_batch_id": calibration_batch_id,
                "job_ids": job_ids,
            },
        )
    )
    chat.updated_at = datetime.now(timezone.utc)
    db.commit()
    for job in jobs:
        db.refresh(job)
        _enqueue_job(job.id, calibration_index=int(job.settings.get("sample_index", 1)))
    return [_job_dict(job) for job in jobs]


@router.post("/calibration/complete", response_model=CalibrationOut)
def complete_calibration(
    payload: CalibrationCompleteIn,
    user: User = Depends(require_active_entitlement),
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


def _should_rename_chat(chat: Chat) -> bool:
    return not chat.title.strip() or chat.title.strip().lower() in {"new chat", "studio"}


def _chat_title(content: str) -> str:
    words = " ".join(str(content or "").strip().split())
    if not words:
        return "New chat"
    return words[:57].rstrip(" .,!?") + ("..." if len(words) > 57 else "")


def _prepared_calibration_context(static_db: Session, genre: Genre | None, genre_id: str) -> dict:
    context: dict = {}
    if genre is not None:
        context["prepared_genre_config"] = {
            "genre_id": genre.id,
            "display_name": genre.display_name,
            "word_count_min": genre.word_count_min,
            "word_count_max": genre.word_count_max,
            "tone": genre.tone,
            "layout": genre.layout,
            "caption_preset": genre.caption_preset,
            "voice_rate": genre.voice_rate,
            "music_mood": genre.music_mood,
            "hook_patterns": genre.hook_patterns or [],
            "banned_phrases": genre.banned_phrases or [],
            "visual_style": genre.visual_style or {},
            "topic_rules": genre.topic_rules or [],
            "script_profile": (genre.metadata_json or {}).get("script_profile", genre.metadata_json or {}),
        }
    references = static_db.scalars(
        select(ReferenceExample)
        .where(ReferenceExample.genre_id == genre_id, ReferenceExample.usable_as_few_shot.is_(True))
        .order_by(ReferenceExample.overall_score.desc(), ReferenceExample.id.asc())
        .limit(40)
    ).all()
    if references:
        context["prepared_reference_scripts"] = [_reference_example_dict(row) for row in references]
    return context


def _reference_example_dict(row: ReferenceExample) -> dict:
    metrics = row.metrics or {}
    analysis = row.analysis or {}
    return {
        "genre_id": row.genre_id,
        "title": row.title,
        "source_url": row.source_url,
        "channel_name": row.source_label,
        "views": metrics.get("views", 0) if isinstance(metrics, dict) else 0,
        "likes": metrics.get("likes", 0) if isinstance(metrics, dict) else 0,
        "comments": metrics.get("comments", 0) if isinstance(metrics, dict) else 0,
        "upload_date": str(metrics.get("upload_date", "") if isinstance(metrics, dict) else ""),
        "duration_sec": row.duration_sec,
        "description_first_line": row.description,
        "hashtags": row.tags or [],
        "script": row.script,
        "full_script": row.script,
        "word_count": row.word_count,
        "overall_score": row.overall_score,
        "notes": row.notes,
        "facts": row.facts or [],
        "hook_first_sentence": analysis.get("hook_first_sentence", "") if isinstance(analysis, dict) else "",
        "hook_type": analysis.get("hook_type", "") if isinstance(analysis, dict) else "",
        "hook_emotional_trigger": analysis.get("hook_emotional_trigger", "") if isinstance(analysis, dict) else "",
        "has_twist_reveal": analysis.get("has_twist_reveal", False) if isinstance(analysis, dict) else False,
        "twist_line": analysis.get("twist_line", "") if isinstance(analysis, dict) else "",
        "ending_type": analysis.get("ending_type", "") if isinstance(analysis, dict) else "",
        "last_sentence": analysis.get("last_sentence", "") if isinstance(analysis, dict) else "",
        "power_words": _string_list(analysis.get("power_words", []) if isinstance(analysis, dict) else []),
        "emphasis_words": _string_list(analysis.get("emphasis_words", []) if isinstance(analysis, dict) else []),
        "sensory_language_used": analysis.get("sensory_language_used", "") if isinstance(analysis, dict) else "",
        "retention_hook": analysis.get("retention_hook", "") if isinstance(analysis, dict) else "",
        "likely_share_trigger": analysis.get("likely_share_trigger", "") if isinstance(analysis, dict) else "",
        "why_it_worked": analysis.get("why_it_worked", "") if isinstance(analysis, dict) else "",
        "what_to_improve": analysis.get("what_to_improve", "") if isinstance(analysis, dict) else "",
        "source": "prepared_database_reference",
    }


def _string_list(value) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [item.strip() for item in str(value or "").split(",") if item.strip()]
