from __future__ import annotations

from typing import Any

from app.services.generation_settings import normalize_generation_settings


PIPELINE_AGENT_NAMES = [
    "topic_discovery_agent",
    "research_agent",
    "script_agent",
    "validation_agent",
    "asset_agent",
    "audio_agent",
    "caption_agent",
    "render_agent",
    "thumbnail_agent",
]

ROUTE_AGENT_NAMES = ["master_agent", *PIPELINE_AGENT_NAMES]


def generation_constraints(settings: dict[str, Any] | None = None, *, genre_id: str, duration: int | None) -> dict[str, Any]:
    base = dict(settings or {})
    if duration is not None:
        base["duration"] = duration
    normalized = normalize_generation_settings(base)
    seconds = int(normalized["duration"])
    min_words = max(18, int(seconds * 1.75))
    max_words = max(min_words + 8, int(seconds * 2.55))
    image_count = max(int(normalized["image_count"]), _minimum_image_cues(seconds))
    return {
        "genre_id": genre_id,
        "duration_seconds": seconds,
        "narration_word_count": {"min": min_words, "max": max_words},
        "image_count": image_count,
        "voice_speed_multiplier": float(normalized["voice_speed"]),
        "caption_words_per_phrase": int(normalized["caption_words"]),
        "music_volume": float(normalized["music_volume"]),
        "schedule": str(normalized["schedule"]),
        "language": "simple English, short spoken sentences, clear cause and effect",
        "script_format": "strict JSON only",
        "research_policy": "use concrete real-world anchors when the topic asks for facts, history, mystery, horror, or science",
        "asset_policy": "stock video first; if no distinct video is found, use images instead of repeating one clip",
    }


def build_agent_contracts(settings: dict[str, Any] | None = None, *, genre_id: str, duration: int | None) -> list[dict[str, Any]]:
    constraints = generation_constraints(settings, genre_id=genre_id, duration=duration)
    return [
        _contract("master_agent", "Master", "Routes the request and locks constraints.", constraints),
        _contract("topic_discovery_agent", "Discovery", "Finds real-world angles and source candidates.", constraints),
        _contract("research_agent", "Research", "Builds a short grounded research brief.", constraints),
        _contract("script_agent", "Script", "Writes the script JSON using the research anchors.", constraints),
        _contract("validation_agent", "Validation", "Checks script, assets, audio, captions, and render.", constraints),
        _contract("asset_agent", "Assets", "Fetches varied video/image assets.", constraints),
        _contract("audio_agent", "Voice", "Creates narration and word timing.", constraints),
        _contract("caption_agent", "Captions", "Builds readable captions.", constraints),
        _contract("render_agent", "Render", "Produces the vertical MP4.", constraints),
        _contract("thumbnail_agent", "Thumbnail", "Creates Shorts cover and YouTube thumbnail.", constraints),
    ]


def compact_agent_route(contracts: list[dict[str, Any]]) -> str:
    return "\n".join(f"{item['label']}: {item['description']}" for item in contracts)


def _contract(name: str, label: str, description: str, constraints: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": name,
        "label": label,
        "description": description,
        "input_params": [],
        "output_params": [],
        "constraints": [
            f"duration={constraints['duration_seconds']}s",
            f"word_count={constraints['narration_word_count']['min']}-{constraints['narration_word_count']['max']}",
            f"image_count>={constraints['image_count']}",
            constraints["language"],
        ],
    }


def _minimum_image_cues(duration: int) -> int:
    if duration >= 120:
        return 18
    if duration >= 90:
        return 14
    if duration >= 60:
        return 10
    if duration >= 45:
        return 8
    return 5
