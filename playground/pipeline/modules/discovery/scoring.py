from __future__ import annotations

import re

from modules.discovery.sources import SearchResult


SOURCE_WEIGHTS = {
    "reddit": 1.25,
    "duckduckgo": 1.1,
    "wikipedia": 1.0,
    "local_reference": 0.55,
    "local_profile": 0.45,
}

STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "from",
    "that",
    "this",
    "about",
    "short",
    "story",
    "video",
    "youtube",
    "make",
    "create",
    "generate",
}


def score_result(result: SearchResult, topic: str, profile_keywords: list[str]) -> float:
    text = f"{result.title} {result.snippet}".lower()
    topic_terms = _terms(topic)
    profile_terms = {term for keyword in profile_keywords for term in _terms(keyword)}
    overlap = len(set(topic_terms) & set(_terms(text)))
    profile_overlap = len(profile_terms & set(_terms(text)))
    title_bonus = 0.6 if any(term in result.title.lower() for term in topic_terms[:3]) else 0.0
    snippet_bonus = min(0.7, len(result.snippet.split()) / 80.0)
    score = SOURCE_WEIGHTS.get(result.source, 0.8) + overlap * 0.45 + profile_overlap * 0.2 + title_bonus + snippet_bonus
    if result.source.startswith("local_"):
        score *= 0.72
    return round(score, 3)


def keywords_from_text(text: str, limit: int = 8) -> list[str]:
    terms = _terms(text)
    scored: dict[str, int] = {}
    for term in terms:
        scored[term] = scored.get(term, 0) + 1
    return [term for term, _ in sorted(scored.items(), key=lambda item: (-item[1], item[0]))[:limit]]


def _terms(text: str) -> list[str]:
    return [
        word
        for word in re.findall(r"[a-z0-9]{3,}", text.lower())
        if word not in STOPWORDS and not word.isdigit()
    ]
