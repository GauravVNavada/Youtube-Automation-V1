from __future__ import annotations

import re
from dataclasses import asdict, is_dataclass
from typing import Any

from app.schemas import ImageCue, ScriptOutput, VisualStylePlan


_PROTECTED_REPLACEMENTS: tuple[tuple[str, str, str], ...] = (
    (r"\btony\s+stark\b", "Tony Stark", "the armored tech hero"),
    (r"\biron\s*man\b", "Iron Man", "armored tech hero"),
    (r"\bavengers?\b", "Avengers", "original superhero team"),
    (r"\bmarvel\b", "Marvel", "comic-book"),
    (r"\bcaptain\s+america\b", "Captain America", "shield-bearing hero"),
    (r"\bsteve\s+rogers\b", "Steve Rogers", "shield-bearing hero"),
    (r"\bspider[-\s]?man\b", "Spider-Man", "masked web hero"),
    (r"\bbruce\s+banner\b", "Bruce Banner", "giant powerhouse"),
    (r"\bhulk\b", "Hulk", "giant powerhouse"),
    (r"\bthor\b", "Thor", "storm-powered hero"),
    (r"\bblack\s+widow\b", "Black Widow", "stealth hero"),
    (r"\bhawkeye\b", "Hawkeye", "archer hero"),
    (r"\bthanos\b", "Thanos", "cosmic villain"),
    (r"\bdeadpool\b", "Deadpool", "masked antihero"),
    (r"\bwolverine\b", "Wolverine", "clawed mutant hero"),
    (r"\bx[-\s]?men\b", "X-Men", "mutant hero team"),
    (r"\bbatman\b", "Batman", "masked vigilante"),
    (r"\bbruce\s+wayne\b", "Bruce Wayne", "masked vigilante"),
    (r"\bsuperman\b", "Superman", "flying solar-powered hero"),
    (r"\bwonder\s+woman\b", "Wonder Woman", "warrior heroine"),
    (r"\bjustice\s+league\b", "Justice League", "original superhero league"),
    (r"\bdc\s+comics\b", "DC Comics", "comic-book"),
    (r"\bjoker\b", "Joker", "chaotic masked villain"),
)

_ILLUSTRATION_TERMS = {
    "anime",
    "manga",
    "comic",
    "comics",
    "cartoon",
    "illustration",
    "illustrated",
    "graphic novel",
    "concept art",
    "digital art",
    "storyboard",
}

_FICTION_TERMS = {
    "superhero",
    "superheroes",
    "hero team",
    "masked hero",
    "armored hero",
    "armored",
    "cyberpunk",
    "sci fi",
    "science fiction",
    "alien",
    "robot",
    "mecha",
    "dragon",
    "wizard",
    "magic",
    "fantasy",
    "mutant",
    "space battle",
    "power armor",
}

_QUERY_BLOCKLIST = {
    "the",
    "and",
    "with",
    "all",
    "other",
    "against",
    "fight",
    "fights",
    "fighting",
    "battle",
    "battling",
    "style",
    "video",
    "short",
    "seconds",
    "second",
    "scene",
    "photo",
    "image",
    "realistic",
    "real",
    "movie",
    "film",
}


