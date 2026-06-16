from __future__ import annotations

from dataclasses import dataclass

from modules.llm.anthropic_provider import AnthropicProvider
from modules.llm.gemini_provider import GeminiProvider
from modules.llm.groq_provider import GroqProvider
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
    """Create the best JSON LLM provider from one generic or provider key."""
    provider = (config.provider or "auto").strip().lower()

    if provider in {"anthropic", "claude"}:
        key = config.api_key or config.anthropic_api_key
        return AnthropicProvider(key, config.model or config.anthropic_model)

    if provider in {"gemini", "google"}:
        key = config.api_key or config.gemini_api_key
        return GeminiProvider(key, config.model or config.gemini_model)

    if provider == "groq":
        key = config.api_key or config.groq_api_key
        return GroqProvider(key, config.model or config.groq_model)

    if provider != "auto":
        raise ValueError(f"Unsupported LLM_PROVIDER: {config.provider}")

    generic_key = config.api_key.strip()
    if generic_key:
        return _provider_from_key(generic_key, config.model, config)

    providers: list[LLMProvider] = []
    if config.gemini_api_key:
        providers.append(GeminiProvider(config.gemini_api_key, config.model or config.gemini_model))
    if config.anthropic_api_key:
        providers.append(AnthropicProvider(config.anthropic_api_key, config.model or config.anthropic_model))
    if config.groq_api_key:
        providers.append(GroqProvider(config.groq_api_key, config.model or config.groq_model))
    if providers:
        return FallbackProvider(providers)
    raise RuntimeError(
        "No online LLM API key configured; set ANTHROPIC_API_KEY, GROQ_API_KEY, GEMINI_API_KEY, or LLM_API_KEY."
    )


def _provider_from_key(api_key: str, model: str, config: LLMConfig) -> LLMProvider:
    if api_key.startswith("sk-ant-"):
        return AnthropicProvider(api_key, model or config.anthropic_model)
    if api_key.startswith("gsk_"):
        return GroqProvider(api_key, model or config.groq_model)
    if api_key.startswith("AIza"):
        return GeminiProvider(api_key, model or config.gemini_model)
    raise ValueError("Could not infer LLM provider from LLM_API_KEY; set LLM_PROVIDER.")


def create_provider_from_key(api_key: str, model: str = "", provider: str = "auto") -> LLMProvider:
    """Convenience entry point for callers that only have a key string."""
    return create_llm_provider(LLMConfig(provider=provider, api_key=api_key, model=model))


class FallbackProvider(LLMProvider):
    name = "fallback"

    def __init__(self, providers: list[LLMProvider]):
        self.providers = providers

    def generate_json(self, system_prompt: str, user_prompt: str, max_output_tokens: int) -> dict:
        errors = []
        for provider in self.providers:
            try:
                return provider.generate_json(system_prompt, user_prompt, max_output_tokens)
            except Exception as exc:
                errors.append(f"{provider.name}: {exc}")
        raise RuntimeError("All configured LLM providers failed: " + "; ".join(errors))
