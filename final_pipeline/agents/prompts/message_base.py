from __future__ import annotations

import json
from typing import Any, Iterable, Mapping


Message = dict[str, str]


def clean_text(value: Any, limit: int) -> str:
    value = "" if value is None else str(value)
    value = value.replace("\x00", " ")
    value = " ".join(value.split())
    return value[:limit].strip()


def clean_list(values: Iterable[Any] | None, item_limit: int, max_items: int) -> list[str]:
    if not values:
        return []

    result: list[str] = []
    for value in list(values)[:max_items]:
        text = clean_text(value, item_limit)
        if text:
            result.append(text)
    return result


def compact_json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def normalize_messages(messages: Iterable[Mapping[str, Any]]) -> list[Message]:
    normalized: list[Message] = []
    for item in messages:
        role = clean_text(item.get("role", ""), 40)
        content = str(item.get("content", "")).strip()
        if role and content:
            normalized.append({"role": role, "content": content})
    return normalized


def base_messages(
    system_prompt: str,
    examples: Iterable[Mapping[str, Any]] | None = None,
) -> list[Message]:
    return normalize_messages(
        [{"role": "system", "content": system_prompt}, *(examples or [])]
    )


def append_user_message(
    messages: Iterable[Mapping[str, Any]],
    content: str,
    limit: int | None = None,
) -> list[Message]:
    text = str(content if limit is None else content[:limit]).strip()
    return normalize_messages(messages) + [{"role": "user", "content": text}]


def render_messages_for_single_prompt(messages: Iterable[Mapping[str, Any]]) -> str:
    return "\n\n".join(
        f"{item['role'].upper()}:\n{item['content']}"
        for item in normalize_messages(messages)
    )
