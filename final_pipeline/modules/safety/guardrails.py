from __future__ import annotations

import re


GENERIC_CHAT_MESSAGES = {
    "hi",
    "hey",
    "hello",
    "thanks",
    "thank you",
    "how are you",
    "what are you doing",
    "what can you do",
}

SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_-]{20,}"),
    re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}"),
    re.compile(r"AIza[A-Za-z0-9_-]{20,}"),
    re.compile(r"gsk_[A-Za-z0-9_-]{20,}"),
    re.compile(r"[A-Za-z0-9]{20,}msh[A-Za-z0-9]{8,}"),
]


def is_generic_chat(text: str | None) -> bool:
    if not text:
        return True
    cleaned = re.sub(r"[^a-z\s]", "", text.lower()).strip()
    return cleaned in GENERIC_CHAT_MESSAGES


def redact_secrets(text: str | None) -> str:
    if not text:
        return ""
    redacted = text
    for pattern in SECRET_PATTERNS:
        redacted = pattern.sub("[REDACTED_SECRET]", redacted)
    return redacted


def validate_video_topic(topic: str | None) -> None:
    cleaned = (topic or "").strip()
    if is_generic_chat(cleaned) or len(cleaned.split()) < 3:
        raise RuntimeError("Video topic is too vague. Provide a concrete topic before running the pipeline.")


def validate_generated_text(text: str | None) -> None:
    value = text or ""
    for pattern in SECRET_PATTERNS:
        if pattern.search(value):
            raise RuntimeError("Generated text appears to contain an API key or secret.")
