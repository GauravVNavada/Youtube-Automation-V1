from __future__ import annotations

import logging
import os

from redis import Redis
from rq import Worker

from app.core.config import get_settings
from app.core.database import StaticSessionLocal, init_database
from app.services.knowledge_seed import seed_pipeline_knowledge


logging.basicConfig(level=logging.INFO)


def main() -> None:
    settings = get_settings()
    init_database()
    db = StaticSessionLocal()
    try:
        seed_pipeline_knowledge(db)
    finally:
        db.close()
    connection = Redis.from_url(settings.redis_url)
    configured_queues = [item.strip() for item in os.getenv("WORKER_QUEUES", "").split(",") if item.strip()]
    queues = configured_queues or [
        settings.queue_name,
        f"{settings.queue_name}_calibration_1",
        f"{settings.queue_name}_calibration_2",
        f"{settings.queue_name}_calibration_3",
    ]
    worker = Worker(queues, connection=connection)
    worker.work()


if __name__ == "__main__":
    main()
