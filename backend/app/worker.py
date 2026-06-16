from __future__ import annotations

import logging
import os
import socket
import uuid
from multiprocessing import Process

from redis import Redis
from rq import Queue, Worker

from app.core.config import Settings, get_settings
from app.core.database import SessionLocal, engine, init_database
from app.services.queue import calibration_queue_name
from app.services.knowledge_seed import seed_pipeline_knowledge


def main() -> None:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
    settings = get_settings()
    init_database()
    db = SessionLocal()
    try:
        seed_pipeline_knowledge(db)
    finally:
        db.close()
    if settings.worker_concurrency == 1:
        _work(settings, worker_index=1, with_scheduler=True)
        return

    processes = [
        Process(
            target=_work,
            args=(settings, index + 1, index == 0),
            name=f"video-worker-{index + 1}",
        )
        for index in range(settings.worker_concurrency)
    ]
    for process in processes:
        process.start()
    for process in processes:
        process.join()


def _work(settings: Settings, worker_index: int, with_scheduler: bool) -> None:
    # Child workers must not reuse DB connections opened before multiprocessing fork.
    engine.dispose(close=False)
    connection = Redis.from_url(settings.redis_url)
    queue_names = _queue_names_for_worker(settings, worker_index)
    queues = [Queue(name, connection=connection) for name in queue_names]
    logging.info("Worker %s listening on queues: %s", worker_index, ", ".join(queue_names))
    worker = Worker(
        queues,
        connection=connection,
        name=f"{settings.queue_name}-{socket.gethostname()}-{os.getpid()}-{worker_index}-{uuid.uuid4().hex[:8]}",
    )
    worker.work(with_scheduler=with_scheduler)


def _queue_names_for_worker(settings: Settings, worker_index: int) -> list[str]:
    names: list[str] = []
    if worker_index <= 3:
        names.append(calibration_queue_name(worker_index))
    names.append(settings.queue_name)
    return names


if __name__ == "__main__":
    main()
