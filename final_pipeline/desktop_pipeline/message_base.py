from __future__ import annotations

import json
from typing import Any, Iterable, Mapping


Message = dict[str, str]


def clean_text(value: Any, limit: int = 6000) -> str:
    value = "" if value is None else str(value)
    value = value.replace("\x00", " ")
    return " ".join(value.split())[:limit].strip()


def compact_json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=True, separators=(",", ":"))


def normalize_messages(messages: Iterable[Mapping[str, Any]]) -> list[Message]:
    normalized: list[Message] = []
    for item in messages:
        role = clean_text(item.get("role", ""), 40)
        content = str(item.get("content", "")).strip()
        if role and content:
            normalized.append({"role": role, "content": content})
    return normalized


def base_messages(system_prompt: str, examples: Iterable[Mapping[str, Any]] | None = None) -> list[Message]:
    return normalize_messages([{"role": "system", "content": system_prompt}, *(examples or [])])


def render_messages_for_single_prompt(messages: Iterable[Mapping[str, Any]]) -> str:
    return "\n\n".join(
        f"{item['role'].upper()}:\n{item['content']}"
        for item in normalize_messages(messages)
    )


def system_prompt_with_examples(system_prompt: str, examples: Iterable[Mapping[str, Any]] | None = None) -> str:
    return render_messages_for_single_prompt(base_messages(system_prompt, examples))
