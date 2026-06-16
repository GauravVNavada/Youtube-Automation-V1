from __future__ import annotations

from redis import Redis
from rq import Queue

from app.core.config import get_settings


def get_queue(name: str | None = None) -> Queue:
    settings = get_settings()
    connection = Redis.from_url(settings.redis_url)
    return Queue(name or settings.queue_name, connection=connection)


def calibration_queue_name(sample_index: int) -> str:
    settings = get_settings()
    slot = max(1, min(3, sample_index))
    return f"{settings.queue_name}_calibration_{slot}"


def get_calibration_queue(sample_index: int) -> Queue:
    return get_queue(calibration_queue_name(sample_index))