def build_visual_style_plan(topic: str, genre_id: str = "", user_notes: str = "") -> VisualStylePlan:
    """Decide whether a request should be stock-video-first or stylized image-first."""
    combined = f"{topic} {user_notes}".strip()
    lowered = _normalize(combined)
    matched = _matched_replacements(lowered)
    illustration_hits = _term_hits(lowered, _ILLUSTRATION_TERMS)
    fiction_hits = _term_hits(lowered, _FICTION_TERMS)

    needs_stylized = bool(matched or illustration_hits or len(fiction_hits) >= 2)
    mode = "illustration" if needs_stylized else "stock_video"
    render_style = _render_style(lowered, matched, illustration_hits, fiction_hits) if needs_stylized else "natural"
    sanitized_topic = sanitize_text(topic)

    if not needs_stylized:
        return VisualStylePlan(
            original_topic=topic,
            sanitized_topic=sanitized_topic,
            mode=mode,
            render_style=render_style,
            asset_strategy="hybrid_video",
            search_style_terms=[],
            blocked_terms=[],
            replacements={},
            prompt_guidance=[
                "Use concrete, real-world visual cues that stock image and video providers can satisfy.",
            ],
            source_policy="stock_video_first",
        )

    search_terms = _style_terms_for(render_style)
    replacements = {label: replacement for _, label, replacement in _PROTECTED_REPLACEMENTS if label in matched}
    return VisualStylePlan(
        original_topic=topic,
        sanitized_topic=sanitized_topic,
        mode=mode,
        render_style=render_style,
        asset_strategy="image_first",
        search_style_terms=search_terms,
        blocked_terms=matched,
        replacements=replacements,
        prompt_guidance=[
            "Use original fictional characters only; do not use franchise names, logos, actor likenesses, or exact costume designs.",
            "Write visual cues as stylized illustration searches, not real-world stock-footage searches.",
            "Prefer dynamic panels, dramatic poses, impact moments, city scale, readable silhouettes, and clean subject/object/setting nouns.",
            "Avoid exact movie, brand, or character names in narration, title, hashtags, image cues, and thumbnail text.",
        ],
        source_policy="image_first_no_stock_video",
    )


def coerce_visual_style_plan(value: VisualStylePlan | dict[str, Any] | None) -> VisualStylePlan:
    if isinstance(value, VisualStylePlan):
        return value
    if is_dataclass(value):
        return coerce_visual_style_plan(asdict(value))
    if isinstance(value, dict):
        return VisualStylePlan(
            original_topic=str(value.get("original_topic") or ""),
            sanitized_topic=str(value.get("sanitized_topic") or value.get("original_topic") or ""),
            mode=str(value.get("mode") or "stock_video"),
            render_style=str(value.get("render_style") or "natural"),
            asset_strategy=str(value.get("asset_strategy") or "hybrid_video"),
            search_style_terms=[str(item) for item in value.get("search_style_terms", [])],
            blocked_terms=[str(item) for item in value.get("blocked_terms", [])],
            replacements={str(k): str(v) for k, v in dict(value.get("replacements", {})).items()},
            prompt_guidance=[str(item) for item in value.get("prompt_guidance", [])],
            source_policy=str(value.get("source_policy") or "stock_video_first"),
        )
    return VisualStylePlan(original_topic="", sanitized_topic="")


def visual_style_to_dict(value: VisualStylePlan | dict[str, Any] | None) -> dict[str, Any]:
    return asdict(coerce_visual_style_plan(value))


def should_skip_stock_video(value: VisualStylePlan | dict[str, Any] | None) -> bool:
    plan = coerce_visual_style_plan(value)
    return plan.asset_strategy == "image_first" or plan.source_policy == "image_first_no_stock_video"


