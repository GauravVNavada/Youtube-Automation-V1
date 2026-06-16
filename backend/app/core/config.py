from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _default_pipeline_root() -> str:
    return str(Path(__file__).resolve().parents[2] / "pipeline")


@dataclass(frozen=True)
class Settings:
    database_url: str
    redis_url: str
    jwt_secret: str
    jwt_algorithm: str
    access_token_minutes: int
    pipeline_root: str
    pipeline_runs_dir: str
    cors_origins: list[str]
    queue_name: str
    worker_concurrency: int


def get_settings() -> Settings:
    pipeline_root = os.getenv("PIPELINE_ROOT", _default_pipeline_root())
    return Settings(
        database_url=os.getenv(
            "DATABASE_URL",
            "postgresql+psycopg://desktopapp:desktopapp@db:5432/desktopapp",
        ),
        redis_url=os.getenv("REDIS_URL", "redis://redis:6379/0"),
        jwt_secret=os.getenv("JWT_SECRET", "change-me-in-production"),
        jwt_algorithm=os.getenv("JWT_ALGORITHM", "HS256"),
        access_token_minutes=int(os.getenv("ACCESS_TOKEN_MINUTES", "10080")),
        pipeline_root=pipeline_root,
        pipeline_runs_dir=os.getenv(
            "PIPELINE_RUNS_DIR",
            str(Path(pipeline_root) / "runs"),
        ),
        cors_origins=[
            origin.strip()
            for origin in os.getenv("CORS_ORIGINS", "http://localhost:8080,http://localhost:5173").split(",")
            if origin.strip()
        ],
        queue_name=os.getenv("QUEUE_NAME", "video_jobs"),
        worker_concurrency=max(3, int(os.getenv("WORKER_CONCURRENCY", "3"))),
    )
