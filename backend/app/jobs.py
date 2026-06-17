from __future__ import annotations

import logging

from app.core.database import SessionLocal
from app.models import Message, VideoJob, utc_now
from app.services.api_keys import user_key_env_overrides
from app.services.pipeline_runner import PipelineRunner


logger = logging.getLogger(__name__)


def run_video_job(job_id: str) -> None:
    db = SessionLocal()
    try:
        job = db.get(VideoJob, job_id)
        if job is None:
            logger.warning("Job %s not found", job_id)
            return
        job.status = "running"
        job.started_at = utc_now()
        job.updated_at = utc_now()
        db.commit()

        runner = PipelineRunner()
        result = runner.run(
            topic=job.topic,
            genre=job.genre,
            duration=job.duration,
            notes=job.notes,
            settings=job.settings,
            env_overrides=user_key_env_overrides(db, job.user_id),
        )

        job.stdout = result.stdout
        job.stderr = result.stderr
        job.video_path = result.video_path
        job.run_dir = result.run_dir
        job.logs_path = f"{result.run_dir}/logs" if result.run_dir else ""
        job.completed_at = utc_now()
        job.updated_at = utc_now()
        if result.returncode == 0 and result.video_path:
            job.status = "succeeded"
            job.error_message = ""
            _add_assistant_message(db, job, "Your video is ready.", {"job_id": job.id})
        else:
            job.status = "failed"
            job.error_message = result.stderr.strip() or result.stdout.strip() or "Pipeline failed"
            _add_assistant_message(db, job, f"Video generation failed: {job.error_message[:400]}", {"job_id": job.id})
        db.commit()
    except Exception as exc:
        db.rollback()
        job = db.get(VideoJob, job_id)
        if job is not None:
            job.status = "failed"
            job.error_message = str(exc)
            job.completed_at = utc_now()
            job.updated_at = utc_now()
            db.commit()
        logger.exception("Job %s failed", job_id)
    finally:
        db.close()


def _add_assistant_message(db, job: VideoJob, content: str, metadata: dict) -> None:
    if not job.chat_id:
        return
    db.add(Message(chat_id=job.chat_id, role="assistant", content=content, message_metadata=metadata))
