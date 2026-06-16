from __future__ import annotations

import re
from typing import Any

from app.schemas import GenreConfig, NicheProfile, ResearchOutput, ResearchSource, TopicDiscoveryOutput
from modules.discovery.scoring import keywords_from_text
from modules.discovery.sources import SearchResult, search_duckduckgo, search_reddit, search_wikimedia


def build_research_brief(
    topic: str,
    genre: GenreConfig,
    discovery: TopicDiscoveryOutput,
    profile: NicheProfile,
    reference_scripts: list[dict[str, Any]] | None = None,
    max_sources: int = 5,
    web_enabled: bool = True,
    grounding_plan: dict[str, Any] | None = None,
) -> ResearchOutput:
    """Build a compact, best-effort research brief without paid APIs."""
    source_errors: list[str] = []
    results: list[SearchResult] = []
    if web_enabled:
        for source_name, search_fn, query in _research_queries(topic, genre, grounding_plan or {}):
            try:
                results.extend(search_fn(query, max_results=max_sources))
            except Exception as exc:
                source_errors.append(f"{source_name}: {type(exc).__name__}: {exc}")
    results.extend(_local_research_results(topic, genre, discovery, profile, reference_scripts or []))

    sources = _to_research_sources(results, topic=topic, genre=genre, max_sources=max_sources, grounding_plan=grounding_plan or {})
    facts = _facts_from_sources(sources, topic, profile)
    brief = _brief_from_facts(topic, discovery.selected_angle, facts, genre, profile, grounding_plan or {})
    return ResearchOutput(
        topic=topic,
        brief=brief,
        facts=facts,
        source_snippets=sources,
        source_errors=source_errors,
    )


def _research_queries(topic: str, genre: GenreConfig, grounding_plan: dict[str, Any]) -> tuple[tuple[str, Any, str], ...]:
    clean = " ".join(topic.split())
    planned = [str(item) for item in grounding_plan.get("search_queries", []) if str(item).strip()]
    queries = planned[:3] or [f"{clean} facts context", f"{clean} real example", clean]
    query = queries[0]
    wiki_query = queries[1] if len(queries) > 1 else clean
    reddit_query = queries[2] if len(queries) > 2 else f"{clean} real story"
    return (
        ("duckduckgo", search_duckduckgo, query),
        ("wikipedia", search_wikimedia, wiki_query),
        ("reddit", search_reddit, reddit_query),
    )


def _local_research_results(
    topic: str,
    genre: GenreConfig,
    discovery: TopicDiscoveryOutput,
    profile: NicheProfile,
    reference_scripts: list[dict[str, Any]],
) -> list[SearchResult]:
    results = [
        SearchResult(
            title=f"Selected angle: {discovery.selected_angle}",
            url="",
            snippet="Use the selected topic angle as the spine of the short. Keep it concrete and visual.",
            source="local_profile",
        ),
        SearchResult(
            title=f"{genre.display_name} style guide",
            url="",
            snippet=" ".join(profile.tone_rules[:3]),
            source="local_profile",
        ),
    ]
    for ref in reference_scripts[:3]:
        title = str(ref.get("title") or topic)
        snippet = " ".join(
            part
            for part in [
                str(ref.get("hook_type") or ""),
                str(ref.get("why_it_worked") or ""),
                str(ref.get("script") or "")[:220],
            ]
            if part
        )
        results.append(SearchResult(title=title, url="", snippet=snippet, source="local_reference"))
    return results


def _to_research_sources(results: list[SearchResult], topic: str, genre: GenreConfig, max_sources: int, grounding_plan: dict[str, Any]) -> list[ResearchSource]:
    sources: list[ResearchSource] = []
    seen: set[str] = set()
    sorted_results = sorted(
        results,
        key=lambda result: (
            0 if result.url else 1,
            result.source.startswith("local"),
        ),
    )
    for result in sorted_results:
        if not _is_relevant_source(result, topic, genre, grounding_plan):
            continue
        key = (result.url or result.title).strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        sources.append(
            ResearchSource(
                title=result.title[:140],
                url=result.url,
                snippet=result.snippet[:360],
                source=result.source,
            )
        )
        if len(sources) >= max_sources:
            break
    return sources


def _is_relevant_source(result: SearchResult, topic: str, genre: GenreConfig, grounding_plan: dict[str, Any]) -> bool:
    if result.source.startswith("local"):
        return True
    text = f"{result.title} {result.snippet} {result.url}".lower()
    if _contains_any_plan_term(text, grounding_plan.get("excluded_terms", [])):
        return False
    topic_terms = set(_plan_terms(grounding_plan.get("required_terms", []))) or set(_terms(topic))
    source_terms = set(_terms(text))
    if not topic_terms:
        return True
    overlap = topic_terms & source_terms
    return len(overlap) >= 1


def _terms(text: str) -> list[str]:
    return [
        word
        for word in re.findall(r"[a-z0-9]{3,}", text.lower())
        if word not in {"the", "and", "for", "with", "from", "that", "this", "story", "stories"}
    ]


def _facts_from_sources(sources: list[ResearchSource], topic: str, profile: NicheProfile) -> list[str]:
    facts: list[str] = []
    for source in sources:
        text = source.snippet or source.title
        sentence = _first_useful_sentence(text)
        if sentence:
            facts.append(sentence)
    if not facts:
        keywords = ", ".join(keywords_from_text(" ".join(profile.visual_keywords) or topic, limit=4))
        facts.append(f"Build the story around concrete visual details: {keywords or topic}.")
    return facts[:5]


def _brief_from_facts(
    topic: str,
    selected_angle: str,
    facts: list[str],
    genre: GenreConfig,
    profile: NicheProfile,
    grounding_plan: dict[str, Any],
) -> str:
    facts_text = " ".join(f"- {fact}" for fact in facts[:4])
    tone = " ".join(profile.tone_rules[:2]) or genre.tone
    grounding_note = str(grounding_plan.get("grounding_note") or "").strip()
    grounding_text = f" Grounding target: {grounding_note}" if grounding_note else ""
    return (
        f"Topic: {topic}. Selected angle: {selected_angle}. "
        f"Use this as research context, not as a citation script.{grounding_text} Tone: {tone}. "
        f"Useful details: {facts_text}"
    ).strip()


def _contains_any_plan_term(text: str, terms: Any) -> bool:
    return any(str(term).strip().lower() in text for term in terms or [] if str(term).strip())


def _plan_terms(value: Any) -> list[str]:
    terms: list[str] = []
    for item in value or []:
        terms.extend(re.findall(r"[a-z0-9]{3,}", str(item).lower()))
    return list(dict.fromkeys(terms))


def _first_useful_sentence(text: str) -> str:
    cleaned = " ".join(str(text or "").split())
    if not cleaned:
        return ""
    for separator in (". ", "? ", "! "):
        if separator in cleaned:
            return cleaned.split(separator, 1)[0].strip(" .?!") + separator.strip()
    return cleaned[:220].strip(" .") + "."
