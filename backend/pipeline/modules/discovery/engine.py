from __future__ import annotations

import re
from typing import Any

from app.schemas import GenreConfig, NicheProfile, TopicCandidate, TopicDiscoveryOutput
from modules.discovery.scoring import keywords_from_text, score_result
from modules.discovery.sources import SearchResult, search_duckduckgo, search_reddit, search_wikimedia


def discover_topics(
    topic: str,
    genre: GenreConfig,
    reference_scripts: list[dict[str, Any]],
    profile: NicheProfile,
    max_candidates: int = 8,
    web_enabled: bool = True,
    grounding_plan: dict[str, Any] | None = None,
) -> TopicDiscoveryOutput:
    """Create scored topic angles from free web sources and local fallbacks."""
    source_errors: list[str] = []
    results: list[SearchResult] = []
    if web_enabled:
        for source_name, search_fn, query in _discovery_queries(topic, genre, grounding_plan or {}):
            try:
                results.extend(search_fn(query, max_results=5))
            except Exception as exc:
                source_errors.append(f"{source_name}: {type(exc).__name__}: {exc}")
    results.extend(_local_results(topic, genre, reference_scripts, profile))

    candidates = _results_to_candidates(topic, results, profile, _grounded_genre(genre), grounding_plan or {})
    if not candidates:
        candidates = _fallback_candidates(topic, genre, profile)

    deduped = _dedupe_candidates(candidates)
    deduped.sort(key=lambda candidate: candidate.score, reverse=True)
    selected = deduped[0]
    return TopicDiscoveryOutput(
        original_topic=topic,
        selected_topic=selected.topic,
        selected_angle=selected.angle,
        candidates=deduped[:max_candidates],
        niche_profile=profile,
        grounding_plan=grounding_plan or {},
        source_errors=source_errors,
    )


def _discovery_queries(topic: str, genre: GenreConfig, grounding_plan: dict[str, Any]) -> tuple[tuple[str, Any, str], ...]:
    clean = " ".join(topic.split())
    planned = [str(item) for item in grounding_plan.get("search_queries", []) if str(item).strip()]
    queries = planned[:3] or [
        f"{clean} {genre.display_name} real example",
        f"{clean} reported facts context",
        clean,
    ]
    duck = queries[0]
    wiki = queries[1] if len(queries) > 1 else clean
    reddit = queries[2] if len(queries) > 2 else f"{clean} real story"
    return (("duckduckgo", search_duckduckgo, duck), ("wikipedia", search_wikimedia, wiki), ("reddit", search_reddit, reddit))


def _grounded_genre(genre: GenreConfig) -> bool:
    return genre.genre_id.lower() in {"scary_stories", "mystery_stories", "history_facts", "science_facts"}


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
        snippet = " ".join(part for part in [hook_type, why, str(ref.get("script") or "")[:180]] if part)
        results.append(SearchResult(title=f"{topic}: {title}", url="", snippet=snippet, source="local_reference"))
    for template in profile.hook_templates[:4]:
        detail = _first_visual_keyword(profile, topic)
        hook = template.replace("{detail}", detail).replace("{subject}", topic).replace("{time}", "one night").replace("{sound}", "a sound")
        results.append(SearchResult(title=hook, url="", snippet=" ".join(profile.tone_rules[:2]), source="local_profile"))
    return results


def _results_to_candidates(topic: str, results: list[SearchResult], profile: NicheProfile, grounded: bool = False, grounding_plan: dict[str, Any] | None = None) -> list[TopicCandidate]:
    candidates: list[TopicCandidate] = []
    plan = grounding_plan or {}
    for result in results:
        if grounded and not _is_relevant_result(result, topic, plan):
            continue
        text = f"{result.title}. {result.snippet}".strip()
        angle = _angle_from_text(text, profile)
        hook = _hook_from_text(text, topic, profile)
        keywords = keywords_from_text(text, limit=8)
        score = score_result(result, topic, profile.visual_keywords)
        if grounded and result.url:
            score += 0.35
        score += _plan_overlap_score(text, plan)
        if grounded and result.source.startswith("local"):
            score -= 0.2
        candidates.append(
            TopicCandidate(
                topic=_candidate_topic(topic, angle),
                angle=angle,
                hook=hook,
                score=score,
                source=result.source,
                keywords=keywords,
            )
        )
    return candidates


