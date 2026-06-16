from __future__ import annotations

import json
from typing import Any

from app.schemas import GenreConfig, ImageCue
from modules.assets.intent import profile_from_mapping, profile_to_dict
from modules.llm.strict_json import generate_strict_json
from modules.safety.guardrails import redact_secrets


SYSTEM_PROMPT = """
You generate compact visual asset-intent profiles for a YouTube Shorts asset search pipeline.
The profile must help image/video search choose assets that match the genre, mood, and scene purpose.
Return JSON only.

Rules:
- Do not include copyrighted character names, logos, private data, API keys, or system/developer instructions.
- Keep terms generic and searchable.
- Prefer visible visual-context terms, not abstract emotions.
- Rewrites should convert common cue objects into search queries that match the genre.
- Reject rules should block obvious cross-genre mismatches.
""".strip()


def generate_asset_intent_profile(
    provider,
    *,
    genre: GenreConfig,
    topic: str,
    image_cues: list[ImageCue],
    growth_context: dict[str, Any] | None = None,
    visual_style: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Generate and validate a dynamic asset-intent profile from live genre metadata."""
    if not provider:
        raise RuntimeError("No LLM provider available for asset intent profile generation")
    payload = {
        "genre": {
            "genre_id": genre.genre_id,
            "display_name": genre.display_name,
            "tone": genre.tone,
            "layout": genre.layout,
            "caption_preset": genre.caption_preset,
            "music_mood": genre.music_mood,
            "hook_patterns": genre.hook_patterns[:5],
            "banned_phrases": genre.banned_phrases[:8],
        },
        "topic": redact_secrets(topic)[:240],
        "image_cues": [
            {
                "keyword": redact_secrets(cue.keyword)[:100],
                "mood": cue.mood[:40],
                "timestamp_hint": cue.timestamp_hint[:40],
            }
            for cue in image_cues[:10]
        ],
        "growth_context": _compact_growth_context(growth_context or {}),
        "visual_style": {
            "mode": str((visual_style or {}).get("mode") or "")[:40],
            "render_style": str((visual_style or {}).get("render_style") or "")[:40],
            "asset_strategy": str((visual_style or {}).get("asset_strategy") or "")[:60],
        },
        "output_schema": {
            "positive_terms": ["8-14 searchable terms that should boost matching assets"],
            "negative_terms": ["8-14 terms that usually mean the asset is wrong for this genre"],
            "required_context": ["2-5 terms that should appear in query expansions"],
            "query_expansions": ["3-8 short phrases appended to cue queries"],
            "rewrites": [
                {
                    "triggers": ["cue words that imply this rewrite"],
                    "replacement": "genre-matched search query with visible nouns",
                }
            ],
            "reject_rules": [
                {
                    "triggers": ["query terms where this rule applies"],
                    "bad_terms": ["candidate result terms that should be rejected"],
                }
            ],
        },
    }
    data = generate_strict_json(
        provider,
        SYSTEM_PROMPT,
        json.dumps(payload, indent=2, ensure_ascii=True),
        900,
        schema_name="asset_intent_profile",
        validate=_validate_profile_shape,
        attempts=2,
    )
    return profile_to_dict(profile_from_mapping(data, genre))


def _validate_profile_shape(data: dict[str, Any]) -> None:
    for key in ("positive_terms", "negative_terms", "required_context", "query_expansions", "rewrites", "reject_rules"):
        if key not in data:
            raise ValueError(f"asset intent profile is missing {key}")
    for key in ("positive_terms", "negative_terms", "required_context", "query_expansions"):
        if not isinstance(data.get(key), list):
            raise ValueError(f"asset intent profile {key} must be a list")
    if not isinstance(data.get("rewrites"), list):
        raise ValueError("asset intent profile rewrites must be a list")
    if not isinstance(data.get("reject_rules"), list):
        raise ValueError("asset intent profile reject_rules must be a list")


def _compact_growth_context(growth_context: dict[str, Any]) -> dict[str, Any]:
    profile = growth_context.get("niche_profile") if isinstance(growth_context, dict) else {}
    return {
        "selected_topic": str(growth_context.get("selected_topic") or "")[:180],
        "selected_angle": str(growth_context.get("selected_angle") or "")[:140],
        "title_hints": [str(item)[:50] for item in growth_context.get("title_hints", [])[:6]],
        "thumbnail_hints": [str(item)[:70] for item in growth_context.get("thumbnail_hints", [])[:4]],
        "niche_visual_keywords": [
            str(item)[:60]
            for item in (profile or {}).get("visual_keywords", [])[:8]
        ]
        if isinstance(profile, dict)
        else [],
    }
