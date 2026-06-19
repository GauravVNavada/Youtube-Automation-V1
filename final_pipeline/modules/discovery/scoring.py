from __future__ import annotations

import math
import re

from modules.discovery.sources import SearchResult


STOPWORDS = {
    "about",
    "after",
    "also",
    "and",
    "are",
    "been",
    "duration",
    "from",
    "have",
    "into",
    "keep",
    "make",
    "secons",
    "seconds",
    "short",
    "that",
    "the",
    "this",
    "video",
    "was",
    "were",
    "with",
}


def keywords_from_text(text: str, limit: int = 8) -> list[str]:
    words = []
    for raw in re.findall(r"[a-z0-9]{3,}", text.lower()):
        if raw not in STOPWORDS and raw not in words:
            words.append(raw)
    return words[:limit]


def score_result(result: SearchResult, topic: str, genre_terms: list[str] | None = None) -> float:
    haystack = f"{result.title} {result.snippet}".lower()
    topic_terms = keywords_from_text(topic, 12)
    score = 0.0
    for term in topic_terms:
        if term in haystack:
            score += 1.0
    for term in genre_terms or []:
        if term.lower() in haystack:
            score += 0.35
    if result.source in {"duckduckgo", "wikipedia"}:
        score += 0.2
    if result.url:
        score += 0.1
    return round(math.sqrt(max(score, 0.0)) * 2.0, 3)
