from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.dependencies import require_active_entitlement
from app.models import User, VideoJob, utc_now
from app.schemas import AgentProgressOut, JobLogsOut, JobOut, JobProgressOut, JobRetryIn, StageLogsOut
from app.services.queue import get_calibration_queue, get_queue


router = APIRouter(prefix="/jobs", tags=["jobs"])

AGENT_ORDER = [
    ("bootstrap", "Bootstrap"),
    ("load_references", "References"),
    ("llm_provider", "AI setup"),
    ("topic_discovery_agent", "Discovery"),
    ("research_agent", "Research"),
    ("script_agent", "Script"),
    ("validation_agent", "Validation"),
    ("asset_agent", "Assets"),
    ("audio_agent", "Voice"),
    ("caption_agent", "Captions"),
    ("timed_visual_agent", "Timing"),
    ("music_agent", "Music"),
    ("render_agent", "Render"),
    ("thumbnail_agent", "Thumbnail"),
    ("final_output", "Final"),
]

STDOUT_STAGE_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"^\[run\]"), "bootstrap"),
    (re.compile(r"^\[resume\]"), "bootstrap"),
    (re.compile(r"^\[1/10\].*Discovering", re.I), "topic_discovery_agent"),
    (re.compile(r"^\[2/10\].*research|^\[2/10\].*brief", re.I), "research_agent"),
    (re.compile(r"^\[3/10\].*script", re.I), "script_agent"),
    (re.compile(r"^\[validation\]", re.I), "validation_agent"),
    (re.compile(r"^\[4/10\].*audio", re.I), "audio_agent"),
    (re.compile(r"^\[5/10\].*caption", re.I), "caption_agent"),
    (re.compile(r"^\[6/10\].*timed|^\[6/10\].*visual cues", re.I), "timed_visual_agent"),
    (re.compile(r"^\[7/10\].*assets", re.I), "asset_agent"),
    (re.compile(r"^\[8/11\].*music|^\[8/11\].*SFX", re.I), "music_agent"),
    (re.compile(r"^\[9/11\].*render", re.I), "render_agent"),
    (re.compile(r"^\[10/11\].*thumbnail", re.I), "thumbnail_agent"),
    (re.compile(r"^\[11/11\]|^Final video:", re.I), "final_output"),
)
ERROR_STAGE_MAP = {
    "load_genre": "bootstrap",
    "load_references": "load_references",
    "llm_provider": "llm_provider",
    "validate_script": "validation_agent",
}
STAGE_LABELS = dict(AGENT_ORDER)
RETRYABLE_STAGES = {
    "topic_discovery_agent",
    "research_agent",
    "script_agent",
    "validation_agent",
    "asset_agent",
    "audio_agent",
    "caption_agent",
    "timed_visual_agent",
    "music_agent",
    "render_agent",
    "thumbnail_agent",
}


@router.get("", response_model=list[JobOut])
def list_jobs(user: User = Depends(require_active_entitlement), db: Session = Depends(get_db)) -> list[VideoJob]:
    return _with_urls(db.scalars(select(VideoJob).where(VideoJob.user_id == user.id).order_by(VideoJob.created_at.desc())).all())


@router.get("/{job_id}", response_model=JobOut)
def get_job(job_id: str, user: User = Depends(require_active_entitlement), db: Session = Depends(get_db)) -> VideoJob:
    return _with_urls([_job_for(db, user, job_id)])[0]


