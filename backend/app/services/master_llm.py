from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.models import Message
from app.services.api_keys import user_key_env_overrides
from pipeline.agents.master_agent import build_agent_contracts, generation_constraints
from pipeline.agents.prompts.master_prompts import MASTER_SYSTEM_PROMPT


MAX_MASTER_OUTPUT_TOKENS = 1800


@dataclass(frozen=True)
class MasterLLMClient:
    provider: str
    model: str
    api_key: str

    def decide(
        self,
        *,
        message: str,
        history: list[Message],
        context: Any,
        base_genre: str,
        base_settings: dict[str, Any],
    ) -> dict[str, Any]:
        user_prompt = _build_master_user_prompt(
            message=message,
            history=history,
            context=context,
            base_genre=base_genre,
            base_settings=base_settings,
        )
        data = self._generate_json(MASTER_SYSTEM_PROMPT, user_prompt, MAX_MASTER_OUTPUT_TOKENS)
        _validate_master_decision(data)
        return data

    def _generate_json(self, system_prompt: str, user_prompt: str, max_output_tokens: int) -> dict[str, Any]:
        if self.provider == "openai":
            return _post_openai(self.api_key, self.model, system_prompt, user_prompt, max_output_tokens)
        if self.provider == "anthropic":
            return _post_anthropic(self.api_key, self.model, system_prompt, user_prompt, max_output_tokens)
        if self.provider == "gemini":
            return _post_gemini(self.api_key, self.model, system_prompt, user_prompt, max_output_tokens)
        if self.provider == "groq":
            return _post_groq(self.api_key, self.model, system_prompt, user_prompt, max_output_tokens)
        raise RuntimeError(f"Unsupported master LLM provider: {self.provider}")


def create_master_llm_client(db: Session, user_id: int) -> MasterLLMClient | None:
    """Create the global master LLM client from user keys or environment keys."""
    try:
        env = os.environ.copy()
        env.update(user_key_env_overrides(db, user_id))
        provider = _normalize_provider(env.get("LLM_PROVIDER", "auto"))

        if provider == "auto":
            for candidate in ("openai", "anthropic", "groq", "gemini"):
                client = _client_for_provider(candidate, env)
                if client:
                    return client
            generic_key = env.get("LLM_API_KEY", "").strip()
            if generic_key:
                return _client_from_generic_key(generic_key, env.get("LLM_MODEL", ""), env)
            return None

        return _client_for_provider(provider, env)
    except Exception:
        return None


def _client_for_provider(provider: str, env: dict[str, str]) -> MasterLLMClient | None:
    key_map = {
        "openai": "OPENAI_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
        "gemini": "GEMINI_API_KEY",
        "groq": "GROQ_API_KEY",
    }
    model_map = {
        "openai": ("OPENAI_MODEL", "gpt-4o-mini"),
        "anthropic": ("ANTHROPIC_MODEL", "claude-3-5-haiku-20241022"),
        "gemini": ("GEMINI_MODEL", "gemini-2.5-flash"),
        "groq": ("GROQ_MODEL", "openai/gpt-oss-20b"),
    }
    key = _env_value(env, key_map.get(provider, ""), _provider_key_aliases(provider))
    if not key:
        generic_key = env.get("LLM_API_KEY", "").strip()
        if generic_key:
            return _client_from_generic_key(generic_key, env.get("LLM_MODEL", ""), env)
        return None
    model_env, default_model = model_map[provider]
    model = env.get("LLM_MODEL", "").strip() or env.get(model_env, "").strip() or default_model
    return MasterLLMClient(provider=provider, model=model, api_key=key)


def _provider_key_aliases(provider: str) -> tuple[str, ...]:
    if provider == "gemini":
        return ("GEMINI_API_KEYS",)
    return ()


def _env_value(env: dict[str, str], key: str, aliases: tuple[str, ...] = ()) -> str:
    value = env.get(key, "").strip() if key else ""
    if value:
        return value
    for alias in aliases:
        alias_value = env.get(alias, "").strip()
        if alias_value:
            return _first_csv_value(alias_value)
    return ""


def _first_csv_value(value: str) -> str:
    return next((item.strip() for item in value.split(",") if item.strip()), "")


