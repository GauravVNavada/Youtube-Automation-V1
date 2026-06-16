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


@router.get("", response_model=list[JobOut])
def list_jobs(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[VideoJob]:
    return _with_urls(db.scalars(select(VideoJob).where(VideoJob.user_id == user.id).order_by(VideoJob.created_at.desc())).all())


@router.get("/{job_id}", response_model=JobOut)
def get_job(job_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> VideoJob:
    return _with_urls([_job_for(db, user, job_id)])[0]


@router.get("/{job_id}/progress", response_model=JobProgressOut)
def job_progress(job_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> JobProgressOut:
    job = _job_for(db, user, job_id)
    events = _load_events(job)
    percent = _percent_for(job.status, events)
    current_agent = _current_agent(job.status, events)
    agents = [
        AgentProgressOut(name=name, label=label, status=_agent_status(name, job.status, current_agent, events))
        for name, label in AGENT_ORDER
    ]
    return JobProgressOut(
        job_id=job.id,
        status=job.status,
        percent=percent,
        current_agent=current_agent,
        agents=agents,
        events=events[-30:],
        error_message=job.error_message,
    )


@router.get("/{job_id}/logs", response_model=JobLogsOut)
def job_logs(job_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> JobLogsOut:
    job = _job_for(db, user, job_id)
    return JobLogsOut(
        job_id=job.id,
        events=_load_events(job),
        stdout=job.stdout,
        stderr=job.stderr,
        error_message=job.error_message,
    )


@router.get("/{job_id}/download")
def download(job_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> FileResponse:
    job = _job_for(db, user, job_id)
    return _file_response(job.video_path, "video/mp4")


@router.get("/{job_id}/preview")
def preview(job_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> FileResponse:
    job = _job_for(db, user, job_id)
    return _file_response(job.video_path, "video/mp4")


@router.get("/{job_id}/shorts-cover")
def shorts_cover(job_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> FileResponse:
    job = _job_for(db, user, job_id)
    return _file_response(_artifact(job, "shorts_cover.jpg"), "image/jpeg")


@router.get("/{job_id}/youtube-thumbnail")
def youtube_thumbnail(job_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> FileResponse:
    job = _job_for(db, user, job_id)
    return _file_response(_artifact(job, "youtube_thumbnail.jpg"), "image/jpeg")


@router.get("/{job_id}/render-plan")
def render_plan(job_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> FileResponse:
    job = _job_for(db, user, job_id)
    return _file_response(_artifact(job, "render_plan.json"), "application/json")


def _job_for(db: Session, user: User, job_id: str) -> VideoJob:
    job = db.get(VideoJob, job_id)
    if job is None or job.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    return job


def _with_urls(jobs: list[VideoJob]) -> list[VideoJob]:
    for job in jobs:
        if job.video_path:
            setattr(job, "download_url", f"/api/jobs/{job.id}/download")
            setattr(job, "preview_url", f"/api/jobs/{job.id}/preview")
        if _artifact(job, "shorts_cover.jpg"):
            setattr(job, "shorts_cover_url", f"/api/jobs/{job.id}/shorts-cover")
        if _artifact(job, "youtube_thumbnail.jpg"):
            setattr(job, "youtube_thumbnail_url", f"/api/jobs/{job.id}/youtube-thumbnail")
        if _artifact(job, "render_plan.json"):
            setattr(job, "render_plan_url", f"/api/jobs/{job.id}/render-plan")
    return jobs


def _load_events(job: VideoJob) -> list[dict[str, Any]]:
    candidates = []
    if job.run_dir:
        candidates.extend(Path(job.run_dir).glob("logs/*.jsonl"))
        candidates.extend(Path(job.run_dir).glob("*.jsonl"))
        candidates.extend(Path(job.run_dir).glob("logs/*/events.log"))
        candidates.extend(Path(job.run_dir).glob("errors/events.log"))
    events: list[dict[str, Any]] = []
    for path in candidates:
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    events.append(json.loads(line))
        except Exception:
            continue
    return events


def _percent_for(status_text: str, events: list[dict[str, Any]]) -> int:
    if status_text == "succeeded":
        return 100
    if status_text == "failed":
        return 100
    if status_text == "queued":
        return 4
    names = [name for name, _ in AGENT_ORDER]
    current = _current_agent(status_text, events)
    return max(8, int(((names.index(current) + 1) / len(names)) * 100)) if current in names else 35


def _current_agent(status_text: str, events: list[dict[str, Any]]) -> str:
    for event in reversed(events):
        name = str(event.get("agent") or event.get("module") or event.get("stage") or "")
        if name in dict(AGENT_ORDER):
            return name
    return "" if status_text in {"queued", "succeeded", "failed"} else "script_agent"


def _agent_status(name: str, job_status: str, current_agent: str, events: list[dict[str, Any]]) -> str:
    if job_status == "queued":
        return "queued"
    if job_status in {"succeeded", "failed"}:
        return job_status
    names = [item[0] for item in AGENT_ORDER]
    if not current_agent or current_agent not in names:
        return "running" if name == "script_agent" else "queued"
    current_index = names.index(current_agent)
    index = names.index(name)
    if index < current_index:
        return "succeeded"
    if index == current_index:
        return "running"
    return "queued"


def _artifact(job: VideoJob, filename: str) -> str:
    if not job.run_dir:
        return ""
    for rel in (f"output/{filename}", f"output/thumbnails/{filename}", filename):
        path = Path(job.run_dir) / rel
        if path.exists():
            return str(path)
    return ""


def _file_response(path_value: str, media_type: str) -> FileResponse:
    path = Path(path_value)
    if not path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Artifact not found")
    return FileResponse(path, media_type=media_type, filename=path.name)
