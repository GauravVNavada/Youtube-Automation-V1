from __future__ import annotations

from dataclasses import dataclass

from modules.llm.gemini_provider import GeminiProvider
from modules.llm.providers import LLMProvider


@dataclass(frozen=True)
class LLMConfig:
    provider: str = "auto"
    api_key: str = ""
    model: str = ""
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-3-5-haiku-20241022"
    groq_api_key: str = ""
    groq_model: str = "llama-3.3-70b-versatile"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"


def create_llm_provider(config: LLMConfig) -> LLMProvider:
    """Create the JSON LLM provider. Production pipeline uses Gemini only."""
    provider = (config.provider or "auto").strip().lower()

    if provider in {"gemini", "google"}:
        key = config.api_key or config.gemini_api_key
        return GeminiProvider(key, config.model or config.gemini_model)

    if provider != "auto":
        raise ValueError(f"Unsupported LLM_PROVIDER: {config.provider}. Only Gemini is allowed.")

    generic_key = config.api_key.strip()
    if generic_key:
        return _provider_from_key(generic_key, config.model, config)

    if config.gemini_api_key:
        return GeminiProvider(config.gemini_api_key, config.model or config.gemini_model)
    raise RuntimeError("No Gemini API key configured; set GEMINI_API_KEY or LLM_API_KEY with LLM_PROVIDER=gemini.")


def _provider_from_key(api_key: str, model: str, config: LLMConfig) -> LLMProvider:
    if api_key.startswith("AIza"):
        return GeminiProvider(api_key, model or config.gemini_model)
    if (config.provider or "").strip().lower() in {"gemini", "google"}:
        return GeminiProvider(api_key, model or config.gemini_model)
    raise ValueError("LLM_API_KEY must be a Gemini key, or set LLM_PROVIDER=gemini.")


def create_provider_from_key(api_key: str, model: str = "", provider: str = "auto") -> LLMProvider:
    """Convenience entry point for callers that only have a key string."""
    return create_llm_provider(LLMConfig(provider=provider, api_key=api_key, model=model))
