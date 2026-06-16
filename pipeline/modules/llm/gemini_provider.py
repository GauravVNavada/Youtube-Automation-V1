from __future__ import annotations

import json
import re

from modules.llm.providers import LLMProvider


class GeminiProvider(LLMProvider):
    """Optional Gemini provider.

    Max token usage is controlled per call by the caller-provided
    max_output_tokens. Script calls use 1200 tokens; asset rewrites use 80.
    """

    name = "gemini"

    def __init__(self, api_key: str, model: str = "gemini-2.5-flash"):
        self.api_key = api_key
        self.model = model

    def generate_json(
        self,
        system_prompt: str,
        user_prompt: str,
        max_output_tokens: int,
    ) -> dict:
        if not self.api_key:
            raise RuntimeError("Gemini API key is not configured")
        from google import genai

        client = genai.Client(api_key=self.api_key)
        response = client.models.generate_content(
            model=self.model,
            contents=user_prompt,
            config={
                "system_instruction": system_prompt,
                "temperature": 0.8,
                "max_output_tokens": max_output_tokens,
                "response_mime_type": "application/json",
            },
        )
        return _parse_json(response.text or "")


def _parse_json(text: str) -> dict:
    cleaned = text.strip()
    cleaned = re.sub(r"```(?:json)?|```", "", cleaned).strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start >= 0 and end >= start:
        cleaned = cleaned[start : end + 1]
    return json.loads(cleaned)
