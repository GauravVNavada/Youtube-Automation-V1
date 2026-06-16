from __future__ import annotations

import base64
import hashlib
import json
import os
import urllib.error
import urllib.parse
import urllib.request

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import UserApiKey, utc_now


PROVIDERS = (
    "openai",
    "gemini",
    "anthropic",
    "groq",
    "google_tts",
    "pexels",
    "pixabay",
    "freesound",
)

ENV_MAP = {
    "openai": "OPENAI_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "groq": "GROQ_API_KEY",
    "google_tts": "GOOGLE_TTS_CREDENTIALS",
    "pexels": "PEXELS_API_KEY",
    "pixabay": "PIXABAY_API_KEY",
    "freesound": "FREESOUND_API_KEY",
}

ENV_ALIASES = {
    "gemini": ("GEMINI_API_KEYS",),
    "google_tts": ("TTS_CREDENTIALS_PATH", "GOOGLE_APPLICATION_CREDENTIALS"),
}

MODEL_ENV_MAP = {
    "openai": "OPENAI_MODEL",
    "gemini": "GEMINI_MODEL",
    "anthropic": "ANTHROPIC_MODEL",
    "groq": "GROQ_MODEL",
}

LLM_PROVIDERS = ("openai", "anthropic", "gemini", "groq")

LLM_MODEL_OPTIONS = {
    "openai": ["gpt-4o-mini", "gpt-4o", "gpt-4.1-mini", "gpt-4.1"],
    "anthropic": [
        "claude-3-5-haiku-20241022",
        "claude-3-5-sonnet-20241022",
        "claude-3-7-sonnet-20250219",
        "claude-sonnet-4-20250514",
    ],
    "gemini": ["gemini-2.5-flash", "gemini-2.5-pro", "gemini-1.5-flash", "gemini-1.5-pro"],
    "groq": ["openai/gpt-oss-20b", "llama-3.3-70b-versatile", "llama-3.1-8b-instant", "llama3-70b-8192", "mixtral-8x7b-32768"],
}

DEFAULT_MODEL = {provider: models[0] for provider, models in LLM_MODEL_OPTIONS.items()}


def save_api_key(db: Session, user_id: int, provider: str, value: str, model: str = "") -> UserApiKey:
    provider = normalize_provider(provider)
    record = db.scalar(select(UserApiKey).where(UserApiKey.user_id == user_id, UserApiKey.provider == provider))
    if not record:
        record = UserApiKey(user_id=user_id, provider=provider)
        db.add(record)
    model_name = normalize_model(provider, model)
    record.encrypted_value = encrypt_secret(value.strip()) if value.strip() else ""
    record.model_name = model_name
    record.status = test_api_key(provider, value.strip(), model_name)
    record.last_tested_at = utc_now()
    record.updated_at = utc_now()
    db.commit()
    db.refresh(record)
    return record


def list_key_statuses(db: Session, user_id: int) -> list[dict]:
    records = {
        record.provider: record
        for record in db.scalars(select(UserApiKey).where(UserApiKey.user_id == user_id))
    }
    statuses: list[dict] = []
    for provider in PROVIDERS:
        record = records.get(provider)
        env_value = _env_value_for_provider(provider)
        if record and record.encrypted_value:
            statuses.append(
                {
                    "provider": provider,
                    "configured": True,
                    "status": record.status,
                    "source": "user",
                    "model": record.model_name or default_model(provider),
                    "last_tested_at": record.last_tested_at,
                }
            )
        else:
            model = os.getenv(MODEL_ENV_MAP.get(provider, ""), "") or default_model(provider)
            statuses.append(
                {
                    "provider": provider,
                    "configured": bool(env_value),
                    "status": "passed" if env_value else "missing",
                    "source": "env" if env_value else "none",
                    "model": model,
                    "last_tested_at": None,
                }
            )
    return statuses


def api_setup_complete(statuses: list[dict]) -> tuple[bool, dict[str, bool]]:
    by_provider = {item["provider"]: item for item in statuses}
    required = {
        "llm": any(_is_green(by_provider.get(provider)) for provider in LLM_PROVIDERS),
        "narration": True,
        "image_provider": True,
    }
    optional = {
        "google_tts": _is_green(by_provider.get("google_tts")),
        "stock_video": _is_green(by_provider.get("pexels")),
        "premium_image_provider": any(_is_green(by_provider.get(provider)) for provider in ("pexels", "pixabay")),
    }
    return required["llm"], {**required, **optional}


def user_key_env_overrides(db: Session, user_id: int) -> dict[str, str]:
    overrides: dict[str, str] = {}
    selected_llm: UserApiKey | None = None
    records = list(db.scalars(select(UserApiKey).where(UserApiKey.user_id == user_id).order_by(UserApiKey.updated_at.desc())))
    for record in records:
        if record.status != "passed":
            continue
        env_name = ENV_MAP.get(record.provider)
        if not env_name or not record.encrypted_value:
            continue
        value = decrypt_secret(record.encrypted_value)
        if value:
            overrides[env_name] = value
            model_env = MODEL_ENV_MAP.get(record.provider)
            if model_env and record.model_name:
                overrides[model_env] = record.model_name
            if record.provider in LLM_PROVIDERS and not selected_llm:
                selected_llm = record
    if selected_llm:
        overrides["LLM_PROVIDER"] = selected_llm.provider
        overrides["LLM_MODEL"] = selected_llm.model_name or default_model(selected_llm.provider)
    return overrides


