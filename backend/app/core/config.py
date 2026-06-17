from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import os


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default)


def _bool_env(name: str, default: bool = False) -> bool:
    value = _env(name, str(default)).strip().lower()
    return value in {"1", "true", "yes", "on"}


def _csv_env(name: str, default: str = "") -> list[str]:
    return [item.strip() for item in _env(name, default).split(",") if item.strip()]


@dataclass(frozen=True)
class Settings:
    app_port: int = 8080
    database_url: str = ""
    redis_url: str = "redis://redis:6379/0"
    queue_name: str = "video_jobs"
    jwt_secret: str = "change-this-long-random-secret"
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 10080
    cors_origins: list[str] = None  # type: ignore[assignment]
    llm_provider: str = "auto"
    llm_api_key: str = ""
    llm_model: str = ""
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-3-5-sonnet-latest"
    groq_api_key: str = ""
    groq_model: str = "openai/gpt-oss-20b"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"
    pexels_api_key: str = ""
    pixabay_api_key: str = ""
    unsplash_access_key: str = ""
    google_tts_credentials: str = ""
    worker_autorun_jobs: bool = False


def _database_url() -> str:
    explicit = _env("DATABASE_URL")
    if explicit:
        return explicit
    user = _env("POSTGRES_USER", "playground")
    password = _env("POSTGRES_PASSWORD", "playground")
    db = _env("POSTGRES_DB", "playground")
    host = _env("POSTGRES_HOST", "db")
    port = _env("POSTGRES_PORT", "5432")
    return f"postgresql+psycopg://{user}:{password}@{host}:{port}/{db}"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings(
        app_port=int(_env("APP_PORT", "8080")),
        database_url=_database_url(),
        redis_url=_env("REDIS_URL", "redis://redis:6379/0"),
        queue_name=_env("QUEUE_NAME", "video_jobs"),
        jwt_secret=_env("JWT_SECRET", "change-this-long-random-secret"),
        jwt_algorithm=_env("JWT_ALGORITHM", "HS256"),
        access_token_minutes=int(_env("ACCESS_TOKEN_MINUTES", "10080")),
        cors_origins=_csv_env("CORS_ORIGINS", "http://localhost:8080,http://localhost:5173"),
        llm_provider=_env("LLM_PROVIDER", "auto"),
        llm_api_key=_env("LLM_API_KEY", ""),
        llm_model=_env("LLM_MODEL", ""),
        anthropic_api_key=_env("ANTHROPIC_API_KEY", ""),
        anthropic_model=_env("ANTHROPIC_MODEL", "claude-3-5-sonnet-latest"),
        groq_api_key=_env("GROQ_API_KEY", ""),
        groq_model=_env("GROQ_MODEL", "openai/gpt-oss-20b"),
        gemini_api_key=_env("GEMINI_API_KEY", ""),
        gemini_model=_env("GEMINI_MODEL", "gemini-2.5-flash"),
        pexels_api_key=_env("PEXELS_API_KEY", ""),
        pixabay_api_key=_env("PIXABAY_API_KEY", ""),
        unsplash_access_key=_env("UNSPLASH_ACCESS_KEY", ""),
        google_tts_credentials=_env("GOOGLE_TTS_CREDENTIALS", ""),
        worker_autorun_jobs=_bool_env("WORKER_AUTORUN_JOBS", False),
    )
