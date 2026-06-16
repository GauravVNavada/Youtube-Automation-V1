from __future__ import annotations

import json
import urllib.error
import urllib.request

from modules.llm.json_utils import parse_llm_json
from modules.llm.providers import LLMProvider


class OpenAIProvider(LLMProvider):
    """OpenAI chat-completions provider for JSON-focused LLM calls."""

    name = "openai"

    def __init__(self, api_key: str, model: str = "gpt-4o-mini"):
        self.api_key = api_key
        self.model = model

    def generate_json(
        self,
        system_prompt: str,
        user_prompt: str,
        max_output_tokens: int,
    ) -> dict:
        if not self.api_key:
            raise RuntimeError("OpenAI API key is not configured")

        body = json.dumps(
            {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": 0.8,
                "max_tokens": max_output_tokens,
                "response_format": {"type": "json_object"},
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            "https://api.openai.com/v1/chat/completions",
            data=body,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"OpenAI API returned HTTP {exc.code}: {error_body}") from exc

        choices = data.get("choices", [])
        if not choices:
            raise RuntimeError("OpenAI API returned no choices")
        content = choices[0].get("message", {}).get("content", "")
        return parse_llm_json(content)