def llm_options() -> list[dict]:
    return [
        {"provider": provider, "label": llm_label(provider), "models": models, "default_model": models[0]}
        for provider, models in LLM_MODEL_OPTIONS.items()
    ]


def normalize_provider(provider: str) -> str:
    normalized = provider.strip().lower()
    if normalized not in PROVIDERS:
        raise ValueError(f"Unsupported API key provider: {provider}")
    return normalized


def normalize_model(provider: str, model: str) -> str:
    if provider not in LLM_PROVIDERS:
        return ""
    selected = model.strip()
    return selected or default_model(provider)


def default_model(provider: str) -> str:
    return DEFAULT_MODEL.get(provider, "")


def llm_label(provider: str) -> str:
    return {
        "openai": "OpenAI / ChatGPT",
        "anthropic": "Claude",
        "gemini": "Gemini",
        "groq": "Groq",
    }.get(provider, provider.title())


def _env_value_for_provider(provider: str) -> str:
    canonical = os.getenv(ENV_MAP.get(provider, ""), "").strip()
    if canonical:
        return canonical
    for alias in ENV_ALIASES.get(provider, ()):
        value = os.getenv(alias, "").strip()
        if value:
            return _first_csv_value(value) if provider == "gemini" else value
    return ""


def _first_csv_value(value: str) -> str:
    return next((item.strip() for item in value.split(",") if item.strip()), "")


def test_api_key(provider: str, value: str, model: str = "") -> str:
    if not value:
        return "missing"
    provider = normalize_provider(provider)
    if provider == "google_tts":
        return "passed" if value.endswith(".json") or value.strip().startswith("{") else "needs_json_or_path"
    if provider in {"pexels", "pixabay", "freesound"}:
        return "passed" if len(value) >= 12 else "too_short"
    if provider in LLM_PROVIDERS:
        if len(value) < 16:
            return "too_short"
        return test_llm_api_key(provider, value, normalize_model(provider, model))
    return "passed"


def test_llm_api_key(provider: str, value: str, model: str) -> str:
    try:
        if provider == "openai":
            return _post_json(
                "https://api.openai.com/v1/chat/completions",
                {
                    "model": model,
                    "messages": [
                        {"role": "system", "content": "Return compact JSON only."},
                        {"role": "user", "content": "Return {\"ok\": true}."},
                    ],
                    "temperature": 0,
                    "max_tokens": 20,
                    "response_format": {"type": "json_object"},
                },
                {"Authorization": f"Bearer {value}"},
            )
        if provider == "anthropic":
            return _post_json(
                "https://api.anthropic.com/v1/messages",
                {
                    "model": model,
                    "max_tokens": 20,
                    "temperature": 0,
                    "system": "Return compact JSON only.",
                    "messages": [{"role": "user", "content": "Return {\"ok\": true}."}],
                },
                {"x-api-key": value, "anthropic-version": "2023-06-01"},
            )
        if provider == "gemini":
            quoted_model = urllib.parse.quote(model, safe="")
            return _post_json(
                f"https://generativelanguage.googleapis.com/v1beta/models/{quoted_model}:generateContent?key={urllib.parse.quote(value, safe='')}",
                {
                    "contents": [{"parts": [{"text": "Return {\"ok\": true}."}]}],
                    "generationConfig": {
                        "temperature": 0,
                        "maxOutputTokens": 20,
                        "responseMimeType": "application/json",
                    },
                },
                {},
            )
        if provider == "groq":
            return _test_groq_api_key(value, model)
    except urllib.error.HTTPError as exc:
        return f"http_{exc.code}: {_short_error(exc.read().decode('utf-8', errors='replace'))}"
    except Exception as exc:
        return f"error: {_short_error(str(exc))}"
    return "unsupported_provider"


def _test_groq_api_key(value: str, model: str) -> str:
    try:
        from openai import OpenAI
    except ImportError:
        return "openai_sdk_missing"
    try:
        client = OpenAI(api_key=value, base_url="https://api.groq.com/openai/v1")
        response = client.responses.create(
            model=model,
            input="Return {\"ok\": true}.",
            temperature=0,
            max_output_tokens=128,
            reasoning={"effort": "low"},
        )
        if getattr(response, "output_text", ""):
            return "passed"
        chat_response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "Return {\"ok\": true}."}],
            temperature=0,
            max_tokens=64,
            response_format={"type": "json_object"},
        )
        return "passed" if chat_response.choices and chat_response.choices[0].message.content else "empty_response"
    except Exception as exc:
        return f"error: {_short_error(str(exc))}"


def _post_json(url: str, payload: dict, headers: dict[str, str]) -> str:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "User-Agent": "DesktopApp/1.0 (+https://localhost)",
            **headers,
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=25) as response:
        body = json.loads(response.read().decode("utf-8") or "{}")
    if not body:
        return "empty_response"
    return "passed"


def _short_error(value: str) -> str:
    compact = " ".join(value.strip().split())
    return compact[:220] if compact else "unknown_error"


def encrypt_secret(value: str) -> str:
    return _fernet().encrypt(value.encode("utf-8")).decode("utf-8")


def decrypt_secret(value: str) -> str:
    try:
        return _fernet().decrypt(value.encode("utf-8")).decode("utf-8")
    except InvalidToken:
        return ""


def _is_green(status: dict | None) -> bool:
    return bool(status and status.get("configured") and status.get("status") == "passed")


def _fernet() -> Fernet:
    settings = get_settings()
    digest = hashlib.sha256(settings.jwt_secret.encode("utf-8")).digest()
    key = base64.urlsafe_b64encode(digest)
    return Fernet(key)
