from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from app.paths import DATA_DIR, PROJECT_ROOT


@dataclass(frozen=True)
class Settings:
    """Runtime settings loaded from environment variables."""

    project_root: Path = PROJECT_ROOT
    data_dir: Path = DATA_DIR
    video_width: int = 1080
    video_height: int = 1920
    fps: int = 30
    llm_provider: str = "auto"
    llm_api_key: str = ""
    llm_model: str = ""
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-3-5-haiku-20241022"
    groq_api_key: str = ""
    groq_model: str = "openai/gpt-oss-20b"
    gemini_model: str = "gemini-2.5-flash"
    gemini_api_key: str = ""
    pexels_api_key: str = ""
    pixabay_api_key: str = ""
    google_tts_credentials: str = ""
    edge_tts_voice: str = "en-US-GuyNeural"


def load_dotenv_file(path: Path) -> None:
    """Tiny .env loader to avoid requiring python-dotenv."""
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def get_settings() -> Settings:
    load_dotenv_file(PROJECT_ROOT / ".env")
    return Settings(
        llm_provider=os.environ.get("LLM_PROVIDER", "auto"),
        llm_api_key=os.environ.get("LLM_API_KEY", ""),
        llm_model=os.environ.get("LLM_MODEL", ""),
        openai_api_key=os.environ.get("OPENAI_API_KEY", ""),
        openai_model=os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
        anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY", ""),
        anthropic_model=os.environ.get("ANTHROPIC_MODEL", "claude-3-5-haiku-20241022"),
        groq_api_key=os.environ.get("GROQ_API_KEY", ""),
        groq_model=os.environ.get("GROQ_MODEL", "openai/gpt-oss-20b"),
        gemini_model=os.environ.get("GEMINI_MODEL", "gemini-2.5-flash"),
        gemini_api_key=_env_any("GEMINI_API_KEY", "GEMINI_API_KEYS", csv_first=True),
        pexels_api_key=os.environ.get("PEXELS_API_KEY", ""),
        pixabay_api_key=os.environ.get("PIXABAY_API_KEY", ""),
        google_tts_credentials=_env_any(
            "GOOGLE_TTS_CREDENTIALS",
            "TTS_CREDENTIALS_PATH",
            "GOOGLE_APPLICATION_CREDENTIALS",
        ),
        edge_tts_voice=os.environ.get("EDGE_TTS_VOICE", "en-US-GuyNeural"),
    )


def _env_any(*keys: str, csv_first: bool = False) -> str:
    for key in keys:
        value = os.environ.get(key, "").strip()
        if value:
            return _first_csv_value(value) if csv_first else value
    return ""


def _first_csv_value(value: str) -> str:
    return next((item.strip() for item in value.split(",") if item.strip()), "")
