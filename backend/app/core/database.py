from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import get_settings


class UserBase(DeclarativeBase):
    pass


class StaticBase(DeclarativeBase):
    pass


class PlaygroundBase(DeclarativeBase):
    pass


settings = get_settings()
user_engine = create_engine(settings.user_database_url, pool_pre_ping=True, future=True)
static_engine = create_engine(settings.static_database_url, pool_pre_ping=True, future=True)
playground_engine = create_engine(settings.playground_database_url, pool_pre_ping=True, future=True)

# Backward-compatible aliases for the user-facing desktop database.
Base = UserBase
engine = user_engine
SessionLocal = sessionmaker(bind=user_engine, autoflush=False, autocommit=False, expire_on_commit=False)
UserSessionLocal = SessionLocal
StaticSessionLocal = sessionmaker(bind=static_engine, autoflush=False, autocommit=False, expire_on_commit=False)
PlaygroundSessionLocal = sessionmaker(bind=playground_engine, autoflush=False, autocommit=False, expire_on_commit=False)


LEGACY_STATIC_TABLES = (
    "ai_suggestions",
    "generation_runs",
    "genre_hooks",
    "genre_rules",
    "knowledge_import_batches",
    "music_assets",
    "reference_videos",
    "script_analysis",
    "sfx_assets",
    "topic_expansion_rules",
    "topic_research_sources",
    "visual_style_rules",
)


def init_database() -> None:
    from app import models  # noqa: F401

    UserBase.metadata.create_all(bind=user_engine)
    drop_legacy_static_tables()
    StaticBase.metadata.create_all(bind=static_engine)
    repair_static_schema()
    PlaygroundBase.metadata.create_all(bind=playground_engine)


def drop_legacy_static_tables() -> None:
    suffix = " CASCADE" if static_engine.dialect.name == "postgresql" else ""
    with static_engine.begin() as connection:
        for table_name in LEGACY_STATIC_TABLES:
            connection.execute(text(f'DROP TABLE IF EXISTS "{table_name}"{suffix}'))