def sanitize_text(text: str) -> str:
    cleaned = str(text or "")
    for pattern, _, replacement in _PROTECTED_REPLACEMENTS:
        cleaned = re.sub(pattern, replacement, cleaned, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", cleaned).strip()


def apply_visual_style_to_script(script: ScriptOutput, value: VisualStylePlan | dict[str, Any] | None) -> ScriptOutput:
    plan = coerce_visual_style_plan(value)
    if plan.mode != "illustration" and not plan.blocked_terms:
        return script
    script.title = sanitize_text(script.title)[:60] or script.title
    script.narration = sanitize_text(script.narration)
    script.hook_line = sanitize_text(script.hook_line)
    script.description = sanitize_text(script.description)
    script.hashtags = [_safe_hashtag(item) for item in script.hashtags]
    script.emphasis_words = [sanitize_text(item) for item in script.emphasis_words if sanitize_text(item)]
    script.image_cues = apply_visual_style_to_cues(script.image_cues, plan)
    return script


def apply_visual_style_to_cues(cues: list[ImageCue], value: VisualStylePlan | dict[str, Any] | None) -> list[ImageCue]:
    plan = coerce_visual_style_plan(value)
    if plan.mode != "illustration" and not plan.blocked_terms:
        return [ImageCue(keyword=sanitize_text(cue.keyword), timestamp_hint=cue.timestamp_hint, mood=cue.mood) for cue in cues]
    return [
        ImageCue(
            keyword=stylized_asset_keyword(cue.keyword, plan),
            timestamp_hint=cue.timestamp_hint,
            mood=cue.mood,
        )
        for cue in cues
    ]


def stylized_query_variants(
    keyword: str,
    value: VisualStylePlan | dict[str, Any] | None,
    fallback_topic: str = "",
) -> list[str]:
    plan = coerce_visual_style_plan(value)
    core = _query_core(keyword)
    if len(core.split()) < 3:
        core = _query_core(fallback_topic or plan.sanitized_topic or plan.original_topic)
    if len(core.split()) < 3:
        core = "original hero dramatic city"

    terms = plan.search_style_terms or _style_terms_for(plan.render_style)
    variants = [
        f"{core} {terms[0]}",
        f"{core} {terms[1] if len(terms) > 1 else terms[0]}",
        f"{core} dynamic action pose",
        f"original superhero team {terms[0]}",
        f"armored tech hero city battle {terms[0]}",
        f"dramatic impact panel {terms[0]}",
    ]
    return _dedupe_queries(variants)


def stylized_asset_keyword(keyword: str, value: VisualStylePlan | dict[str, Any] | None) -> str:
    plan = coerce_visual_style_plan(value)
    if plan.mode != "illustration":
        return sanitize_text(keyword)
    return stylized_query_variants(keyword, plan)[0]


def _render_style(
    lowered: str,
    matched: list[str],
    illustration_hits: set[str],
    fiction_hits: set[str],
) -> str:
    if "anime" in illustration_hits or "manga" in illustration_hits:
        return "anime"
    if matched or "superhero" in fiction_hits or "superheroes" in fiction_hits or "comic" in illustration_hits:
        return "comic_book"
    if "fantasy" in fiction_hits or "dragon" in fiction_hits or "wizard" in fiction_hits or "magic" in fiction_hits:
        return "fantasy_concept"
    if "cyberpunk" in fiction_hits or "sci fi" in fiction_hits or "science fiction" in fiction_hits:
        return "sci_fi_concept"
    return "illustration"


def _style_terms_for(render_style: str) -> list[str]:
    if render_style == "anime":
        return ["anime key art", "manga action panel", "dynamic anime illustration"]
    if render_style == "fantasy_concept":
        return ["fantasy concept art", "painted fantasy illustration", "dramatic fantasy key art"]
    if render_style == "sci_fi_concept":
        return ["sci fi concept art", "cinematic digital illustration", "futuristic key art"]
    if render_style == "comic_book":
        return ["comic book illustration", "graphic novel panel", "dynamic superhero comic art"]
    return ["digital illustration", "storyboard art", "cinematic key art"]


def _matched_replacements(lowered: str) -> list[str]:
    matched: list[str] = []
    for pattern, label, _ in _PROTECTED_REPLACEMENTS:
        if re.search(pattern, lowered, flags=re.IGNORECASE):
            matched.append(label)
    return matched


def _term_hits(lowered: str, terms: set[str]) -> set[str]:
    hits: set[str] = set()
    padded = f" {lowered} "
    for term in terms:
        if " " in term:
            if f" {term} " in padded:
                hits.add(term)
        elif re.search(rf"\b{re.escape(term)}\b", lowered):
            hits.add(term)
    return hits


def _query_core(text: str) -> str:
    sanitized = sanitize_text(text).lower()
    words: list[str] = []
    for raw in sanitized.split():
        word = re.sub(r"[^a-z0-9]", "", raw)
        if len(word) < 3 or word in _QUERY_BLOCKLIST:
            continue
        words.append(word)
    return " ".join(words[:7])


def _safe_hashtag(value: str) -> str:
    text = sanitize_text(str(value or "")).lower()
    words = [re.sub(r"[^a-z0-9]", "", part) for part in text.split()]
    words = [word for word in words if word and word not in {"comicbook", "comic"}]
    if not words:
        return "#shorts"
    return "#" + "".join(words)[:32]


def _dedupe_queries(queries: list[str]) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for query in queries:
        normalized = re.sub(r"\s+", " ", sanitize_text(query)).strip()
        key = normalized.lower()
        if normalized and key not in seen:
            cleaned.append(normalized)
            seen.add(key)
    return cleaned


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").lower()).strip()
