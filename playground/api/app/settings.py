from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    database_url: str
    pipeline_root: str
    playground_runs_dir: str
    cors_origins: list[str]


def _default_pipeline_root() -> str:
    return str(Path(__file__).resolve().parents[2] / "pipeline")


def get_settings() -> Settings:
    return Settings(
        database_url=os.getenv(
            "PLAYGROUND_DATABASE_URL",
            "postgresql+psycopg://playground:playground@playground-db:5432/playground",
        ),
        pipeline_root=os.getenv("PIPELINE_ROOT", _default_pipeline_root()),
        playground_runs_dir=os.getenv("PLAYGROUND_RUNS_DIR", "/app/playground-runs"),
        cors_origins=[
            origin.strip()
            for origin in os.getenv(
                "PLAYGROUND_CORS_ORIGINS",
                "http://localhost:8080",
            ).split(",")
            if origin.strip()
        ],
    )


def ensure_runtime_dirs(settings: Settings) -> None:
    Path(settings.playground_runs_dir).mkdir(parents=True, exist_ok=True)
