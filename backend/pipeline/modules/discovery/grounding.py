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


def build_grounding_plan(topic: str, genre: GenreConfig, provider: Any | None = None) -> dict[str, Any]:
    if provider:
        try:
            payload = {
                "topic": topic,
                "genre_id": genre.genre_id,
                "genre": genre.display_name,
                "tone": genre.tone,
            }
            data = provider.generate_json(SYSTEM_PROMPT, json.dumps(payload, ensure_ascii=True), 600)
            return _coerce_plan(data, topic, genre)
        except Exception:
            pass
    return _fallback_plan(topic, genre)


def _coerce_plan(data: dict[str, Any], topic: str, genre: GenreConfig) -> dict[str, Any]:
    fallback = _fallback_plan(topic, genre)
    queries = _clean_items(data.get("search_queries"), fallback["search_queries"], 6)
    required = _clean_items(data.get("required_terms"), fallback["required_terms"], 12)
    excluded = _clean_items(data.get("excluded_terms"), fallback["excluded_terms"], 16)
    return {
        "search_queries": queries,
        "required_terms": required,
        "excluded_terms": excluded,
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
    return {
        "search_queries": queries,
        "required_terms": terms,
        "excluded_terms": excluded,
        "grounding_note": note,
    }


def _topic_terms(text: str) -> list[str]:
    stop = {"the", "and", "for", "with", "from", "that", "this", "story", "stories", "haunted"}
    return [
        word
        for word in re.findall(r"[a-z0-9]{3,}", text.lower())
        if word not in stop and not word.isdigit()
    ][:12]


def _clean_items(value: Any, fallback: list[str], max_items: int) -> list[str]:
    if not isinstance(value, list):
        return fallback
    cleaned = [" ".join(str(item).split())[:120] for item in value if str(item).strip()]
    return cleaned[:max_items] or fallback
