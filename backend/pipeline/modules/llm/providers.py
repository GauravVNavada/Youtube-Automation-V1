from __future__ import annotations

from abc import ABC, abstractmethod


class LLMProvider(ABC):
    """Simple provider interface for JSON-focused LLM calls."""

    name = "base"

    @abstractmethod
    def generate_json(
        self,
        system_prompt: str,
        user_prompt: str,
        max_output_tokens: int,
    ) -> dict:
        raise NotImplementedError
