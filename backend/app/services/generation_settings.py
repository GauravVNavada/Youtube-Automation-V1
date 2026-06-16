from __future__ import annotations

from typing import Any


MIN_DURATION_SECONDS = 15
MAX_DURATION_SECONDS = 120
MIN_VOICE_SPEED = 0.75
MAX_VOICE_SPEED = 1.4

DEFAULT_GENERATION_SETTINGS: dict[str, Any] = {
    "duration": 30,
    "voice_speed": 1.0,
    "caption_words": 4,
    "image_count": 8,
    "music_volume": 0.18,
    "schedule": "now",
}


def normalize_generation_settings(settings: dict[str, Any] | None) -> dict[str, Any]:
    data = {**DEFAULT_GENERATION_SETTINGS, **(settings or {})}
    data["duration"] = _clamp_int(data.get("duration"), MIN_DURATION_SECONDS, MAX_DURATION_SECONDS, 30)
    data["voice_speed"] = _clamp_float(data.get("voice_speed"), MIN_VOICE_SPEED, MAX_VOICE_SPEED, 1.0)
    data["caption_words"] = _clamp_int(data.get("caption_words"), 1, 10, 4)
    data["image_count"] = _clamp_int(data.get("image_count"), 3, 24, 8)
    data["music_volume"] = _clamp_float(data.get("music_volume"), 0.0, 0.8, 0.18)
    data["schedule"] = str(data.get("schedule") or "now")
    return data


def _clamp_int(value: Any, low: int, high: int, default: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return max(low, min(high, number))


def _clamp_float(value: Any, low: float, high: float, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    return max(low, min(high, number))