def _client_from_generic_key(api_key: str, model: str, env: dict[str, str]) -> MasterLLMClient:
    if api_key.startswith("sk-ant-"):
        return MasterLLMClient("anthropic", model or env.get("ANTHROPIC_MODEL", "claude-3-5-haiku-20241022"), api_key)
    if api_key.startswith("gsk_"):
        return MasterLLMClient("groq", model or env.get("GROQ_MODEL", "openai/gpt-oss-20b"), api_key)
    if api_key.startswith("AIza"):
        return MasterLLMClient("gemini", model or env.get("GEMINI_MODEL", "gemini-2.5-flash"), api_key)
    if api_key.startswith("sk-"):
        return MasterLLMClient("openai", model or env.get("OPENAI_MODEL", "gpt-4o-mini"), api_key)
    raise RuntimeError("Could not infer master LLM provider from LLM_API_KEY")


def _normalize_provider(provider: str) -> str:
    selected = (provider or "auto").strip().lower()
    if selected in {"chatgpt"}:
        return "openai"
    if selected in {"claude"}:
        return "anthropic"
    if selected in {"google"}:
        return "gemini"
    if selected in {"auto", "openai", "anthropic", "gemini", "groq"}:
        return selected
    return "auto"


def _build_master_user_prompt(
    *,
    message: str,
    history: list[Message],
    context: Any,
    base_genre: str,
    base_settings: dict[str, Any],
) -> str:
    contracts = build_agent_contracts(base_settings, genre_id=base_genre, duration=int(base_settings.get("duration", 30)))
    constraints = generation_constraints(base_settings, genre_id=base_genre, duration=int(base_settings.get("duration", 30)))
    payload = {
        "latest_user_message": _redact(message),
        "recent_chat_history": [
            {"role": item.role, "content": _redact(item.content[:800])}
            for item in history[-8:]
        ],
        "context": {
            "onboarding_complete": bool(getattr(context, "onboarding_complete", False)),
            "selected_genre_id": getattr(context, "genre_id", base_genre) or base_genre,
            "user_intent": _redact(getattr(context, "user_intent", "") or ""),
            "calibration_notes": _redact(getattr(context, "calibration_notes", "") or ""),
            "preferred_script_excerpt": _redact((getattr(context, "preferred_script", "") or "")[:900]),
            "latest_generation_topic": _redact(getattr(context, "latest_generation_topic", "") or ""),
            "latest_generation_job_id": getattr(context, "latest_generation_job_id", "") or "",
            "latest_generation_settings": getattr(context, "latest_generation_settings", None) or {},
            "feedback_notes": [_redact(str(item)) for item in (getattr(context, "feedback_notes", None) or [])[:5]],
        },
        "base_genre": base_genre,
        "base_settings": base_settings,
        "base_constraints": constraints,
        "available_agent_contracts": contracts,
        "decision_hints": [
            "Generate only when the user clearly asks for a video/short/story/render or asks to change a previous video.",
            "If the user says hi/how are you/what can you do, use chat.",
            "If a generation topic is vague, ask one clarifying question.",
            "If changing an existing video, reuse latest_generation_topic unless the user gives a new topic.",
        ],
    }
    return json.dumps(payload, ensure_ascii=True, indent=2)


def _validate_master_decision(data: dict[str, Any]) -> None:
    if not isinstance(data, dict):
        raise ValueError("master decision must be a JSON object")
    intent = str(data.get("intent") or "")
    if intent not in {"chat", "ask_clarifying_question", "save_preference", "generate_video"}:
        raise ValueError(f"unsupported master intent: {intent}")
    if not str(data.get("assistant_message") or "").strip():
        raise ValueError("assistant_message is required")
    if data.get("settings") is not None and not isinstance(data.get("settings"), dict):
        raise ValueError("settings must be an object")
    if data.get("agent_tasks") is not None and not isinstance(data.get("agent_tasks"), list):
        raise ValueError("agent_tasks must be an array")


def _post_openai(api_key: str, model: str, system_prompt: str, user_prompt: str, max_output_tokens: int) -> dict[str, Any]:
    return _post_chat_completions(
        url="https://api.openai.com/v1/chat/completions",
        api_key=api_key,
        model=model,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        max_output_tokens=max_output_tokens,
        provider_label="OpenAI",
    )


