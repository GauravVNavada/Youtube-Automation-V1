from __future__ import annotations

import re
from typing import Any

from desktop_pipeline.message_base import base_messages, compact_json
from desktop_pipeline.route_models import ParameterPatch


SYSTEM_PROMPT = """You map short follow-up chat requests into safe generation-setting patches.
Return only fields that should change. Target the specific pipeline agent that owns the issue.
This agent is deterministic in production, but these examples document the intended mapping."""


EXAMPLES = [
    {
        "role": "user",
        "content": compact_json({"message": "the audio speed is a lot", "current_settings": {"voice_speed": 1.0}}),
    },
    {
        "role": "assistant",
        "content": compact_json(
            {
                "target_agent": "audio_agent",
                "settings_patch": {"voice_speed": 0.88},
                "agent_instructions": {},
                "reason": "voice/audio sounds too fast",
            }
        ),
    },
    {
        "role": "user",
        "content": compact_json({"message": "images are not good and the same ones repeat", "current_settings": {"image_count": 8}}),
    },
    {
        "role": "assistant",
        "content": compact_json(
            {
                "target_agent": "asset_agent",
                "settings_patch": {"image_count": 10},
                "agent_instructions": {"asset_agent": "Replace weak or repeated visuals and avoid reusing selected URLs."},
                "reason": "visual assets need replacement",
            }
        ),
    },
    {
        "role": "user",
        "content": compact_json({"message": "the script does not look good, it feels random", "current_settings": {}}),
    },
    {
        "role": "assistant",
        "content": compact_json(
            {
                "target_agent": "script_agent",
                "settings_patch": {},
                "agent_instructions": {
                    "script_agent": "Regenerate the script around the original source prompt. Keep the same subject, remove random or unrelated beats, and use a fresh coherent angle."
                },
                "reason": "script quality or topic alignment needs repair",
            }
        ),
    },
]


def messages_base() -> list[dict[str, str]]:
    return base_messages(SYSTEM_PROMPT, EXAMPLES)


def map_parameter_request(message: str, current_settings: dict[str, Any] | None = None) -> ParameterPatch:
    settings = current_settings or {}
    text = " ".join(str(message or "").lower().split())
    patch: dict[str, Any] = {}
    instructions: dict[str, str] = {}
    target = ""
    reasons: list[str] = []

    voice_speed = _float(settings.get("voice_speed"), 1.0)
    if _mentions(text, "audio", "voice", "narration", "speaker", "tts"):
        if _mentions(text, "fast", "quick", "speedy", "rushed", "lot") and not _mentions(text, "slow"):
            patch["voice_speed"] = round(max(0.75, voice_speed - 0.12), 2)
            target = "audio_agent"
            reasons.append("voice/audio sounds too fast")
        elif _mentions(text, "slow", "sluggish", "dragging"):
            patch["voice_speed"] = round(min(1.4, voice_speed + 0.1), 2)
            target = "audio_agent"
            reasons.append("voice/audio sounds too slow")

    caption_words = _int(settings.get("caption_words"), 4)
    if _mentions(text, "caption", "captions", "subtitle", "subtitles", "text"):
        if _mentions(text, "fast", "quick", "many", "crowded", "too much", "long"):
            patch["caption_words"] = max(1, caption_words - 1)
            target = target or "caption_agent"
            reasons.append("captions need fewer words per phrase")
        elif _mentions(text, "bigger", "large", "readable", "clear"):
            instructions["caption_agent"] = "Make captions more readable and prioritize safe margins, contrast, and active-word clarity."
            target = target or "caption_agent"
            reasons.append("caption readability needs improvement")

    image_count = _int(settings.get("image_count"), 8)
    if _mentions(text, "image", "images", "visual", "visuals", "asset", "assets", "picture", "pictures", "stock"):
        if _mentions(text, "bad", "wrong", "random", "irrelevant", "repeat", "same", "not good", "weak"):
            patch["image_count"] = min(24, max(image_count + 2, 10))
            instructions["asset_agent"] = (
                "Replace weak or repeated visuals. Search for assets that match the narration subject and avoid reusing selected URLs."
            )
            target = target or "asset_agent"
            reasons.append("visual assets need replacement")

    if _mentions(text, "script", "story", "narration", "hook", "writing", "plot", "content"):
        if _mentions(
            text,
            "bad",
            "wrong",
            "random",
            "unusual",
            "weird",
            "generic",
            "boring",
            "better",
            "improve",
            "not good",
            "look good",
            "doesnt",
            "doesn't",
            "does not",
            "off topic",
            "unrelated",
        ):
            instructions["script_agent"] = (
                "Regenerate the script around the original source prompt. Keep the same named subject, "
                "remove random or unrelated beats, and use a fresh coherent angle instead of treating the follow-up complaint as the topic."
            )
            target = target or "script_agent"
            reasons.append("script quality or topic alignment needs repair")

    music_volume = _float(settings.get("music_volume"), 0.18)
    if _mentions(text, "music", "background", "bgm", "song"):
        if _mentions(text, "loud", "high", "overpower"):
            patch["music_volume"] = round(max(0.0, music_volume - 0.06), 2)
            target = target or "music_agent"
            reasons.append("music is too loud")
        elif _mentions(text, "low", "quiet", "silent"):
            patch["music_volume"] = round(min(0.8, music_volume + 0.05), 2)
            target = target or "music_agent"
            reasons.append("music is too quiet")

    duration_match = re.search(r"\b(\d{2,3})\s*(?:sec|secs|second|seconds|s)\b", text)
    if duration_match and _mentions(text, "duration", "make it", "video", "shorter", "longer"):
        patch["duration"] = int(duration_match.group(1))
        target = target or "script_agent"
        reasons.append("duration requested")

    return ParameterPatch(
        target_agent=target,
        settings_patch=patch,
        agent_instructions=instructions,
        reason=", ".join(reasons),
    )


def looks_like_edit_request(message: str) -> bool:
    text = " ".join(str(message or "").lower().split())
    edit_words = {
        "change",
        "fix",
        "remake",
        "redo",
        "again",
        "too",
        "less",
        "more",
        "faster",
        "slower",
        "loud",
        "quiet",
        "bad",
        "wrong",
        "not good",
        "same",
        "repeat",
        "random",
        "unusual",
        "weird",
        "generic",
        "boring",
        "better",
        "improve",
        "off topic",
        "doesnt",
        "doesn't",
    }
    return any(word in text for word in edit_words)


def _mentions(text: str, *needles: str) -> bool:
    return any(needle in text for needle in needles)


def _float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
