from __future__ import annotations

from modules.llm.json_utils import parse_llm_json
from modules.llm.providers import LLMProvider


class GroqProvider(LLMProvider):
    """Groq provider using the OpenAI-compatible SDK client."""

    name = "groq"

    def __init__(self, api_key: str, model: str = "openai/gpt-oss-20b"):
        self.api_key = api_key
        self.model = model

    def generate_json(
        self,
        system_prompt: str,
        user_prompt: str,
        max_output_tokens: int,
    ) -> dict:
        if not self.api_key:
            raise RuntimeError("Groq API key is not configured")

        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError("OpenAI SDK is required for Groq; install the openai package") from exc

        client = OpenAI(api_key=self.api_key, base_url="https://api.groq.com/openai/v1")
        try:
            response = client.responses.create(
                model=self.model,
                input=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.2,
                max_output_tokens=max(256, max_output_tokens),
                reasoning={"effort": "low"},
            )
            content = getattr(response, "output_text", "") or ""
            if not content.strip():
                raise RuntimeError("Groq Responses API returned no final text")
        except Exception as exc:
            content = _generate_with_chat_completions(client, self.model, system_prompt, user_prompt, max_output_tokens, exc)
        return parse_llm_json(content)


def _generate_with_chat_completions(
    client,
    model: str,
    system_prompt: str,
    user_prompt: str,
    max_output_tokens: int,
    original_exc: Exception,
) -> str:
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.2,
            max_tokens=max_output_tokens,
            response_format={"type": "json_object"},
        )
    except Exception as fallback_exc:
        raise RuntimeError(
            f"Groq API failed via Responses API ({original_exc}) and chat completions fallback ({fallback_exc})"
        ) from fallback_exc
    choices = getattr(response, "choices", []) or []
    if not choices:
        raise RuntimeError("Groq API returned no choices")
    return choices[0].message.content or ""
