from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.paths import DATA_DIR
from app.schemas import GenreConfig, NicheProfile


DEFAULT_PROFILES: dict[str, dict[str, Any]] = {
    "scary_stories": {
        "hook_templates": [
            "At {time}, {subject} noticed {detail}.",
            "The first warning was {detail}.",
            "People still avoid {place} because of {event}.",
        ],
        "tone_rules": [
            "Slow dread with one concrete detail per sentence.",
            "Use a final reveal that feels possible, not random.",
            "Use easy spoken words.",
            "Ground the story in a named place, report, legend, or real-world claim when research is available.",
        ],
        "title_words": ["sealed", "hidden", "knock", "room", "warning", "alone"],
        "thumbnail_text_rules": ["Use 2-4 words.", "Use one scary object or action."],
        "visual_keywords": ["dark hallway", "old door", "phone screen", "shadow figure", "abandoned room", "mirror"],
        "negative_visual_keywords": ["anime", "cartoon", "random school hallway", "gore", "fantasy monster"],
        "hashtag_hints": ["#shorts", "#scary", "#horror"],
    },
    "history_facts": {
        "hook_templates": ["This real place still shows {detail}.", "Most people miss {fact}."],
        "tone_rules": ["Use names, dates, places, and simple explanations.", "Make history feel close to daily life."],
        "title_words": ["ancient", "hidden", "lost", "real", "forgotten"],
        "visual_keywords": ["archive photo", "historic street", "museum object", "old map"],
        "negative_visual_keywords": ["fantasy", "game art", "fiction"],
        "hashtag_hints": ["#shorts", "#history", "#facts"],
    },
    "reddit_stories": {
        "hook_templates": ["I thought {person} was joking until {detail}.", "What would you do if {problem}?"],
        "tone_rules": ["Use normal conversational words.", "Keep the twist believable and satisfying."],
        "title_words": ["secret", "caught", "truth", "test", "family"],
        "visual_keywords": ["family dinner", "phone message", "living room", "tense conversation"],
        "negative_visual_keywords": ["celebrity", "cartoon", "fantasy"],
        "hashtag_hints": ["#shorts", "#redditstory", "#storytime"],
    },
}


def load_niche_profile(genre: GenreConfig) -> NicheProfile:
    path = DATA_DIR / "niche_profiles" / f"{genre.genre_id}.json"
    data: dict[str, Any] = {}
    source = "default"
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            source = str(path)
        except Exception:
            data = {}
    merged = {**DEFAULT_PROFILES.get(genre.genre_id, {}), **data}
    return NicheProfile(
        genre_id=genre.genre_id,
        display_name=genre.display_name,
        hook_templates=_list(merged.get("hook_templates") or genre.hook_patterns),
        tone_rules=_list(merged.get("tone_rules") or [genre.tone]),
        title_words=_list(merged.get("title_words")),
        thumbnail_text_rules=_list(merged.get("thumbnail_text_rules")),
        visual_keywords=_list(merged.get("visual_keywords")),
        negative_visual_keywords=_list(merged.get("negative_visual_keywords")),
        hashtag_hints=_list(merged.get("hashtag_hints")),
        source=source,
    )


def _list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []
