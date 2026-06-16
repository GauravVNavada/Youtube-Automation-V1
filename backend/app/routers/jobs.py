from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.dependencies import get_current_user
from app.models import User, VideoJob
from app.schemas import AgentProgressOut, JobLogsOut, JobOut, JobProgressOut


router = APIRouter(prefix="/jobs", tags=["jobs"])

AGENT_ORDER = [
    ("topic_discovery_agent", "Discovery"),
    ("research_agent", "Research"),
    ("script_agent", "Script"),
    ("validation_agent", "Validation"),
    ("asset_agent", "Assets"),
    ("audio_agent", "Voice"),
    ("caption_agent", "Captions"),
    ("render_agent", "Render"),
    ("thumbnail_agent", "Thumbnail"),
]

ERROR_STAGE_TO_AGENT = {
    "topic_discovery_agent": "topic_discovery_agent",
    "research_agent": "research_agent",
    "script_agent": "script_agent",
    "validate_script": "validation_agent",
    "validate_script_result": "validation_agent",
    "asset_agent": "asset_agent",
    "validate_assets": "validation_agent",
    "validate_assets_result": "validation_agent",
    "audio_agent": "audio_agent",
    "validate_audio": "validation_agent",
    "validate_audio_result": "validation_agent",
    "caption_agent": "caption_agent",
    "validate_captions": "validation_agent",
    "validate_captions_result": "validation_agent",
    "render_agent": "render_agent",
    "validate_render": "validation_agent",
    "validate_render_result": "validation_agent",
    "thumbnail_agent": "thumbnail_agent",
}


