from __future__ import annotations

import json
import urllib.error
import urllib.request

from modules.llm.json_utils import parse_llm_json
from modules.llm.providers import LLMProvider


class AnthropicProvider(LLMProvider):
    """Optional Claude provider using Anthropic's Messages API."""

    name = "anthropic"

    def __init__(self, api_key: str, model: str = "claude-3-5-haiku-20241022"):
        self.api_key = api_key
        self.model = model

    def generate_json(
        self,
        system_prompt: str,
        user_prompt: str,
        max_output_tokens: int,
    ) -> dict:
        if not self.api_key:
            raise RuntimeError("Anthropic API key is not configured")

        body = json.dumps(
            {
                "model": self.model,
                "max_tokens": max_output_tokens,
                "temperature": 0.8,
                "system": system_prompt,
                "messages": [{"role": "user", "content": user_prompt}],
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            "https://api.anthropic.com/v1/messages",
            data=body,
            headers={
                "Content-Type": "application/json",
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Anthropic API returned HTTP {exc.code}: {error_body}") from exc

        text_parts = [
            block.get("text", "")
            for block in data.get("content", [])
            if isinstance(block, dict) and block.get("type") == "text"
        ]
        return parse_llm_json("\n".join(text_parts))
