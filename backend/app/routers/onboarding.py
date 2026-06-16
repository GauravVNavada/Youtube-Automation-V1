from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.dependencies import get_current_user
from app.jobs import run_video_job
from app.models import Chat, GenreCalibration, OnboardingState, User, VideoJob, utc_now
from app.schemas import (
    ApiKeyIn,
    ApiKeyStatusOut,
    ApiSetupOut,
    CalibrationCompleteIn,
    CalibrationOut,
    CalibrationStartIn,
    GenreIntentIn,
    GenreOut,
    JobOut,
    OnboardingStateOut,
    ResetFlowOut,
)
from app.services.api_keys import api_setup_complete, list_key_statuses, llm_options, save_api_key
from app.services.generation_settings import normalize_generation_settings
from app.services.queue import get_calibration_queue
from pipeline.agents.master_agent import build_agent_contracts, generation_constraints


router = APIRouter(prefix="/onboarding", tags=["onboarding"])


@router.get("", response_model=OnboardingStateOut)
def get_onboarding(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> OnboardingStateOut:
    state = _get_or_create_state(db, user.id)
    return _state_out(state)


@router.post("/reset", response_model=ResetFlowOut)
def reset_chat_flow(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> ResetFlowOut:
    state = _get_or_create_state(db, user.id)
    statuses = list_key_statuses(db, user.id)
    complete, _ = api_setup_complete(statuses)
    chat = Chat(user_id=user.id, title="New chat")
    db.add(chat)
    db.flush()
    state.api_setup_complete = complete
    state.genre_id = ""
    state.user_intent = ""
    state.calibration_status = "not_started"
    state.selected_sample_job_id = ""
    state.active_chat_id = chat.id
    state.completed_at = None
    state.step = "genre_intent" if complete else "api_setup"
    state.updated_at = utc_now()
    db.commit()
    db.refresh(state)
    db.refresh(chat)
    return ResetFlowOut(state=_state_out(state), chat=chat)


@router.get("/api-keys", response_model=ApiSetupOut)
def get_api_keys(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> ApiSetupOut:
    statuses = list_key_statuses(db, user.id)
    complete, required = api_setup_complete(statuses)
    state = _get_or_create_state(db, user.id)
    state.api_setup_complete = complete
    state.step = _next_step(state)
    state.updated_at = utc_now()
    db.commit()
    return ApiSetupOut(
        keys=[ApiKeyStatusOut(**item) for item in statuses],
        complete=complete,
        required=required,
        llm_options=llm_options(),
    )


@router.post("/api-keys", response_model=ApiSetupOut)
def upsert_api_key(
    payload: ApiKeyIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ApiSetupOut:
    try:
        save_api_key(db, user.id, payload.provider, payload.value, payload.model)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return get_api_keys(user, db)


@router.get("/genres", response_model=list[GenreOut])
def list_genres(user: User = Depends(get_current_user)) -> list[GenreOut]:
    root = Path(get_settings().pipeline_root)
    genre_dir = root / "data" / "genres"
    genres: list[GenreOut] = []
    for path in sorted(genre_dir.glob("*.yaml")):
        data = _parse_simple_yaml(path.read_text(encoding="utf-8"))
        genres.append(
            GenreOut(
                genre_id=str(data.get("genre_id", path.stem)),
                display_name=str(data.get("display_name", path.stem.replace("_", " ").title())),
                tone=str(data.get("tone", "")),
                word_count_min=int(data.get("word_count_min", 80)),
                word_count_max=int(data.get("word_count_max", 130)),
            )
        )
    return genres


@router.post("/genre-intent", response_model=OnboardingStateOut)
def save_genre_intent(
    payload: GenreIntentIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> OnboardingStateOut:
    state = _get_or_create_state(db, user.id)
    state.genre_id = payload.genre_id
    state.user_intent = payload.user_intent
    state.calibration_status = "not_started"
    state.step = "calibration"
    state.updated_at = utc_now()
    chat = _get_or_create_flow_chat(db, user.id)
    if chat.title == "New chat":
        chat.title = _title_from_text(payload.user_intent)
    chat.updated_at = utc_now()
    db.commit()
    return _state_out(state)


@router.post("/calibration/start", response_model=list[JobOut])
def start_calibration(
    payload: CalibrationStartIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[VideoJob]:
    state = _get_or_create_state(db, user.id)
    state.genre_id = payload.genre_id
    state.user_intent = payload.user_intent
    state.calibration_status = "running"
    state.step = "calibration"
    state.updated_at = utc_now()
    chat = _get_or_create_flow_chat(db, user.id)
    base_settings = normalize_generation_settings(payload.settings.model_dump(), text=payload.user_intent, prefer_text=True)
    base_settings["image_count"] = max(base_settings.get("image_count", 8), 8)
    existing_jobs = list(
        db.scalars(
            select(VideoJob)
            .where(
                VideoJob.user_id == user.id,
                VideoJob.chat_id == chat.id,
                VideoJob.job_type == "calibration_sample",
                VideoJob.genre == payload.genre_id,
                VideoJob.duration == base_settings["duration"],
                VideoJob.topic.contains(payload.user_intent),
            )
            .order_by(VideoJob.created_at.desc())
            .limit(3)
        )
    )
    if len(existing_jobs) >= 3:
        if not any(job.status == "failed" for job in existing_jobs):
            db.commit()
            return existing_jobs

    jobs: list[VideoJob] = []
    for index in range(1, 4):
        settings = dict(base_settings)
        contracts = build_agent_contracts(settings, genre_id=payload.genre_id, duration=int(settings["duration"]))
        topic = f"Calibration sample {index}: {payload.user_intent}"
        job = VideoJob(
            user_id=user.id,
            chat_id=chat.id,
            topic=topic,
            genre=payload.genre_id,
            duration=settings["duration"],
            notes=_build_calibration_notes(payload.user_intent, index, payload.genre_id, settings),
            settings=settings,
            job_type="calibration_sample",
            planned_agents=contracts,
        )
        db.add(job)
        db.flush()
        jobs.append(job)
    db.commit()
    for index, job in enumerate(jobs, start=1):
        get_calibration_queue(index).enqueue(run_video_job, job.id, job_timeout=1200)
    return jobs


@router.post("/calibration/complete", response_model=CalibrationOut)
def complete_calibration(
    payload: CalibrationCompleteIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> GenreCalibration:
    job = db.get(VideoJob, payload.preferred_video_id)
    if not job or job.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Calibration job not found")
    state = _get_or_create_state(db, user.id)
    script_text = _read_script_text(job.run_dir)
    calibration = db.scalar(
        select(GenreCalibration).where(
            GenreCalibration.user_id == user.id,
            GenreCalibration.genre_id == job.genre,
        )
    )
    if not calibration:
        calibration = GenreCalibration(user_id=user.id, genre_id=job.genre)
        db.add(calibration)
    calibration.user_intent = state.user_intent or job.topic
    calibration.preferred_video_id = job.id
    calibration.preferred_script = script_text
    calibration.why_chosen = payload.why_chosen
    calibration.improvement_notes = payload.improvement_notes
    calibration.preferred_config = job.settings or {}
    calibration.updated_at = utc_now()
    state.selected_sample_job_id = job.id
    state.calibration_status = "completed"
    state.step = "complete"
    state.completed_at = utc_now()
    state.updated_at = utc_now()
    db.commit()
    db.refresh(calibration)
    return calibration


def _get_or_create_state(db: Session, user_id: int) -> OnboardingState:
    state = db.get(OnboardingState, user_id)
    if state:
        return state
    state = OnboardingState(user_id=user_id, step="api_setup")
    db.add(state)
    db.commit()
    db.refresh(state)
    return state


def _state_out(state: OnboardingState) -> OnboardingStateOut:
    return OnboardingStateOut(
        step=state.step,
        api_setup_complete=state.api_setup_complete,
        genre_id=state.genre_id,
        user_intent=state.user_intent,
        calibration_status=state.calibration_status,
        selected_sample_job_id=state.selected_sample_job_id,
        active_chat_id=state.active_chat_id,
        completed=bool(state.completed_at),
    )


def _next_step(state: OnboardingState) -> str:
    if not state.api_setup_complete:
        return "api_setup"
    if not state.genre_id or not state.user_intent:
        return "genre_intent"
    if state.calibration_status != "completed":
        return "calibration"
    return "complete"


def _get_or_create_flow_chat(db: Session, user_id: int) -> Chat:
    state = _get_or_create_state(db, user_id)
    chat = db.get(Chat, state.active_chat_id) if state.active_chat_id else None
    if chat and chat.user_id == user_id:
        return chat
    chat = db.scalar(select(Chat).where(Chat.user_id == user_id).order_by(Chat.updated_at.desc()))
    if chat:
        state.active_chat_id = chat.id
        return chat
    chat = Chat(user_id=user_id, title="New chat")
    db.add(chat)
    db.flush()
    state.active_chat_id = chat.id
    return chat


def _build_calibration_notes(user_intent: str, index: int, genre_id: str, settings: dict[str, Any]) -> str:
    styles = {
        1: "Style sample A: slow, clear, safe baseline.",
        2: "Style sample B: stronger emotion and sharper hook.",
        3: "Style sample C: more cinematic pacing and bigger reveal.",
    }
    constraints = generation_constraints(settings, genre_id=genre_id, duration=int(settings["duration"]))
    return (
        f"{styles[index]}\n"
        f"User intent: {user_intent}\n"
        f"Master constraints JSON: {json.dumps(constraints, ensure_ascii=True)}\n"
        "Pipeline order: Master decides route and constraints; Script writes within constraints; Script self-checks; "
        "Validation checks; invalid scripts auto-repair; only then assets, audio, captions, and render continue."
    )


def _title_from_text(text: str) -> str:
    title = " ".join(text.strip().split())
    return title[:80] if title else "New chat"


def _read_script_text(run_dir: str) -> str:
    if not run_dir:
        return ""
    output_path = Path(run_dir) / "logs" / "script_agent" / "output.json"
    if not output_path.exists():
        return ""
    try:
        data = json.loads(output_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return ""
    return str(data.get("narration") or "")


def _parse_simple_yaml(text: str) -> dict[str, Any]:
    result: dict[str, Any] = {}
    current_key: str | None = None
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line.startswith("  - ") and current_key:
            result.setdefault(current_key, []).append(line[4:].strip().strip('"').strip("'"))
            continue
        if ":" in line and not line.startswith(" "):
            key, value = line.split(":", 1)
            current_key = key.strip()
            value = value.strip().strip('"').strip("'")
            result[current_key] = value if value else []
    return result
