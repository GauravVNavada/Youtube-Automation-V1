from __future__ import annotations

import re
from typing import Any

from app.schemas import GenreConfig, ImageCue


ABSTRACT_WORDS = {
    "anxiety",
    "cinematic",
    "dramatic",
    "dread",
    "emotion",
    "fear",
    "feeling",
    "mystery",
    "pressure",
    "scary",
    "shock",
    "truth",
}


def build_asset_intent(cue: ImageCue, genre: GenreConfig, asset_intent_profile: dict[str, Any] | None = None) -> dict[str, Any]:
    profile = asset_intent_profile or {}
    words = _important_words(cue.keyword)
    return {
        "genre_id": genre.genre_id,
        "keyword": cue.keyword,
        "required_terms": profile.get("required_terms", words[:4]),
        "negative_terms": profile.get("negative_terms", []),
        "visual_style": profile.get("visual_style", "realistic stock footage"),
    }


def rewrite_query_for_intent(
    query: str,
    genre: GenreConfig,
    asset_intent_profile: dict[str, Any] | None = None,
) -> str:
    words = _important_words(query)
    if len(words) < 3:
        words.extend(_genre_defaults(genre))
    return " ".join(words[:6])


def expand_query_for_intent(query: str, intent: dict[str, Any]) -> list[str]:
    base = " ".join(_important_words(query))
    variants = [base]
    if base:
        variants.extend([f"{base} vertical video", f"{base} realistic footage", f"{base} close up"])
    required = " ".join(intent.get("required_terms", [])[:4])
    if required and required != base:
        variants.append(required)
    return [item for item in variants if item.strip()]


def reject_for_intent(result: Any, intent: dict[str, Any]) -> bool:
    text = f"{getattr(result, 'title', '')} {getattr(result, 'url', '')}".lower()
    return any(str(term).lower() in text for term in intent.get("negative_terms", []))


def score_intent_alignment(result: Any, intent: dict[str, Any]) -> float:
    text = f"{getattr(result, 'title', '')} {getattr(result, 'url', '')}".lower()
    score = 0.0
    for term in intent.get("required_terms", []):
        if str(term).lower() in text:
            score += 1.0
    return score


def _important_words(text: str) -> list[str]:
    words = []
    for raw in re.findall(r"[a-z0-9]{3,}", text.lower()):
        if raw in ABSTRACT_WORDS or raw in {"image", "video", "stock", "vertical"}:
            continue
        if raw not in words:
            words.append(raw)
    return words


def _genre_defaults(genre: GenreConfig) -> list[str]:
    if genre.genre_id == "scary_stories":
        return ["dark", "hallway", "real", "location"]
    if genre.genre_id == "history_facts":
        return ["historic", "street", "archive", "detail"]
    if genre.genre_id == "comics":
        return ["comic", "hero", "panel", "city"]
    return ["person", "room", "real", "scene"]
