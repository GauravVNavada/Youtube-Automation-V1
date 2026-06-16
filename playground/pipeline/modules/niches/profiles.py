from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.paths import DATA_DIR
from app.schemas import GenreConfig, NicheProfile


def load_niche_profile(genre: GenreConfig, data_dir: Path | None = None) -> NicheProfile:
    """Load a local niche profile, falling back to genre config guidance."""
    root = data_dir or DATA_DIR
    path = root / "niche_profiles" / f"{genre.genre_id}.json"
    if not path.exists():
        return fallback_niche_profile(genre)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return fallback_niche_profile(genre)
    if not isinstance(data, dict):
        return fallback_niche_profile(genre)
    return NicheProfile(
        genre_id=str(data.get("genre_id") or genre.genre_id),
        display_name=str(data.get("display_name") or genre.display_name),
        hook_templates=_string_list(data.get("hook_templates") or genre.hook_patterns),
        tone_rules=_string_list(data.get("tone_rules") or [genre.tone]),
        title_words=_string_list(data.get("title_words")),
        thumbnail_text_rules=_string_list(data.get("thumbnail_text_rules")),
        visual_keywords=_string_list(data.get("visual_keywords")),
        hashtag_hints=_string_list(data.get("hashtag_hints")),
        source=str(path),
    )


def fallback_niche_profile(genre: GenreConfig) -> NicheProfile:
    base = genre.display_name.lower().replace(" stories", "").replace(" facts", "")
    return NicheProfile(
        genre_id=genre.genre_id,
        display_name=genre.display_name,
        hook_templates=genre.hook_patterns
        or [
            "The strangest detail is {detail}.",
            "Most people miss the moment when {detail}.",
        ],
        tone_rules=[genre.tone, "Use specific details and simple spoken sentences."],
        title_words=[genre.display_name, "short", "story"],
        thumbnail_text_rules=["Use 2-4 words.", "Lead with the strongest concrete detail."],
        visual_keywords=[base, "person", "close up", "dramatic scene"],
        hashtag_hints=["#shorts", f"#{genre.genre_id.replace('_', '')}"],
        source="fallback",
    )


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]

