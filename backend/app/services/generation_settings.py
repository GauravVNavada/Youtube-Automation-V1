from __future__ import annotations

import re
from typing import Any


MIN_DURATION_SECONDS = 10
MAX_DURATION_SECONDS = 180
MIN_VOICE_SPEED = 0.65
MAX_VOICE_SPEED = 1.4

DEFAULT_GENERATION_SETTINGS: dict[str, Any] = {
    "duration": 30,
    "voice_speed": 1.0,
    "caption_words": 4,
    "image_count": 8,
    "music_volume": 0.18,
    "schedule": "now",
}

_DURATION_RE = re.compile(r"\b([1-9]\d{0,2})\s*(?:second|seconds|sec|secs|s)\b", re.IGNORECASE)
_VOICE_SPEED_RE = re.compile(
    r"\b(?:voice\s*speed|speaking\s*rate|speed)\s*(?:is|=|:)?\s*(0\.\d+|1(?:\.\d+)?|1\.4)\s*x?\b",
    re.IGNORECASE,
)
_CAPTION_WORDS_RE = re.compile(r"\b(?:caption\s*words|words\s*per\s*caption)\s*(?:is|=|:)?\s*([1-9]\d?)\b", re.IGNORECASE)
_IMAGE_COUNT_RE = re.compile(r"\b([1-9]\d?)\s*(?:images|frames|visuals|photos)\b", re.IGNORECASE)
_MUSIC_VOLUME_RE = re.compile(r"\b(?:music\s*volume|bgm\s*volume)\s*(?:is|=|:)?\s*(0(?:\.\d+)?|0?\.?\d+)\b", re.IGNORECASE)


def normalize_generation_settings(
    settings: dict[str, Any] | None = None,
    text: str = "",
    prefer_text: bool = False,
) -> dict[str, Any]:
    normalized = dict(DEFAULT_GENERATION_SETTINGS)
    normalized.update({key: value for key, value in (settings or {}).items() if value is not None})

    parsed_duration = extract_duration_seconds(text)
    if parsed_duration is not None and prefer_text:
        normalized["duration"] = parsed_duration

    parsed_voice_speed = extract_voice_speed(text)
    if parsed_voice_speed is not None and prefer_text:
        normalized["voice_speed"] = parsed_voice_speed

    caption_words = _extract_int(_CAPTION_WORDS_RE, text)
    if caption_words is not None and prefer_text:
        normalized["caption_words"] = caption_words

    image_count = _extract_int(_IMAGE_COUNT_RE, text)
    if image_count is not None and prefer_text:
        normalized["image_count"] = image_count

    music_volume = _extract_float(_MUSIC_VOLUME_RE, text)
    if music_volume is not None and prefer_text:
        normalized["music_volume"] = music_volume

    if prefer_text:
        lowered = text.lower()
        if parsed_voice_speed is None and any(word in lowered for word in ("slower voice", "slow voice", "speak slower")):
            normalized["voice_speed"] = 0.9
        if parsed_voice_speed is None and any(word in lowered for word in ("faster voice", "fast voice", "speak faster")):
            normalized["voice_speed"] = 1.1

    normalized["duration"] = _clamp_int(normalized.get("duration"), MIN_DURATION_SECONDS, MAX_DURATION_SECONDS, DEFAULT_GENERATION_SETTINGS["duration"])
    normalized["voice_speed"] = _clamp_float(normalized.get("voice_speed"), MIN_VOICE_SPEED, MAX_VOICE_SPEED, DEFAULT_GENERATION_SETTINGS["voice_speed"])
    normalized["caption_words"] = _clamp_int(normalized.get("caption_words"), 1, 10, DEFAULT_GENERATION_SETTINGS["caption_words"])
    normalized["image_count"] = _clamp_int(normalized.get("image_count"), 3, 24, DEFAULT_GENERATION_SETTINGS["image_count"])
    normalized["music_volume"] = _clamp_float(normalized.get("music_volume"), 0.0, 0.8, DEFAULT_GENERATION_SETTINGS["music_volume"])
    normalized["schedule"] = str(normalized.get("schedule") or "now")
    return normalized


def extract_duration_seconds(text: str) -> int | None:
    match = _DURATION_RE.search(text or "")
    if not match:
        return None
    return _clamp_int(match.group(1), MIN_DURATION_SECONDS, MAX_DURATION_SECONDS, DEFAULT_GENERATION_SETTINGS["duration"])


def extract_voice_speed(text: str) -> float | None:
    return _extract_float(_VOICE_SPEED_RE, text)


def _extract_int(pattern: re.Pattern[str], text: str) -> int | None:
    match = pattern.search(text or "")
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def _extract_float(pattern: re.Pattern[str], text: str) -> float | None:
    match = pattern.search(text or "")
    if not match:
        return None
    try:
        return float(match.group(1))
    except ValueError:
        return None


def _clamp_int(value: Any, minimum: int, maximum: int, fallback: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = fallback
    return max(minimum, min(maximum, number))


def _clamp_float(value: Any, minimum: float, maximum: float, fallback: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = fallback
    return round(max(minimum, min(maximum, number)), 3)