def _post_groq(api_key: str, model: str, system_prompt: str, user_prompt: str, max_output_tokens: int) -> dict[str, Any]:
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError("OpenAI SDK is required for Groq; install the openai package") from exc

    client = OpenAI(api_key=api_key, base_url="https://api.groq.com/openai/v1")
    try:
        response = client.responses.create(
            model=model,
            input=[
                {"role": "system", "content": _strict_system(system_prompt)},
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
        content = _groq_chat_completion_fallback(client, model, system_prompt, user_prompt, max_output_tokens, exc)
    data = _parse_json_object(content)
    _validate_master_decision(data)
    return data


def _post_chat_completions(
    *,
    url: str,
    api_key: str,
    model: str,
    system_prompt: str,
    user_prompt: str,
    max_output_tokens: int,
    provider_label: str,
) -> dict[str, Any]:
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": _strict_system(system_prompt)},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.2,
        "max_tokens": max_output_tokens,
        "response_format": {"type": "json_object"},
    }
    data = _post_json(url, body, {"Authorization": f"Bearer {api_key}"}, provider_label)
    choices = data.get("choices", [])
    if not choices:
        raise RuntimeError(f"{provider_label} API returned no choices")
    content = choices[0].get("message", {}).get("content", "")
    return _parse_json_object(content)


def _groq_chat_completion_fallback(
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
                {"role": "system", "content": _strict_system(system_prompt)},
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


def _post_anthropic(api_key: str, model: str, system_prompt: str, user_prompt: str, max_output_tokens: int) -> dict[str, Any]:
    body = {
        "model": model,
        "max_tokens": max_output_tokens,
        "temperature": 0.2,
        "system": _strict_system(system_prompt),
        "messages": [{"role": "user", "content": user_prompt}],
    }
    data = _post_json(
        "https://api.anthropic.com/v1/messages",
        body,
        {"x-api-key": api_key, "anthropic-version": "2023-06-01"},
        "Anthropic",
    )
    text = "\n".join(
        block.get("text", "")
        for block in data.get("content", [])
        if isinstance(block, dict) and block.get("type") == "text"
    )
    return _parse_json_object(text)


def _post_gemini(api_key: str, model: str, system_prompt: str, user_prompt: str, max_output_tokens: int) -> dict[str, Any]:
    quoted_model = urllib.parse.quote(model, safe="")
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/{quoted_model}:generateContent"
        f"?key={urllib.parse.quote(api_key, safe='')}"
    )
    body = {
        "contents": [{"parts": [{"text": user_prompt}]}],
        "generationConfig": {
            "temperature": 0.2,
            "maxOutputTokens": max_output_tokens,
            "responseMimeType": "application/json",
        },
        "systemInstruction": {"parts": [{"text": _strict_system(system_prompt)}]},
    }
    data = _post_json(url, body, {}, "Gemini")
    parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
    text = "\n".join(str(part.get("text", "")) for part in parts if isinstance(part, dict))
    return _parse_json_object(text)


def _post_json(url: str, payload: dict[str, Any], headers: dict[str, str], provider_label: str) -> dict[str, Any]:
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
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:800]
        raise RuntimeError(f"{provider_label} master LLM returned HTTP {exc.code}: {body}") from exc


def _strict_system(system_prompt: str) -> str:
    return (
        "STRICT JSON CONTRACT:\n"
        "- Return exactly one JSON object and nothing else.\n"
        "- No markdown, comments, prose outside JSON, or code fences.\n"
        "- Use double quotes for every key and string value.\n"
        "- Do not include trailing commas.\n\n"
        f"{system_prompt}"
    )


def _parse_json_object(text: str) -> dict[str, Any]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text or "", flags=re.DOTALL)
        if not match:
            raise ValueError("master LLM did not return a JSON object")
        data = json.loads(match.group(0))
    if not isinstance(data, dict):
        raise ValueError("master LLM returned non-object JSON")
    return data


def _redact(text: str) -> str:
    cleaned = str(text or "")
    cleaned = re.sub(r"sk-[A-Za-z0-9_-]{12,}", "[REDACTED_KEY]", cleaned)
    cleaned = re.sub(r"sk-ant-[A-Za-z0-9_-]{12,}", "[REDACTED_KEY]", cleaned)
    cleaned = re.sub(r"gsk_[A-Za-z0-9_-]{12,}", "[REDACTED_KEY]", cleaned)
    cleaned = re.sub(r"AIza[A-Za-z0-9_-]{12,}", "[REDACTED_KEY]", cleaned)
    return cleaned
