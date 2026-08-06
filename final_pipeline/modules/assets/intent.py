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

GENRE_VISUAL_PROFILES: dict[str, dict[str, list[str] | str]] = {
    "scary_stories": {
        "query_modifiers": ["dark", "moody", "low light", "eerie", "night"],
        "preferred_terms": ["dark", "night", "shadow", "eerie", "abandoned", "dim", "mist", "empty", "low light"],
        "negative_terms": ["happy", "smiling", "cheerful", "sunny", "bright", "colorful", "party", "wedding", "cartoon", "anime", "illustration"],
        "visual_style": "dark eerie low-light realistic horror stock footage",
    },
    "true_crime": {
        "query_modifiers": ["dark", "documentary", "tense", "low light", "realistic"],
        "preferred_terms": ["dark", "night", "police", "evidence", "documentary", "street", "crime", "shadow", "investigation"],
        "negative_terms": ["happy", "smiling", "cheerful", "sunny", "bright", "colorful", "party", "wedding", "cartoon", "anime", "illustration"],
        "visual_style": "tense dark documentary realistic crime footage",
    },
    "history_facts": {
        "query_modifiers": ["historic", "documentary", "archive", "cinematic"],
        "preferred_terms": ["historic", "archive", "museum", "ancient", "documentary", "ruins", "detail"],
        "negative_terms": ["cartoon", "anime", "illustration", "party", "selfie"],
        "visual_style": "documentary historic realistic archive style footage",
    },
    "reddit_stories": {
        "query_modifiers": ["realistic", "indoor", "conversation", "lifestyle"],
        "preferred_terms": ["person", "room", "phone", "conversation", "home", "realistic"],
        "negative_terms": ["cartoon", "anime", "illustration", "fantasy"],
        "visual_style": "realistic lifestyle stock footage",
    },
    "comics": {
        "query_modifiers": ["cinematic", "city", "dramatic", "hero"],
        "preferred_terms": ["hero", "city", "dramatic", "action", "costume", "comic"],
        "negative_terms": ["wedding", "party", "corporate", "office"],
        "visual_style": "dramatic cinematic comic hero visuals",
    },
}


def build_asset_intent(cue: ImageCue, genre: GenreConfig, asset_intent_profile: dict[str, Any] | None = None) -> dict[str, Any]:
    profile = asset_intent_profile or {}
    visual_profile = genre_visual_profile(genre)
    words = _important_words(cue.keyword)
    preferred_terms = _merge_terms(profile.get("preferred_terms", []), visual_profile.get("preferred_terms", []), _mood_terms(cue.mood))
    negative_terms = _merge_terms(profile.get("negative_terms", []), visual_profile.get("negative_terms", []))
    return {
        "genre_id": genre.genre_id,
        "keyword": cue.keyword,
        "required_terms": profile.get("required_terms", words[:4]),
        "preferred_terms": preferred_terms,
        "negative_terms": negative_terms,
        "query_modifiers": visual_profile.get("query_modifiers", []),
        "visual_style": profile.get("visual_style") or visual_profile.get("visual_style", "realistic stock footage"),
    }


def rewrite_query_for_intent(
    query: str,
    genre: GenreConfig,
    asset_intent_profile: dict[str, Any] | None = None,
) -> str:
    visual_profile = genre_visual_profile(genre)
    words = _important_words(query)
    if len(words) < 3:
        words.extend(_genre_defaults(genre))
    base_words = list(dict.fromkeys(words))[:4]
    style_words = [str(term) for term in visual_profile.get("query_modifiers", [])[:3]]
    return " ".join(list(dict.fromkeys([*base_words, *style_words]))[:7])


def expand_query_for_intent(query: str, intent: dict[str, Any]) -> list[str]:
    base = " ".join(_important_words(query))
    variants = [base]
    if base:
        variants.extend([f"{base} vertical video", f"{base} realistic footage", f"{base} close up"])
        for modifier in intent.get("query_modifiers", [])[:3]:
            variants.append(f"{modifier} {base}")
    required = " ".join(intent.get("required_terms", [])[:4])
    if required and required != base:
        variants.append(required)
    return [item for item in variants if item.strip()]


def reject_for_intent(result: Any, intent: dict[str, Any]) -> bool:
    text = _candidate_text(result)
    return any(_term_in_text(str(term), text) for term in intent.get("negative_terms", []))


def score_intent_alignment(result: Any, intent: dict[str, Any]) -> float:
    text = _candidate_text(result)
    score = 0.0
    for term in intent.get("required_terms", []):
        if _term_in_text(str(term), text):
            score += 1.0
    for term in intent.get("preferred_terms", []):
        if _term_in_text(str(term), text):
            score += 0.7
    for term in intent.get("negative_terms", []):
        if _term_in_text(str(term), text):
            score -= 1.5
    return score


def genre_visual_profile(genre: GenreConfig) -> dict[str, Any]:
    genre_id = str(getattr(genre, "genre_id", "") or "").lower()
    tone = str(getattr(genre, "tone", "") or "").lower()
    music_mood = str(getattr(genre, "music_mood", "") or "").lower()
    if genre_id in GENRE_VISUAL_PROFILES:
        base = dict(GENRE_VISUAL_PROFILES[genre_id])
    elif "scary" in genre_id or "horror" in genre_id or "dark" in tone or "dark" in music_mood:
        base = dict(GENRE_VISUAL_PROFILES["scary_stories"])
    elif "crime" in genre_id or "mystery" in genre_id or "tense" in tone:
        base = dict(GENRE_VISUAL_PROFILES["true_crime"])
    else:
        base = {
            "query_modifiers": ["realistic", "cinematic"],
            "preferred_terms": ["realistic", "cinematic"],
            "negative_terms": ["cartoon", "anime", "illustration"],
            "visual_style": "realistic cinematic stock footage",
        }
    configured = getattr(genre, "visual_style", {}) or {}
    if isinstance(configured, dict):
        for key in ("query_modifiers", "preferred_terms", "negative_terms"):
            if configured.get(key):
                base[key] = _merge_terms(base.get(key, []), configured.get(key, []))
        if configured.get("visual_style"):
            base["visual_style"] = str(configured["visual_style"])
    return base


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


def _mood_terms(mood: str) -> list[str]:
    text = str(mood or "").lower()
    if text in {"dark", "eerie"}:
        return ["dark", "eerie", "shadow", "low light"]
    if text == "dramatic":
        return ["dramatic", "cinematic"]
    if text == "reveal":
        return ["close up", "detail", "dramatic"]
    return []


def _merge_terms(*groups: Any) -> list[str]:
    merged: list[str] = []
    for group in groups:
        values = group if isinstance(group, list) else [group]
        for value in values:
            text = str(value or "").strip().lower()
            if text and text not in merged:
                merged.append(text)
    return merged


def _candidate_text(result: Any) -> str:
    return " ".join(
        str(getattr(result, key, "") or "")
        for key in ("title", "description", "url", "page_url", "creator", "source")
    ).lower()


def _term_in_text(term: str, text: str) -> bool:
    clean = str(term or "").strip().lower()
    if not clean:
        return False
    pattern = r"\b" + r"\s+".join(re.escape(part) for part in clean.split()) + r"\b"
    return bool(re.search(pattern, text))
