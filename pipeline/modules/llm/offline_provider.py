from __future__ import annotations

from modules.llm.providers import LLMProvider


class OfflineProvider(LLMProvider):
    name = "offline"

    def generate_json(self, system_prompt: str, user_prompt: str, max_output_tokens: int) -> dict:
        raise NotImplementedError("OfflineProvider is intentionally disabled for production script generation")
