from __future__ import annotations

from typing import Any

from app.core.config import get_settings
from app.services.api_keys import user_key_env_overrides
from desktop_pipeline.master_agent import MasterAgent


def decide_next_action(
    message: str,
    fallback_genre: str = "scary_stories",
    *,
    chat_history: list[dict[str, Any]] | None = None,
    latest_job: dict[str, Any] | None = None,
    calibration: dict[str, Any] | None = None,
    feedback: list[dict[str, Any]] | None = None,
    provider: Any | None = None,
    require_provider: bool = False,
) -> dict[str, Any]:
    context = {
        "genre_id": fallback_genre,
        "user_intent": (calibration or {}).get("user_intent", ""),
        "chat_history": chat_history or [],
        "latest_job": latest_job or {},
        "calibration": calibration or {},
        "feedback": feedback or [],
    }
    decision = MasterAgent(provider=provider, require_provider=require_provider).decide(message, context)
    return decision.to_dict()


def gemini_provider_for_user(db, user_id: int):
    overrides = user_key_env_overrides(db, user_id)
    settings = get_settings()
    api_key = overrides.get("GEMINI_API_KEY") or overrides.get("LLM_API_KEY") or settings.gemini_api_key or settings.llm_api_key
    model = overrides.get("GEMINI_MODEL") or overrides.get("LLM_MODEL") or settings.gemini_model or settings.llm_model
    if not api_key:
        return None
    from modules.llm.factory import LLMConfig, create_llm_provider

    return create_llm_provider(
        LLMConfig(
            provider="gemini",
            api_key=api_key,
            model=model,
            gemini_api_key=api_key,
            gemini_model=model,
        )
    )
