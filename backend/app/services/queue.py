from __future__ import annotations

from app.core.config import get_settings


def get_queue(name: str | None = None):
    settings = get_settings()
    from redis import Redis
    from rq import Queue

    connection = Redis.from_url(settings.redis_url)
    return Queue(name or settings.queue_name, connection=connection)


def calibration_queue_name(sample_index: int) -> str:
    settings = get_settings()
    slot = max(1, min(3, int(sample_index)))
    return f"{settings.queue_name}_calibration_{slot}"


def get_calibration_queue(sample_index: int):
    return get_queue(calibration_queue_name(sample_index))
