from __future__ import annotations

import logging
from pathlib import Path

from app.core.config import get_settings
from app.models import Message, VideoJob, utc_now
from app.core.database import SessionLocal
from app.services.api_keys import user_key_env_overrides
from app.services.pipeline_runner import PipelineRunner


logger = logging.getLogger(__name__)


def run_video_job(job_id: str) -> None:
    db = SessionLocal()
    try:
        job = db.get(VideoJob, job_id)
        if not job:
            logger.warning("Video job %s was not found in the database", job_id)
            return
        job.status = "running"
        job.started_at = utc_now()
        job.updated_at = utc_now()
        run_dir = str(Path(get_settings().pipeline_runs_dir) / f"job_{job.id}")
        job.run_dir = run_dir
        job.logs_path = str(Path(run_dir) / "logs")
        db.commit()
        logger.info("Started video job %s (%s) with logs at %s", job.id, job.job_type, job.logs_path)

        result = PipelineRunner().run(
            topic=job.topic,
            genre=job.genre,
            duration=job.duration,
            notes=job.notes,
            settings_payload=job.settings or {},
            env_overrides=user_key_env_overrides(db, job.user_id),
            run_dir_override=run_dir,
        )

        job.stdout = result.stdout[-10000:]
        job.stderr = result.stderr[-10000:]
        job.run_dir = result.run_dir
        job.logs_path = result.logs_path
        job.video_path = result.video_path
        job.error_message = result.error_message
        job.completed_at = utc_now()
        job.updated_at = utc_now()

        if result.returncode == 0:
            job.status = "succeeded"
            content = "Your video is ready. You can preview or download it from the job card."
            logger.info("Finished video job %s successfully: %s", job.id, job.video_path)
        else:
            job.status = "failed"
            content = f"The video job failed: {result.error_message or 'pipeline returned a non-zero status'}"
            logger.error("Video job %s failed: %s", job.id, content)

        db.add(
            Message(
                chat_id=job.chat_id,
                role="assistant",
                content=content,
                message_metadata={"job_id": job.id, "job_status": job.status},
            )
        )
        db.commit()
    except Exception as exc:
        job = db.get(VideoJob, job_id)
        if job:
            logger.exception("Video job %s crashed before completion", job.id)
            job.status = "failed"
            job.error_message = str(exc)
            job.completed_at = utc_now()
            job.updated_at = utc_now()
            db.add(
                Message(
                    chat_id=job.chat_id,
                    role="assistant",
                    content=f"The video job failed: {exc}",
                    message_metadata={"job_id": job.id, "job_status": "failed"},
                )
            )
            db.commit()
        raise
    finally:
        db.close()
