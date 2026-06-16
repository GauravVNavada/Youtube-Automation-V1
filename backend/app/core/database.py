from __future__ import annotations

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.core.config import get_settings
from app.services.generation_settings import normalize_generation_settings


class Base(DeclarativeBase):
    pass


settings = get_settings()
engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def init_database() -> None:
    import app.models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    migrate_existing_schema()


def migrate_existing_schema() -> None:
    inspector = inspect(engine)
    table_names = inspector.get_table_names()
    statements: list[str] = []

    if "video_jobs" in table_names:
        columns = {column["name"] for column in inspector.get_columns("video_jobs")}
        if "settings" not in columns:
            statements.append("ALTER TABLE video_jobs ADD COLUMN settings JSON DEFAULT '{}' NOT NULL")
        if "parent_job_id" not in columns:
            statements.append("ALTER TABLE video_jobs ADD COLUMN parent_job_id VARCHAR(36) DEFAULT '' NOT NULL")
        if "job_type" not in columns:
            statements.append("ALTER TABLE video_jobs ADD COLUMN job_type VARCHAR(40) DEFAULT 'generation' NOT NULL")

    if "user_api_keys" in table_names:
        user_key_columns = inspector.get_columns("user_api_keys")
        columns = {column["name"] for column in user_key_columns}
        if "model_name" not in columns:
            statements.append("ALTER TABLE user_api_keys ADD COLUMN model_name VARCHAR(120) DEFAULT '' NOT NULL")
        status_column = next((column for column in user_key_columns if column["name"] == "status"), None)
        status_length = getattr(status_column["type"], "length", 0) if status_column else 0
        if status_column and status_length and status_length < 300:
            statements.append("ALTER TABLE user_api_keys ALTER COLUMN status TYPE VARCHAR(300)")

    if "onboarding_states" in table_names:
        columns = {column["name"] for column in inspector.get_columns("onboarding_states")}
        if "active_chat_id" not in columns:
            statements.append("ALTER TABLE onboarding_states ADD COLUMN active_chat_id VARCHAR(36) DEFAULT '' NOT NULL")

    if not statements:
        _repair_video_job_settings()
        return
    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))
    _repair_video_job_settings()


def _repair_video_job_settings() -> None:
    import app.models  # noqa: F401
    from app.models import VideoJob

    changed = False
    db = SessionLocal()
    try:
        for job in db.query(VideoJob).all():
            settings = normalize_generation_settings(job.settings or {})
            if settings["duration"] != job.duration:
                settings["duration"] = job.duration
            if settings != (job.settings or {}):
                job.settings = settings
                changed = True
        if changed:
            db.commit()
    finally:
        db.close()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
