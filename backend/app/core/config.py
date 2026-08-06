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
    user_database_url: str = ""
    static_database_url: str = ""
    playground_database_url: str = ""
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
    worker_job_timeout: int = 1800
    razorpay_key_id: str = ""
    razorpay_key_secret: str = ""
    razorpay_webhook_secret: str = ""
    payment_currency: str = "INR"
    payment_site_url: str = "http://localhost:3001"
    payment_monthly_plan_id: str = ""
    payment_yearly_plan_id: str = ""
    payment_monthly_amount_paise: int = 49900
    payment_yearly_amount_paise: int = 499900
    payment_lifetime_amount_paise: int = 999900


def _postgres_url(
    *,
    prefix: str,
    default_user: str,
    default_password: str,
    default_db: str,
    default_host: str,
    default_port: str,
) -> str:
    user = _env(f"{prefix}_DB_USER", default_user)
    password = _env(f"{prefix}_DB_PASSWORD", default_password)
    db = _env(f"{prefix}_DB_NAME", default_db)
    host = _env(f"{prefix}_DB_HOST", default_host)
    port = _env(f"{prefix}_DB_PORT", default_port)
    return f"postgresql+psycopg://{user}:{password}@{host}:{port}/{db}"


def _user_database_url() -> str:
    explicit = _env("USER_DATABASE_URL", _env("DATABASE_URL"))
    if explicit:
        return explicit
    return _postgres_url(
        prefix="APP",
        default_user=_env("POSTGRES_USER", "pradeep"),
        default_password=_env("POSTGRES_PASSWORD", "password"),
        default_db=_env("POSTGRES_DB", "automation"),
        default_host=_env("POSTGRES_HOST", "db_user"),
        default_port=_env("POSTGRES_PORT", "5432"),
    )


def _static_database_url() -> str:
    explicit = _env("STATIC_DATABASE_URL")
    if explicit:
        return explicit
    return _postgres_url(
        prefix="STATIC",
        default_user=_env("APP_DB_USER", "pradeep"),
        default_password=_env("APP_DB_PASSWORD", "password"),
        default_db="static_assets",
        default_host="db_static",
        default_port="5432",
    )


def _playground_database_url() -> str:
    explicit = _env("PLAYGROUND_DATABASE_URL")
    if explicit:
        return explicit
    return _postgres_url(
        prefix="PLAYGROUND",
        default_user="playground",
        default_password="playground",
        default_db="playground",
        default_host="db_playground",
        default_port="5432",
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    user_database_url = _user_database_url()
    return Settings(
        app_port=int(_env("APP_PORT", "8080")),
        database_url=user_database_url,
        user_database_url=user_database_url,
        static_database_url=_static_database_url(),
        playground_database_url=_playground_database_url(),
        redis_url=_env("REDIS_URL", "redis://redis:6379/0"),
        queue_name=_env("QUEUE_NAME", "video_jobs"),
        jwt_secret=_env("JWT_SECRET", "change-this-long-random-secret"),
        jwt_algorithm=_env("JWT_ALGORITHM", "HS256"),
        access_token_minutes=int(_env("ACCESS_TOKEN_MINUTES", "10080")),
        cors_origins=_csv_env(
            "CORS_ORIGINS",
            "http://localhost:8080,http://localhost:3001,http://localhost:5173,http://localhost:5174,file://,null",
        ),
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
        worker_job_timeout=int(_env("WORKER_JOB_TIMEOUT", "1800")),
        razorpay_key_id=_env("RAZORPAY_KEY_ID", ""),
        razorpay_key_secret=_env("RAZORPAY_KEY_SECRET", ""),
        razorpay_webhook_secret=_env("RAZORPAY_WEBHOOK_SECRET", ""),
        payment_currency=_env("PAYMENT_CURRENCY", "INR"),
        payment_site_url=_env("PAYMENT_SITE_URL", "http://localhost:3001"),
        payment_monthly_plan_id=_env("PAYMENT_MONTHLY_PLAN_ID", ""),
        payment_yearly_plan_id=_env("PAYMENT_YEARLY_PLAN_ID", ""),
        payment_monthly_amount_paise=int(_env("PAYMENT_MONTHLY_AMOUNT_PAISE", "49900")),
        payment_yearly_amount_paise=int(_env("PAYMENT_YEARLY_AMOUNT_PAISE", "499900")),
        payment_lifetime_amount_paise=int(_env("PAYMENT_LIFETIME_AMOUNT_PAISE", "999900")),
    )
