from __future__ import annotations

import re
from typing import Any

from app.schemas import GenreConfig, NicheProfile, TopicCandidate, TopicDiscoveryOutput
from modules.discovery.scoring import keywords_from_text, score_result
from modules.discovery.sources import SearchResult, search_duckduckgo, search_reddit, search_wikimedia


def discover_topics(
    topic: str,
    genre: GenreConfig,
    reference_scripts: list[dict[str, Any]] | None,
    profile: NicheProfile,
    max_candidates: int = 8,
    web_enabled: bool = True,
    grounding_plan: dict[str, Any] | None = None,
) -> TopicDiscoveryOutput:
    source_errors: list[str] = []
    results: list[SearchResult] = []
    reference_scripts = reference_scripts or []
    grounding_plan = grounding_plan or {}
    if web_enabled:
        for source_name, search_fn, query in _discovery_queries(topic, genre, grounding_plan):
            try:
                results.extend(search_fn(query, max_results=5))
            except Exception as exc:
                source_errors.append(f"{source_name}: {type(exc).__name__}: {exc}")
    results.extend(_local_results(topic, genre, reference_scripts, profile))
    candidates = _results_to_candidates(topic, genre, results, profile, grounding_plan)
    if not candidates:
        candidates = [_fallback_candidate(topic, profile)]
    candidates = sorted(candidates, key=lambda item: item.score, reverse=True)[:max_candidates]
    selected = candidates[0]
    return TopicDiscoveryOutput(
        original_topic=topic,
        selected_topic=selected.topic,
        selected_angle=selected.angle,
        candidates=candidates,
        niche_profile=profile,
        source_errors=source_errors,
        grounding_plan=grounding_plan,
    )


def _discovery_queries(topic: str, genre: GenreConfig, grounding_plan: dict[str, Any]) -> tuple[tuple[str, Any, str], ...]:
    clean = " ".join(topic.split())
    planned = [str(item) for item in grounding_plan.get("search_queries", []) if str(item).strip()]
    queries = planned[:3] or [f"{clean} {genre.display_name} real example", f"{clean} reported facts context", clean]
    duck = queries[0]
    wiki = queries[1] if len(queries) > 1 else clean
    reddit = queries[2] if len(queries) > 2 else f"{clean} real story"
    return (("duckduckgo", search_duckduckgo, duck), ("wikipedia", search_wikimedia, wiki), ("reddit", search_reddit, reddit))


def _local_results(
    topic: str,
    genre: GenreConfig,
    reference_scripts: list[dict[str, Any]],
    profile: NicheProfile,
) -> list[SearchResult]:
    results: list[SearchResult] = []
    for ref in reference_scripts[:5]:
        title = str(ref.get("title") or genre.display_name)
        hook_type = str(ref.get("hook_type") or "reference hook")
        why = str(ref.get("why_it_worked") or "")
        script = " ".join(str(ref.get("script") or "").split())[:260]
        results.append(SearchResult(title=f"{topic}: {title}", url="", snippet=f"{hook_type}. {why}. {script}", source="local_reference"))
    if profile.hook_templates or profile.tone_rules:
        results.append(
            SearchResult(
                title=f"{genre.display_name} profile",
                url="",
                snippet=" ".join(profile.hook_templates[:2] + profile.tone_rules[:2]),
                source="local_profile",
            )
        )
    return results


def _results_to_candidates(
    topic: str,
    genre: GenreConfig,
    results: list[SearchResult],
    profile: NicheProfile,
    grounding_plan: dict[str, Any],
) -> list[TopicCandidate]:
    candidates: list[TopicCandidate] = []
    genre_terms = profile.title_words + profile.visual_keywords[:3]
    for result in results:
        if not _is_relevant_result(result, topic, grounding_plan):
            continue
        text = f"{result.title} {result.snippet}"
        keywords = keywords_from_text(text, 8)
        angle = _angle_from_keywords(keywords) or _angle_from_title(result.title)
        hook = _hook_from_result(result, topic)
        score = score_result(result, topic, genre_terms) + _plan_overlap_score(result, grounding_plan)
        candidates.append(
            TopicCandidate(
                topic=f"{topic} - {angle}" if angle and angle.lower() not in topic.lower() else topic,
                angle=angle or topic,
                hook=hook,
                score=round(score, 3),
                source=result.source,
                keywords=keywords,
            )
        )
    return candidates


def _is_relevant_result(result: SearchResult, topic: str, grounding_plan: dict[str, Any]) -> bool:
    haystack = f"{result.title} {result.snippet}".lower()
    excluded = [str(term).lower() for term in grounding_plan.get("excluded_terms", [])]
    if any(term and term in haystack for term in excluded):
        return False
    required = _plan_terms(grounding_plan) or keywords_from_text(topic, 6)
    return not required or any(term in haystack for term in required)


def _plan_overlap_score(result: SearchResult, grounding_plan: dict[str, Any]) -> float:
    haystack = f"{result.title} {result.snippet}".lower()
    terms = _plan_terms(grounding_plan)
    return round(sum(0.25 for term in terms if term in haystack), 3)


def _plan_terms(grounding_plan: dict[str, Any]) -> list[str]:
    return [str(term).lower() for term in grounding_plan.get("required_terms", []) if len(str(term)) >= 3]


def _angle_from_keywords(keywords: list[str]) -> str:
    return " ".join(keywords[:4])


def _angle_from_title(title: str) -> str:
    words = keywords_from_text(title, 4)
    return " ".join(words)


def _hook_from_result(result: SearchResult, topic: str) -> str:
    title = result.title.strip().rstrip(".")
    if title:
        return f"{title}."
    return f"{topic}: real-world angle."


def _fallback_candidate(topic: str, profile: NicheProfile) -> TopicCandidate:
    keywords = keywords_from_text(topic, 6)
    angle = " ".join(keywords) or topic
    return TopicCandidate(topic=topic, angle=angle, hook=topic, score=1.0, source="fallback", keywords=keywords)