def _is_relevant_result(result: SearchResult, topic: str, grounding_plan: dict[str, Any]) -> bool:
    if result.source.startswith("local"):
        return True
    text = f"{result.title} {result.snippet} {result.url}".lower()
    if _contains_any_plan_term(text, grounding_plan.get("excluded_terms", [])):
        return False
    required_terms = set(_plan_terms(grounding_plan.get("required_terms", [])))
    if not required_terms:
        required_terms = set(re.findall(r"[a-z0-9]{3,}", topic.lower()))
    required_terms = {term for term in required_terms if term not in {"story", "stories", "real", "reported"}}
    if not required_terms:
        return True
    source_terms = set(re.findall(r"[a-z0-9]{3,}", text))
    return bool(required_terms & source_terms)


def _plan_overlap_score(text: str, grounding_plan: dict[str, Any]) -> float:
    source_terms = set(re.findall(r"[a-z0-9]{3,}", text.lower()))
    required_terms = set(_plan_terms(grounding_plan.get("required_terms", [])))
    if not required_terms:
        return 0.0
    hits = len(required_terms & source_terms)
    return min(0.8, hits * 0.18)


def _contains_any_plan_term(text: str, terms: Any) -> bool:
    return any(str(term).strip().lower() in text for term in terms or [] if str(term).strip())


def _plan_terms(value: Any) -> list[str]:
    terms: list[str] = []
    for item in value or []:
        terms.extend(re.findall(r"[a-z0-9]{3,}", str(item).lower()))
    return list(dict.fromkeys(terms))


def _fallback_candidates(topic: str, genre: GenreConfig, profile: NicheProfile) -> list[TopicCandidate]:
    base_keywords = profile.visual_keywords[:3] or [genre.display_name.lower()]
    candidates: list[TopicCandidate] = []
    for index, keyword in enumerate(base_keywords):
        angle = f"{keyword} detail"
        candidates.append(
            TopicCandidate(
                topic=_candidate_topic(topic, angle),
                angle=angle,
                hook=_default_hook(topic, profile),
                score=0.8 - index * 0.05,
                source="fallback",
                keywords=keywords_from_text(f"{topic} {keyword}", limit=6),
            )
        )
    return candidates


def _dedupe_candidates(candidates: list[TopicCandidate]) -> list[TopicCandidate]:
    deduped: list[TopicCandidate] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = re.sub(r"[^a-z0-9]+", " ", candidate.topic.lower()).strip()
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(candidate)
    return deduped


def _candidate_topic(topic: str, angle: str) -> str:
    clean_topic = " ".join(topic.split())
    clean_angle = " ".join(angle.split())
    if not clean_angle or clean_angle.lower() in clean_topic.lower():
        return clean_topic
    return f"{clean_topic} - {clean_angle}"


def _angle_from_text(text: str, profile: NicheProfile) -> str:
    keywords = keywords_from_text(text, limit=5)
    if keywords:
        return " ".join(keywords[:4])
    return _first_visual_keyword(profile, "unexpected detail")


def _hook_from_text(text: str, topic: str, profile: NicheProfile) -> str:
    sentence = re.split(r"(?<=[.!?])\s+", text.strip())[0][:140].strip(" .")
    if sentence:
        return sentence + "."
    return _default_hook(topic, profile)


def _default_hook(topic: str, profile: NicheProfile) -> str:
    template = profile.hook_templates[0] if profile.hook_templates else "The strangest detail was {detail}."
    detail = _first_visual_keyword(profile, topic)
    return template.replace("{detail}", detail).replace("{subject}", topic).replace("{time}", "one night").replace("{sound}", "a sound")


def _first_visual_keyword(profile: NicheProfile, fallback: str) -> str:
    return profile.visual_keywords[0] if profile.visual_keywords else fallback
