from __future__ import annotations

import logging

from redis import Redis
from rq import Worker

from app.core.config import get_settings
from app.core.database import SessionLocal, init_database
from app.services.knowledge_seed import seed_pipeline_knowledge


logging.basicConfig(level=logging.INFO)


def main() -> None:
    settings = get_settings()
    init_database()
    db = SessionLocal()
    try:
        seed_pipeline_knowledge(db)
    finally:
        db.close()
    connection = Redis.from_url(settings.redis_url)
    queues = [
        settings.queue_name,
        f"{settings.queue_name}_calibration_1",
        f"{settings.queue_name}_calibration_2",
        f"{settings.queue_name}_calibration_3",
    ]
    worker = Worker(queues, connection=connection)
    worker.work()


if __name__ == "__main__":
    main()
