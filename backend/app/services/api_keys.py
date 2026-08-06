from __future__ import annotations

import base64
from datetime import datetime, timezone
import hashlib
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import UserApiKey


PROVIDER_ENV_KEYS = {
    "gemini": "GEMINI_API_KEY",
    "groq": "GROQ_API_KEY",
    "openai": "LLM_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "pexels": "PEXELS_API_KEY",
    "pixabay": "PIXABAY_API_KEY",
    "unsplash": "UNSPLASH_ACCESS_KEY",
    "google_tts": "GOOGLE_TTS_CREDENTIALS",
}


def save_user_api_key(db: Session, user_id: int, provider: str, value: str, model: str = "") -> UserApiKey:
    provider = provider.strip().lower()
    row = db.scalar(select(UserApiKey).where(UserApiKey.user_id == user_id, UserApiKey.provider == provider))
    if row is None:
        row = UserApiKey(user_id=user_id, provider=provider)
        db.add(row)
    row.encrypted_value = _encode(value)
    row.model_name = model
    row.status = "configured" if value else "empty"
    row.last_tested_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(row)
    return row


def api_key_statuses(db: Session, user_id: int) -> list[dict[str, Any]]:
    rows = {
        row.provider: row
        for row in db.scalars(select(UserApiKey).where(UserApiKey.user_id == user_id)).all()
    }
    settings = get_settings()
    statuses = []
    for provider in PROVIDER_ENV_KEYS:
        row = rows.get(provider)
        env_value = _settings_value(settings, provider)
        if row and row.encrypted_value:
            statuses.append(
                {
                    "provider": provider,
                    "status": row.status or "configured",
                    "source": "user",
                    "model": row.model_name or "",
                    "last_tested_at": row.last_tested_at,
                }
            )
        else:
            statuses.append(
                {
                    "provider": provider,
                    "status": "configured" if env_value else "missing",
                    "source": "env" if env_value else "none",
                    "model": _default_model(settings, provider),
                    "last_tested_at": None,
                }
            )
    return statuses


def user_key_env_overrides(db: Session, user_id: int) -> dict[str, str]:
    overrides: dict[str, str] = {}
    rows = db.scalars(select(UserApiKey).where(UserApiKey.user_id == user_id)).all()
    for row in rows:
        env_name = PROVIDER_ENV_KEYS.get(row.provider)
        value = _decode(row.encrypted_value)
        if env_name and value:
            overrides[env_name] = value
        if row.model_name:
            if row.provider == "gemini":
                overrides["GEMINI_MODEL"] = row.model_name
            elif row.provider == "groq":
                overrides["GROQ_MODEL"] = row.model_name
            elif row.provider == "openai":
                overrides["LLM_MODEL"] = row.model_name
            elif row.provider == "anthropic":
                overrides["ANTHROPIC_MODEL"] = row.model_name
    return overrides


def llm_options() -> list[dict[str, Any]]:
    settings = get_settings()
    return [
        {"provider": "gemini", "label": "Google Gemini", "default_model": settings.gemini_model, "configured": bool(settings.gemini_api_key)},
        {"provider": "groq", "label": "Groq", "default_model": settings.groq_model, "configured": bool(settings.groq_api_key)},
        {"provider": "openai", "label": "OpenAI", "default_model": settings.llm_model, "configured": bool(settings.llm_api_key)},
        {"provider": "anthropic", "label": "Anthropic", "default_model": settings.anthropic_model, "configured": bool(settings.anthropic_api_key)},
    ]


def _encode(value: str) -> str:
    if not value:
        return ""
    token = _fernet().encrypt(value.encode("utf-8")).decode("ascii")
    return f"fernet:{token}"


def _decode(value: str) -> str:
    if not value:
        return ""
    if value.startswith("fernet:"):
        try:
            return _fernet().decrypt(value.removeprefix("fernet:").encode("ascii")).decode("utf-8")
        except (InvalidToken, ValueError):
            return ""
    try:
        return base64.urlsafe_b64decode(value.encode("ascii")).decode("utf-8")
    except Exception:
        return ""


def _fernet() -> Fernet:
    digest = hashlib.sha256(get_settings().jwt_secret.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def _settings_value(settings, provider: str) -> str:
    return {
        "gemini": settings.gemini_api_key,
        "groq": settings.groq_api_key,
        "openai": settings.llm_api_key,
        "anthropic": settings.anthropic_api_key,
        "pexels": settings.pexels_api_key,
        "pixabay": settings.pixabay_api_key,
        "unsplash": settings.unsplash_access_key,
        "google_tts": settings.google_tts_credentials,
    }.get(provider, "")


def _default_model(settings, provider: str) -> str:
    return {
        "gemini": settings.gemini_model,
        "groq": settings.groq_model,
        "openai": settings.llm_model,
        "anthropic": settings.anthropic_model,
    }.get(provider, "")