def repair_static_schema() -> None:
    if static_engine.dialect.name != "postgresql":
        return

    statements = [
        'ALTER TABLE genres ADD COLUMN IF NOT EXISTS category VARCHAR(80) DEFAULT \'\'',
        'ALTER TABLE genres ADD COLUMN IF NOT EXISTS tone TEXT DEFAULT \'\'',
        'ALTER TABLE genres ADD COLUMN IF NOT EXISTS audience_size VARCHAR(40) DEFAULT \'\'',
        'ALTER TABLE genres ADD COLUMN IF NOT EXISTS competition_level VARCHAR(40) DEFAULT \'\'',
        'ALTER TABLE genres ADD COLUMN IF NOT EXISTS content_difficulty VARCHAR(40) DEFAULT \'\'',
        'ALTER TABLE genres ADD COLUMN IF NOT EXISTS recommended_score INTEGER DEFAULT 0',
        'ALTER TABLE genres ADD COLUMN IF NOT EXISTS default_duration_sec INTEGER DEFAULT 45',
        'ALTER TABLE genres ADD COLUMN IF NOT EXISTS word_count_min INTEGER DEFAULT 80',
        'ALTER TABLE genres ADD COLUMN IF NOT EXISTS word_count_max INTEGER DEFAULT 130',
        'ALTER TABLE genres ADD COLUMN IF NOT EXISTS layout VARCHAR(80) DEFAULT \'full_image\'',
        'ALTER TABLE genres ADD COLUMN IF NOT EXISTS caption_preset VARCHAR(80) DEFAULT \'default\'',
        'ALTER TABLE genres ADD COLUMN IF NOT EXISTS voice_rate DOUBLE PRECISION DEFAULT 1.0',
        'ALTER TABLE genres ADD COLUMN IF NOT EXISTS music_mood VARCHAR(80) DEFAULT \'\'',
        'ALTER TABLE genres ADD COLUMN IF NOT EXISTS realism_mode VARCHAR(60) DEFAULT \'inspired_by_real_events\'',
        "ALTER TABLE genres ADD COLUMN IF NOT EXISTS hook_patterns JSON DEFAULT '[]'::json",
        "ALTER TABLE genres ADD COLUMN IF NOT EXISTS banned_phrases JSON DEFAULT '[]'::json",
        "ALTER TABLE genres ADD COLUMN IF NOT EXISTS visual_style JSON DEFAULT '{}'::json",
        "ALTER TABLE genres ADD COLUMN IF NOT EXISTS topic_rules JSON DEFAULT '[]'::json",
        "ALTER TABLE genres ADD COLUMN IF NOT EXISTS metadata_json JSON DEFAULT '{}'::json",
        "ALTER TABLE genres ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT true",
        "ALTER TABLE genres ADD COLUMN IF NOT EXISTS notes TEXT DEFAULT ''",
        "ALTER TABLE genres ADD COLUMN IF NOT EXISTS created_at TIMESTAMP WITH TIME ZONE DEFAULT now()",
        "ALTER TABLE genres ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP WITH TIME ZONE DEFAULT now()",
        "UPDATE genres SET hook_patterns = '[]'::json WHERE hook_patterns IS NULL",
        "UPDATE genres SET banned_phrases = '[]'::json WHERE banned_phrases IS NULL",
        "UPDATE genres SET visual_style = '{}'::json WHERE visual_style IS NULL",
        "UPDATE genres SET topic_rules = '[]'::json WHERE topic_rules IS NULL",
        "UPDATE genres SET metadata_json = '{}'::json WHERE metadata_json IS NULL",
        "ALTER TABLE reference_examples ADD COLUMN IF NOT EXISTS genre_id VARCHAR(80) DEFAULT ''",
        "ALTER TABLE reference_examples ADD COLUMN IF NOT EXISTS source_url VARCHAR(700) DEFAULT ''",
        "ALTER TABLE reference_examples ADD COLUMN IF NOT EXISTS title VARCHAR(200) DEFAULT ''",
        "ALTER TABLE reference_examples ADD COLUMN IF NOT EXISTS source_label VARCHAR(120) DEFAULT ''",
        "ALTER TABLE reference_examples ADD COLUMN IF NOT EXISTS script TEXT DEFAULT ''",
        "ALTER TABLE reference_examples ADD COLUMN IF NOT EXISTS description TEXT DEFAULT ''",
        "ALTER TABLE reference_examples ADD COLUMN IF NOT EXISTS tags JSON DEFAULT '[]'::json",
        "ALTER TABLE reference_examples ADD COLUMN IF NOT EXISTS metrics JSON DEFAULT '{}'::json",
        "ALTER TABLE reference_examples ADD COLUMN IF NOT EXISTS analysis JSON DEFAULT '{}'::json",
        "ALTER TABLE reference_examples ADD COLUMN IF NOT EXISTS facts JSON DEFAULT '[]'::json",
        "ALTER TABLE reference_examples ADD COLUMN IF NOT EXISTS duration_sec INTEGER DEFAULT 0",
        "ALTER TABLE reference_examples ADD COLUMN IF NOT EXISTS word_count INTEGER DEFAULT 0",
        "ALTER TABLE reference_examples ADD COLUMN IF NOT EXISTS overall_score DOUBLE PRECISION DEFAULT 0.0",
        "ALTER TABLE reference_examples ADD COLUMN IF NOT EXISTS usable_as_few_shot BOOLEAN DEFAULT true",
        "ALTER TABLE reference_examples ADD COLUMN IF NOT EXISTS notes TEXT DEFAULT ''",
        "ALTER TABLE reference_examples ADD COLUMN IF NOT EXISTS created_at TIMESTAMP WITH TIME ZONE DEFAULT now()",
        "ALTER TABLE reference_examples ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP WITH TIME ZONE DEFAULT now()",
        "UPDATE reference_examples SET tags = '[]'::json WHERE tags IS NULL",
        "UPDATE reference_examples SET metrics = '{}'::json WHERE metrics IS NULL",
        "UPDATE reference_examples SET analysis = '{}'::json WHERE analysis IS NULL",
        "UPDATE reference_examples SET facts = '[]'::json WHERE facts IS NULL",
        "ALTER TABLE static_assets ADD COLUMN IF NOT EXISTS asset_type VARCHAR(30) DEFAULT 'music'",
        "ALTER TABLE static_assets ADD COLUMN IF NOT EXISTS name VARCHAR(180) DEFAULT ''",
        "ALTER TABLE static_assets ADD COLUMN IF NOT EXISTS path TEXT DEFAULT ''",
        "ALTER TABLE static_assets ADD COLUMN IF NOT EXISTS description TEXT DEFAULT ''",
        "ALTER TABLE static_assets ADD COLUMN IF NOT EXISTS tags JSON DEFAULT '[]'::json",
        "ALTER TABLE static_assets ADD COLUMN IF NOT EXISTS aliases JSON DEFAULT '[]'::json",
        "ALTER TABLE static_assets ADD COLUMN IF NOT EXISTS use_cases JSON DEFAULT '[]'::json",
        "ALTER TABLE static_assets ADD COLUMN IF NOT EXISTS mood VARCHAR(80) DEFAULT ''",
        "ALTER TABLE static_assets ADD COLUMN IF NOT EXISTS intensity VARCHAR(40) DEFAULT ''",
        "ALTER TABLE static_assets ADD COLUMN IF NOT EXISTS duration_ms INTEGER DEFAULT 0",
        "ALTER TABLE static_assets ADD COLUMN IF NOT EXISTS source VARCHAR(80) DEFAULT 'local'",
        "ALTER TABLE static_assets ADD COLUMN IF NOT EXISTS metadata_json JSON DEFAULT '{}'::json",
        "ALTER TABLE static_assets ADD COLUMN IF NOT EXISTS enabled BOOLEAN DEFAULT true",
        "ALTER TABLE static_assets ADD COLUMN IF NOT EXISTS created_at TIMESTAMP WITH TIME ZONE DEFAULT now()",
        "ALTER TABLE static_assets ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP WITH TIME ZONE DEFAULT now()",
        "UPDATE static_assets SET tags = '[]'::json WHERE tags IS NULL",
        "UPDATE static_assets SET aliases = '[]'::json WHERE aliases IS NULL",
        "UPDATE static_assets SET use_cases = '[]'::json WHERE use_cases IS NULL",
        "UPDATE static_assets SET metadata_json = '{}'::json WHERE metadata_json IS NULL",
    ]
    with static_engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_static_db() -> Iterator[Session]:
    db = StaticSessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_playground_db() -> Iterator[Session]:
    db = PlaygroundSessionLocal()
    try:
        yield db
    finally:
        db.close()
