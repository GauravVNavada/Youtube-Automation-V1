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
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-3-5-haiku-20241022"
    groq_api_key: str = ""
    groq_model: str = "llama-3.3-70b-versatile"
    gemini_model: str = "gemini-2.5-flash"
    gemini_api_key: str = ""
    pexels_api_key: str = ""
    pixabay_api_key: str = ""
    unsplash_access_key: str = ""
    google_tts_credentials: str = ""


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
    load_dotenv_file(PROJECT_ROOT.parent.parent / ".env")
    return Settings(
        llm_provider=os.environ.get("LLM_PROVIDER", "auto"),
        llm_api_key=os.environ.get("LLM_API_KEY", ""),
        llm_model=os.environ.get("LLM_MODEL", ""),
        anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY", ""),
        anthropic_model=os.environ.get("ANTHROPIC_MODEL", "claude-3-5-haiku-20241022"),
        groq_api_key=os.environ.get("GROQ_API_KEY", ""),
        groq_model=os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile"),
        gemini_model=os.environ.get("GEMINI_MODEL", "gemini-2.5-flash"),
        gemini_api_key=os.environ.get("GEMINI_API_KEY", ""),
        pexels_api_key=os.environ.get("PEXELS_API_KEY", ""),
        pixabay_api_key=os.environ.get("PIXABAY_API_KEY", ""),
        unsplash_access_key=os.environ.get("UNSPLASH_ACCESS_KEY", ""),
        google_tts_credentials=os.environ.get("GOOGLE_TTS_CREDENTIALS", ""),
    )