@router.get("/{job_id}/progress", response_model=JobProgressOut)
def job_progress(job_id: str, user: User = Depends(require_active_entitlement), db: Session = Depends(get_db)) -> JobProgressOut:
    job = _job_for(db, user, job_id)
    events = _load_events(job)
    percent = _percent_for(job.status, events)
    current_agent = _current_agent(job.status, events)
    failed_stage = _failed_stage(job, events)
    agents = [
        AgentProgressOut(
            name=name,
            label=label,
            status=_agent_status(name, job.status, current_agent, failed_stage),
            message=_stage_message(name, events, job.error_message if name == failed_stage else ""),
        )
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
def job_logs(job_id: str, user: User = Depends(require_active_entitlement), db: Session = Depends(get_db)) -> JobLogsOut:
    job = _job_for(db, user, job_id)
    return JobLogsOut(
        job_id=job.id,
        events=_load_events(job),
        stdout=job.stdout,
        stderr=job.stderr,
        error_message=job.error_message,
    )


@router.get("/{job_id}/stages/{stage_name}/logs", response_model=StageLogsOut)
def stage_logs(
    job_id: str,
    stage_name: str,
    user: User = Depends(require_active_entitlement),
    db: Session = Depends(get_db),
) -> StageLogsOut:
    job = _job_for(db, user, job_id)
    stage_name = _normalize_stage(stage_name)
    if stage_name not in STAGE_LABELS:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pipeline stage not found")
    events = [event for event in _load_events(job) if _normalize_stage(str(event.get("agent") or event.get("module") or event.get("stage") or "")) == stage_name]
    progress = job_progress(job_id, user, db)
    agent = next((item for item in progress.agents if item.name == stage_name), None)
    stage_dir = Path(job.run_dir) / "logs" / stage_name if job.run_dir else Path("")
    error_json = _stage_error(job, stage_name)
    error_message = _stage_error_message(job, stage_name, error_json)
    return StageLogsOut(
        job_id=job.id,
        stage_name=stage_name,
        label=STAGE_LABELS.get(stage_name, stage_name),
        status=agent.status if agent else "queued",
        message=(agent.message if agent else "") or error_message,
        events=events[-80:],
        input_json=_read_json(stage_dir / "input.json") if job.run_dir else None,
        output_json=_read_json(stage_dir / "output.json") if job.run_dir else None,
        error_json=error_json,
        error_message=error_message,
        stdout_lines=[line for line in (job.stdout or "").splitlines() if _stage_from_stdout(line) == stage_name][-30:],
    )


@router.post("/{job_id}/retry", response_model=JobOut)
def retry_job(
    job_id: str,
    payload: JobRetryIn | None = None,
    user: User = Depends(require_active_entitlement),
    db: Session = Depends(get_db),
) -> VideoJob:
    payload = payload or JobRetryIn()
    source = _job_for(db, user, job_id)
    stage_name = _normalize_stage(payload.stage_name.strip())
    if stage_name and stage_name not in RETRYABLE_STAGES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="This stage cannot be retried directly")
    if stage_name and not source.run_dir:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="This job has no run directory to resume from")

    settings = dict(source.settings or {})
    settings.pop("resume_from_run_dir", None)
    settings.pop("rerun_stage", None)
    settings.pop("retry_of_job_id", None)
    settings.pop("retry_stage", None)
    if stage_name:
        settings["resume_from_run_dir"] = source.run_dir
        settings["rerun_stage"] = stage_name
        settings["retry_stage"] = stage_name
    settings["retry_of_job_id"] = source.id

    job = VideoJob(
        user_id=user.id,
        chat_id=source.chat_id,
        status="queued",
        topic=source.topic,
        genre=source.genre,
        duration=source.duration,
        notes=_retry_notes(source.notes, payload.notes, stage_name),
        settings=settings,
        parent_job_id=source.id,
        job_type="stage_retry" if stage_name else source.job_type,
        planned_agents=source.planned_agents or [],
        updated_at=utc_now(),
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    _enqueue_retry(job)
    return _with_urls([job])[0]


@router.get("/{job_id}/download")
def download(job_id: str, user: User = Depends(require_active_entitlement), db: Session = Depends(get_db)) -> FileResponse:
    job = _job_for(db, user, job_id)
    return _file_response(job.video_path, "video/mp4")


@router.get("/{job_id}/preview")
def preview(job_id: str, user: User = Depends(require_active_entitlement), db: Session = Depends(get_db)) -> FileResponse:
    job = _job_for(db, user, job_id)
    return _file_response(job.video_path, "video/mp4")


@router.get("/{job_id}/shorts-cover")
def shorts_cover(job_id: str, user: User = Depends(require_active_entitlement), db: Session = Depends(get_db)) -> FileResponse:
    job = _job_for(db, user, job_id)
    return _file_response(_artifact(job, "shorts_cover.jpg"), "image/jpeg")


@router.get("/{job_id}/youtube-thumbnail")
def youtube_thumbnail(job_id: str, user: User = Depends(require_active_entitlement), db: Session = Depends(get_db)) -> FileResponse:
    job = _job_for(db, user, job_id)
    return _file_response(_artifact(job, "youtube_thumbnail.jpg"), "image/jpeg")


@router.get("/{job_id}/render-plan")
def render_plan(job_id: str, user: User = Depends(require_active_entitlement), db: Session = Depends(get_db)) -> FileResponse:
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


def _enqueue_retry(job: VideoJob) -> None:
    try:
        if job.job_type == "calibration_sample":
            get_calibration_queue(int((job.settings or {}).get("sample_index", 1))).enqueue("app.jobs.run_video_job", job.id)
        else:
            get_queue().enqueue("app.jobs.run_video_job", job.id)
    except Exception:
        return


def _load_events(job: VideoJob) -> list[dict[str, Any]]:
    candidates = []
    if job.run_dir:
        candidates.extend(Path(job.run_dir).glob("logs/*.jsonl"))
        candidates.extend(Path(job.run_dir).glob("*.jsonl"))
        candidates.extend(Path(job.run_dir).glob("logs/*/events.log"))
        candidates.extend(Path(job.run_dir).glob("errors/events.log"))
    events: list[dict[str, Any]] = _stdout_stage_events(job.stdout or "")
    for path in candidates:
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    events.append(json.loads(line))
        except Exception:
            continue
    return events


def _stage_error(job: VideoJob, stage_name: str) -> dict[str, Any] | None:
    if not job.run_dir:
        return None
    error_path = Path(job.run_dir) / "errors" / "error.json"
    data = _read_json(error_path)
    if not isinstance(data, dict):
        return None
    if _normalize_stage(str(data.get("stage") or "")) == stage_name:
        return data
    return None


def _read_json(path: Path) -> dict[str, Any] | list[Any] | None:
    try:
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _percent_for(status_text: str, events: list[dict[str, Any]]) -> int:
    if status_text == "succeeded":
        return 100
    if status_text == "queued":
        return 2
    names = [name for name, _ in AGENT_ORDER]
    current = _current_agent(status_text, events)
    if current in names:
        base = int(((names.index(current) + 1) / len(names)) * 100)
        return min(99, max(4, base))
    return 35 if status_text == "running" else 100


def _current_agent(status_text: str, events: list[dict[str, Any]]) -> str:
    for event in reversed(events):
        name = _normalize_stage(str(event.get("agent") or event.get("module") or event.get("stage") or ""))
        if name in dict(AGENT_ORDER):
            return name
    return "" if status_text in {"queued", "succeeded", "failed"} else "bootstrap"


def _agent_status(name: str, job_status: str, current_agent: str, failed_stage: str) -> str:
    if job_status == "queued":
        return "queued"
    if job_status == "succeeded":
        return job_status
    if job_status == "failed" and failed_stage:
        names = [item[0] for item in AGENT_ORDER]
        failed_index = names.index(failed_stage) if failed_stage in names else len(names) - 1
        index = names.index(name)
        if index < failed_index:
            return "succeeded"
        if index == failed_index:
            return "failed"
        return "queued"
    names = [item[0] for item in AGENT_ORDER]
    if not current_agent or current_agent not in names:
        return "failed" if job_status == "failed" and name == "final_output" else ("running" if name == "bootstrap" else "queued")
    current_index = names.index(current_agent)
    index = names.index(name)
    if index < current_index:
        return "succeeded"
    if index == current_index:
        return "failed" if job_status == "failed" else "running"
    return "queued"


def _stage_message(name: str, events: list[dict[str, Any]], fallback: str = "") -> str:
    for event in reversed(events):
        if _normalize_stage(str(event.get("agent") or event.get("module") or event.get("stage") or "")) == name:
            return str(event.get("message") or event.get("error_type") or "")[:180]
    return str(fallback or "")[:180]


def _stdout_stage_events(stdout: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        stage = _stage_from_stdout(line)
        if stage:
            events.append({"stage": stage, "message": line, "source": "stdout"})
    return events


def _stage_from_stdout(line: str) -> str:
    for pattern, stage in STDOUT_STAGE_PATTERNS:
        if pattern.search(line):
            return stage
    return ""


def _normalize_stage(stage: str) -> str:
    if not stage:
        return ""
    stage = re.sub(r"_repair_\d+$", "", stage)
    return ERROR_STAGE_MAP.get(stage, stage)


def _failed_stage(job: VideoJob, events: list[dict[str, Any]]) -> str:
    if job.status != "failed":
        return ""
    if job.run_dir:
        data = _read_json(Path(job.run_dir) / "errors" / "error.json")
        if isinstance(data, dict):
            stage = _normalize_stage(str(data.get("stage") or ""))
            if stage in STAGE_LABELS:
                return stage
    for event in reversed(events):
        stage = _normalize_stage(str(event.get("agent") or event.get("module") or event.get("stage") or ""))
        if stage in STAGE_LABELS:
            return stage
    return "final_output"


def _stage_error_message(job: VideoJob, stage_name: str, error_json: dict[str, Any] | None) -> str:
    message = str((error_json or {}).get("message") or "").strip()
    if message:
        return message
    if job.status == "failed" and _failed_stage(job, _load_events(job)) == stage_name:
        return (job.error_message or job.stderr or "Pipeline failed").strip()
    return ""


def _retry_notes(source_notes: str, retry_notes: str, stage_name: str) -> str:
    parts = [str(source_notes or "").strip()]
    if stage_name:
        parts.append(f"Retry requested for pipeline stage: {STAGE_LABELS.get(stage_name, stage_name)}.")
    if retry_notes.strip():
        parts.append(f"Retry notes: {retry_notes.strip()}")
    return "\n".join(part for part in parts if part)


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
