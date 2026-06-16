from __future__ import annotations

import json
import re
from typing import Any

from app.schemas import GenreConfig


SYSTEM_PROMPT = """
You are a grounding planner for a YouTube Shorts research pipeline.
Given a user topic and genre, produce generic search guidance.
Do not invent a story. Do not choose from a hardcoded list.
Return JSON only.

OUTPUT:
{
  "search_queries": ["3 to 6 web search queries"],
  "required_terms": ["terms that must stay relevant to the user intent"],
  "excluded_terms": ["terms/categories that would make sources irrelevant"],
  "grounding_note": "one sentence describing what kind of real-world anchor to find"
}
""".strip()


def build_grounding_plan(topic: str, genre: GenreConfig, provider=None) -> dict[str, Any]:
    fallback = _fallback_plan(topic, genre)
    if not provider:
        return fallback
    prompt = {
        "topic": topic,
        "genre": genre.genre_id,
        "genre_display_name": genre.display_name,
        "fallback": fallback,
        "instruction": "Make search guidance generic and topic-specific. Avoid examples unless they come from the user topic.",
    }
    try:
        data = provider.generate_json(SYSTEM_PROMPT, json.dumps(prompt, ensure_ascii=True), 600)
        return _coerce_plan(data, topic, genre)
    except Exception:
        return fallback


def _coerce_plan(data: dict[str, Any], topic: str, genre: GenreConfig) -> dict[str, Any]:
    fallback = _fallback_plan(topic, genre)
    return {
        "search_queries": _clean_items(data.get("search_queries"), fallback["search_queries"], 6),
        "required_terms": _clean_items(data.get("required_terms"), fallback["required_terms"], 12),
        "excluded_terms": _clean_items(data.get("excluded_terms"), fallback["excluded_terms"], 16),
        "grounding_note": str(data.get("grounding_note") or fallback["grounding_note"])[:240],
    }


def _fallback_plan(topic: str, genre: GenreConfig) -> dict[str, Any]:
    clean = " ".join(topic.split())
    terms = _topic_terms(clean)
    genre_id = genre.genre_id.lower()
    if genre_id in {"scary_stories", "mystery_stories"}:
        queries = [
            f"{clean} real reported incident location",
            f"{clean} folklore urban legend reported",
            f"{clean} witness account local legend",
            f"{clean} historical place report",
        ]
        excluded = ["movie", "anime", "tv series", "theme park", "game", "song", "massacre", "shooting"]
        note = "Find a named place, case, urban legend, local report, or documented claim that matches the user topic."
    elif genre_id == "history_facts":
        queries = [f"{clean} history facts date place", f"{clean} historical record", f"{clean} artifact event"]
        excluded = ["movie", "game", "fiction", "fan wiki"]
        note = "Find a named event, date, place, person, or artifact."
    elif genre_id == "science_facts":
        queries = [f"{clean} study research facts", f"{clean} experiment findings", f"{clean} scientific evidence"]
        excluded = ["movie", "fiction", "conspiracy", "fan wiki"]
        note = "Find a study, experiment, researcher, species, mechanism, or verified phenomenon."
    else:
        queries = [f"{clean} facts context", f"{clean} real example", f"{clean} case study"]
        excluded = ["unrelated", "fan wiki"]
        note = "Find concrete real-world context that matches the user's topic."
    return {"search_queries": queries, "required_terms": terms, "excluded_terms": excluded, "grounding_note": note}


def _topic_terms(text: str) -> list[str]:
    stop = {"stories", "story", "this", "for", "with", "haunted", "and", "that", "the", "from"}
    return [word for word in re.findall(r"[a-z0-9]{3,}", text.lower()) if word not in stop][:12]


def _clean_items(value: Any, fallback: list[str], max_items: int) -> list[str]:
    if not isinstance(value, list):
        return fallback
    cleaned = []
    for item in value:
        text = " ".join(str(item).split())
        if text and text.lower() not in {x.lower() for x in cleaned}:
            cleaned.append(text[:160])
    return cleaned[:max_items] or fallback
