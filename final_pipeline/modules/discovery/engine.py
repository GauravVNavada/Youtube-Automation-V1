from __future__ import annotations

import re
from typing import Any

from app.schemas import GenreConfig, NicheProfile, TopicCandidate, TopicDiscoveryOutput
from modules.assets.subject_lock import infer_subject_lock
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
        if not _reference_matches_topic(ref, topic):
            continue
        title = str(ref.get("title") or genre.display_name)
        hook_type = str(ref.get("hook_type") or "reference hook")
        why = str(ref.get("why_it_worked") or "")
        facts = ref.get("facts") if isinstance(ref.get("facts"), list) else []
        fact_text = " ".join(str(fact) for fact in facts[:3])
        script = " ".join(str(ref.get("script") or "").split())[:260]
        results.append(
            SearchResult(
                title=title,
                url=str(ref.get("source_url") or ref.get("video_url") or ""),
                snippet=f"{hook_type}. {why}. {fact_text}. {script}",
                source=str(ref.get("source") or "local_reference"),
            )
        )
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
        candidate_topic = f"{topic} - {angle}" if angle and angle.lower() not in topic.lower() else topic
        candidate_angle = angle or topic
        if not _angle_can_extend_topic(topic, angle):
            candidate_topic = topic
            candidate_angle = topic
            score -= 0.75
        candidates.append(
            TopicCandidate(
                topic=candidate_topic,
                angle=candidate_angle,
                hook=hook,
                score=round(score, 3),
                source=result.source,
                keywords=keywords,
            )
        )
    return candidates


def _is_relevant_result(result: SearchResult, topic: str, grounding_plan: dict[str, Any]) -> bool:
    if result.source == "local_profile":
        return False
    haystack = f"{result.title} {result.snippet}".lower()
    excluded = [str(term).lower() for term in grounding_plan.get("excluded_terms", [])]
    if any(term and term in haystack for term in excluded):
        return False
    required = _plan_terms(grounding_plan) or keywords_from_text(topic, 6)
    return not required or any(term in haystack for term in required)


def _angle_can_extend_topic(topic: str, angle: str) -> bool:
    angle_terms = set(keywords_from_text(angle, 10))
    if not angle_terms:
        return False
    subject_lock = infer_subject_lock(topic)
    if not subject_lock.enabled:
        topic_terms = set(keywords_from_text(topic, 10))
        return bool(topic_terms.intersection(angle_terms))
    subject_terms = set(keywords_from_text(subject_lock.subject, 10))
    if subject_terms and subject_terms.issubset(angle_terms):
        return True
    for alias in (subject_lock.subject, *subject_lock.aliases):
        alias_terms = set(keywords_from_text(alias, 10))
        if alias_terms and alias_terms.issubset(angle_terms):
            return True
    return False


def _plan_overlap_score(result: SearchResult, grounding_plan: dict[str, Any]) -> float:
    haystack = f"{result.title} {result.snippet}".lower()
    terms = _plan_terms(grounding_plan)
    return round(sum(0.25 for term in terms if term in haystack), 3)


def _plan_terms(grounding_plan: dict[str, Any]) -> list[str]:
    return [str(term).lower() for term in grounding_plan.get("required_terms", []) if len(str(term)) >= 3]


def _reference_matches_topic(ref: dict[str, Any], topic: str) -> bool:
    topic_terms = set(keywords_from_text(topic, 10))
    if not topic_terms:
        return False
    haystack = " ".join(
        [
            str(ref.get("title") or ""),
            str(ref.get("real_world_anchor") or ""),
            " ".join(str(fact) for fact in ref.get("facts", []) if isinstance(ref.get("facts"), list)),
            str(ref.get("script") or ref.get("full_script") or ""),
            " ".join(str(word) for word in ref.get("visual_keywords", []) if isinstance(ref.get("visual_keywords"), list)),
        ]
    )
    return bool(topic_terms.intersection(keywords_from_text(haystack, 40)))


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
