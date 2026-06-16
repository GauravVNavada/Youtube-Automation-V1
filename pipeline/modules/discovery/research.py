from __future__ import annotations

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
    grounding_plan = grounding_plan or discovery.grounding_plan or {}
    source_errors: list[str] = []
    results: list[SearchResult] = []
    if web_enabled:
        for source_name, search_fn, query in _research_queries(discovery.selected_topic, genre, grounding_plan):
            try:
                results.extend(search_fn(query, max_results=5))
            except Exception as exc:
                source_errors.append(f"{source_name}: {type(exc).__name__}: {exc}")
    results.extend(_local_research_results(topic, genre, discovery, profile, reference_scripts or []))
    filtered = [item for item in results if _is_relevant_source(item, topic, grounding_plan)]
    sources = _to_research_sources(filtered[:max_sources])
    facts = _facts_from_sources(sources)
    brief = _brief_from_facts(topic, discovery, facts, grounding_plan)
    return ResearchOutput(topic=discovery.selected_topic, brief=brief, facts=facts, source_snippets=sources, source_errors=source_errors)


def _research_queries(topic: str, genre: GenreConfig, grounding_plan: dict[str, Any]) -> tuple[tuple[str, Any, str], ...]:
    clean = " ".join(topic.split())
    planned = [str(item) for item in grounding_plan.get("search_queries", []) if str(item).strip()]
    queries = planned[:3] or [f"{clean} facts context", f"{clean} real example", clean]
    return (
        ("duckduckgo", search_duckduckgo, queries[0]),
        ("wikipedia", search_wikimedia, queries[1] if len(queries) > 1 else clean),
        ("reddit", search_reddit, queries[2] if len(queries) > 2 else f"{clean} real story"),
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
        snippet = " ".join(
            [
                str(ref.get("hook_type") or ""),
                str(ref.get("why_it_worked") or ""),
                str(ref.get("script") or "")[:240],
            ]
        )
        results.append(SearchResult(title=str(ref.get("title") or topic), url="", snippet=snippet, source="local_reference"))
    return results


def _is_relevant_source(result: SearchResult, topic: str, grounding_plan: dict[str, Any]) -> bool:
    if result.source.startswith("local"):
        return True
    haystack = f"{result.title} {result.snippet}".lower()
    if any(str(term).lower() in haystack for term in grounding_plan.get("excluded_terms", [])):
        return False
    required = [str(term).lower() for term in grounding_plan.get("required_terms", []) if len(str(term)) >= 3]
    if not required:
        required = keywords_from_text(topic, 6)
    return not required or any(term in haystack for term in required)


def _to_research_sources(results: list[SearchResult]) -> list[ResearchSource]:
    seen: set[str] = set()
    sources: list[ResearchSource] = []
    for item in results:
        key = (item.url or item.title).lower()
        if key in seen:
            continue
        seen.add(key)
        sources.append(ResearchSource(title=item.title, url=item.url, snippet=item.snippet[:320], source=item.source))
    return sources


def _facts_from_sources(sources: list[ResearchSource]) -> list[str]:
    facts: list[str] = []
    for source in sources:
        for sentence in source.snippet.split("."):
            text = " ".join(sentence.split()).strip(" -")
            if len(text) >= 24 and text not in facts:
                facts.append(text[:240])
            if len(facts) >= 6:
                return facts
    return facts


def _brief_from_facts(
    topic: str,
    discovery: TopicDiscoveryOutput,
    facts: list[str],
    grounding_plan: dict[str, Any],
) -> str:
    details = "\n".join(f"- {fact}" for fact in facts[:5]) or "- No strong external fact found; keep the script honest and say less."
    note = grounding_plan.get("grounding_note", "Use concrete real-world context.")
    return (
        f"Topic: {discovery.selected_topic}. Selected angle: {discovery.selected_angle}. "
        f"{note} Use this as research context, not as a citation script.\nUseful details:\n{details}"
    )