@router.get("", response_model=list[JobOut])
def list_jobs(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[JobOut]:
    jobs = db.scalars(
        select(VideoJob)
        .where(VideoJob.user_id == user.id)
        .order_by(VideoJob.created_at.desc())
    )
    return [_to_job_out(job) for job in jobs]


@router.get("/{job_id}", response_model=JobOut)
def get_job(job_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> JobOut:
    return _to_job_out(_get_owned_job(db, job_id, user.id))


@router.get("/{job_id}/progress", response_model=JobProgressOut)
def get_job_progress(
    job_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> JobProgressOut:
    return _build_progress(_get_owned_job(db, job_id, user.id))


@router.get("/{job_id}/logs", response_model=JobLogsOut)
def get_job_logs(
    job_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> JobLogsOut:
    job = _get_owned_job(db, job_id, user.id)
    run_dir = Path(job.run_dir) if job.run_dir else None
    events: list[dict[str, Any]] = []
    if run_dir:
        for name, _ in AGENT_ORDER:
            for event in _read_events(run_dir / "logs" / name / "events.log", limit=500):
                event.setdefault("module", name)
                events.append(event)
        for event in _read_events(run_dir / "errors" / "events.log", limit=200):
            event.setdefault("module", "errors")
            events.append(event)
    events = sorted(events, key=lambda item: str(item.get("ts", "")))
    return JobLogsOut(
        job_id=job.id,
        status=job.status,
        run_dir=job.run_dir,
        events=events,
        stdout=job.stdout[-20000:],
        stderr=job.stderr[-20000:],
        error_message=job.error_message,
    )


@router.get("/{job_id}/download")
def download_job_video(
    job_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> FileResponse:
    job = _get_owned_job(db, job_id, user.id)
    video_path = Path(job.video_path)
    if job.status != "succeeded" or not video_path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Video is not available")
    return FileResponse(str(video_path), media_type="video/mp4", filename=f"{job.id}.mp4")


@router.get("/{job_id}/preview")
def preview_job_video(
    job_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> FileResponse:
    job = _get_owned_job(db, job_id, user.id)
    video_path = Path(job.video_path)
    if job.status != "succeeded" or not video_path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Video is not available")
    return FileResponse(str(video_path), media_type="video/mp4")


@router.get("/{job_id}/thumbnails/{kind}")
def get_job_thumbnail(
    job_id: str,
    kind: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> FileResponse:
    job = _get_owned_job(db, job_id, user.id)
    path = _job_artifact_path(job, {"shorts": "output/thumbnails/shorts_cover.jpg", "youtube": "output/thumbnails/youtube_thumb.jpg"}.get(kind, ""))
    if job.status != "succeeded" or not path or not path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Thumbnail is not available")
    filename = f"{job.id}_{kind}_thumbnail.jpg"
    return FileResponse(str(path), media_type="image/jpeg", filename=filename)


@router.get("/{job_id}/render-plan")
def get_job_render_plan(
    job_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> FileResponse:
    job = _get_owned_job(db, job_id, user.id)
    path = _job_artifact_path(job, "output/render_plan.json")
    if job.status != "succeeded" or not path or not path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Render plan is not available")
    return FileResponse(str(path), media_type="application/json", filename=f"{job.id}_render_plan.json")


def _get_owned_job(db: Session, job_id: str, user_id: int) -> VideoJob:
    job = db.get(VideoJob, job_id)
    if not job or job.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    return job


def _to_job_out(job: VideoJob) -> JobOut:
    download_url = f"/api/jobs/{job.id}/download" if job.status == "succeeded" and job.video_path else None
    preview_url = f"/api/jobs/{job.id}/preview" if job.status == "succeeded" and job.video_path else None
    shorts_cover_url = _artifact_url_if_exists(job, "output/thumbnails/shorts_cover.jpg", f"/api/jobs/{job.id}/thumbnails/shorts")
    youtube_thumbnail_url = _artifact_url_if_exists(job, "output/thumbnails/youtube_thumb.jpg", f"/api/jobs/{job.id}/thumbnails/youtube")
    render_plan_url = _artifact_url_if_exists(job, "output/render_plan.json", f"/api/jobs/{job.id}/render-plan")
    return JobOut.model_validate(job).model_copy(
        update={
            "download_url": download_url,
            "preview_url": preview_url,
            "shorts_cover_url": shorts_cover_url,
            "youtube_thumbnail_url": youtube_thumbnail_url,
            "render_plan_url": render_plan_url,
        }
    )


def _artifact_url_if_exists(job: VideoJob, relative_path: str, url: str) -> str | None:
    path = _job_artifact_path(job, relative_path)
    return url if job.status == "succeeded" and path and path.exists() else None


def _job_artifact_path(job: VideoJob, relative_path: str) -> Path | None:
    if not relative_path or not job.run_dir:
        return None
    root = Path(job.run_dir).resolve()
    path = (root / relative_path).resolve()
    try:
        path.relative_to(root)
    except ValueError:
        return None
    return path


def _build_progress(job: VideoJob) -> JobProgressOut:
    run_dir = Path(job.run_dir) if job.run_dir else None
    agent_progress: list[AgentProgressOut] = []
    feed: list[dict[str, Any]] = []
    failed_slot = ""

    for name, label in AGENT_ORDER:
        log_dir = run_dir / "logs" / name if run_dir else None
        events = _read_events(log_dir / "events.log" if log_dir else None)
        feed.extend(events[-3:])
        output_exists = bool(log_dir and (log_dir / "output.json").exists())
        input_exists = bool(log_dir and (log_dir / "input.json").exists())
        status_name = _agent_status(job.status, output_exists, input_exists, bool(events))
        message = str(events[-1].get("message", "")) if events else ""
        agent_progress.append(
            AgentProgressOut(
                name=name,
                label=label,
                status=status_name,
                message=message,
                events=events[-3:],
            )
        )

    error_events = _read_events(run_dir / "errors" / "events.log" if run_dir else None)
    if job.status == "failed":
        failed_slot = _mark_failed_agent(agent_progress, error_events)

    feed.extend(error_events[-3:])
    feed = sorted(feed, key=lambda item: str(item.get("ts", "")))[-10:]

    completed = sum(1 for item in agent_progress if item.status == "complete")
    if job.status == "succeeded":
        percent = 100
        current_agent = ""
    elif job.status == "failed":
        percent = max(5, round((completed / len(agent_progress)) * 100))
        current_agent = failed_slot
    else:
        percent = max(5 if job.status == "running" else 0, round((completed / len(agent_progress)) * 100))
        current_agent = _current_agent(agent_progress)

    return JobProgressOut(
        job_id=job.id,
        status=job.status,
        job_type=job.job_type,
        topic=job.topic,
        percent=percent,
        current_agent=current_agent,
        agents=agent_progress,
        events=feed,
        error_message=job.error_message,
    )


def _agent_status(job_status: str, output_exists: bool, input_exists: bool, has_events: bool) -> str:
    if output_exists or job_status == "succeeded":
        return "complete"
    if job_status == "queued":
        return "pending"
    if input_exists or has_events:
        return "running"
    return "pending"


def _mark_failed_agent(agents: list[AgentProgressOut], error_events: list[dict[str, Any]] | None = None) -> str:
    failed_agent = _failed_agent_from_errors(error_events or [])
    if failed_agent:
        for agent in agents:
            if agent.name == failed_agent:
                agent.status = "failed"
                return agent.name
    for agent in agents:
        if agent.status == "running":
            agent.status = "failed"
            return agent.name
    for agent in agents:
        if agent.status == "pending":
            agent.status = "failed"
            return agent.name
    return agents[-1].name if agents else ""


def _failed_agent_from_errors(error_events: list[dict[str, Any]]) -> str:
    for event in reversed(error_events):
        stage = str(event.get("stage") or "")
        agent = ERROR_STAGE_TO_AGENT.get(stage)
        if agent:
            return agent
    return ""


def _current_agent(agents: list[AgentProgressOut]) -> str:
    for agent in agents:
        if agent.status == "running":
            return agent.name
    for agent in agents:
        if agent.status == "pending":
            return agent.name
    return ""


def _read_events(path: Path | None, limit: int = 20) -> list[dict[str, Any]]:
    if not path or not path.exists():
        return []
    events: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines()[-limit:]:
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            event = {"ts": "", "message": line.strip()}
        events.append(event if isinstance(event, dict) else {"ts": "", "message": str(event)})
    return events
