from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from app.schemas import ImageCue


class FallbackLevel:
    EXACT_SUBJECT = "exact_subject"
    SUBJECT_ALIAS = "subject_alias"
    CATEGORY_RELATED = "category_related"
    GENERIC_SCENE = "generic_scene"
    ABSTRACT_SYMBOLIC = "abstract_symbolic"
    TEXT_CARD = "text_card"
    FAIL = "fail"


SOURCE_TYPES = {
    "duckduckgo": ["search_result"],
    "wikimedia": ["entity_search", "open_license"],
    "pexels": ["generic_stock"],
    "pixabay": ["generic_stock"],
    "unsplash": ["generic_stock"],
    "openverse": ["open_license"],
    "generated_fallback": ["synthetic_subject", "text_card"],
    "cache": ["cached"],
    "local_upload": ["user_verified"],
}


GENERIC_TOPIC_HINTS = {
    "advice",
    "discipline",
    "focus",
    "habits",
    "loneliness",
    "motivation",
    "productivity",
    "save money",
    "study",
    "duration",
    "secons",
    "secs",
    "seconds",
}

ENTITY_STOP_WORDS = {
    "a",
    "about",
    "after",
    "and",
    "at",
    "before",
    "for",
    "first",
    "here",
    "how",
    "it",
    "make",
    "normal",
    "one",
    "real",
    "report",
    "short",
    "seconds",
    "secons",
    "duration",
    "story",
    "then",
    "the",
    "this",
    "video",
    "why",
}

KNOWN_ENTITY_PHRASES = (
    "thor",
    "iron man",
    "tony stark",
    "avengers",
    "naruto",
    "batman",
    "harry potter",
    "iphone 16",
    "tesla cybertruck",
    "taj mahal",
    "eiffel tower",
    "world war 2",
    "moon landing",
    "chandrayaan-3",
)


@dataclass(frozen=True)
class SubjectLock:
    enabled: bool
    subject: str = ""
    aliases: tuple[str, ...] = ()
    type: str = "generic_topic"
    strictness: str = "loose"


def infer_subject_lock(topic: str, research: dict[str, Any] | None = None) -> SubjectLock:
    subject = _explicit_subject_from_research(research or {}) or _entity_phrase(topic)
    if not subject:
        return SubjectLock(enabled=False)
    return SubjectLock(
        enabled=True,
        subject=subject,
        aliases=tuple(_aliases_for_subject(subject)),
        type=_subject_type(subject),
        strictness="hard",
    )


def apply_subject_lock_to_cues(cues: list[ImageCue], subject_lock: SubjectLock) -> list[ImageCue]:
    if not subject_lock.enabled:
        for cue in cues:
            cue.subject_lock = False
            cue.allowed_fallback_level = cue.allowed_fallback_level or FallbackLevel.GENERIC_SCENE
        return cues

    subjects = [subject_lock.subject]
    aliases = list(subject_lock.aliases)
    for index, cue in enumerate(cues):
        cue_has_subject = _mentions_any(cue.keyword, subjects + aliases)
        primary = index == 0 or cue.role == "primary_subject"
        cue.subject_lock = bool(cue.subject_lock or cue_has_subject or primary)
        if cue.subject_lock:
            cue.role = cue.role or "primary_subject"
            cue.required_subjects = cue.required_subjects or subjects
            cue.aliases = cue.aliases or aliases
            if cue.required_subjects and not _mentions_any(cue.keyword, cue.required_subjects + cue.aliases):
                cue.keyword = f"{cue.required_subjects[0]} {cue.keyword}"
            cue.allowed_fallback_level = FallbackLevel.SUBJECT_ALIAS
        else:
            cue.allowed_fallback_level = cue.allowed_fallback_level or FallbackLevel.GENERIC_SCENE
    return cues


def source_allowed_for_cue(cue: ImageCue, source: str) -> bool:
    if not cue.subject_lock:
        return True
    if source in {"duckduckgo", "pexels", "pixabay", "unsplash", "wikimedia", "openverse"}:
        return True
    source_types = SOURCE_TYPES.get(source, [])
    return bool({"entity_search", "synthetic_subject", "text_card", "user_verified"}.intersection(source_types))


def subject_match_score(cue: ImageCue, candidate: Any) -> float:
    required = cue.required_subjects or []
    aliases = cue.aliases or []
    if not cue.subject_lock or not required:
        return 1.0
    text = _candidate_text(candidate)
    if any(_contains_phrase(text, subject) for subject in required):
        return 1.0
    if any(_contains_phrase(text, alias) for alias in aliases):
        return 0.9
    distinctive = _distinctive_subject_terms(required[0])
    if distinctive and all(term in text for term in distinctive[:2]):
        return 0.82
    return 0.0


def scene_match_score(query: str, candidate: Any) -> float:
    words = [word for word in re.findall(r"[a-z0-9]+", query.lower()) if len(word) > 2]
    if not words:
        return 0.0
    text = _candidate_text(candidate)
    matches = sum(1 for word in words if word in text)
    return matches / max(1, len(words))


def subject_lock_repair_issue(cue: ImageCue, source: str) -> str:
    subject = ", ".join(cue.required_subjects or ["the named subject"])
    return f"Subject-locked cue expected {subject!r}, but selected asset source {source!r} is not subject-verified."


def _explicit_subject_from_research(research: dict[str, Any]) -> str:
    plan = research.get("grounding_plan")
    if not isinstance(plan, dict):
        return ""
    for key in ("subject", "entity", "target_subject", "main_subject"):
        value = str(plan.get(key) or "").strip()
        if value and not _looks_generic(value):
            return value[:80]
    return ""


def _entity_phrase(text: str) -> str:
    cleaned = " ".join(str(text or "").split())
    if not cleaned or _looks_generic(cleaned):
        return ""
    lower = cleaned.lower()
    for phrase in KNOWN_ENTITY_PHRASES:
        if phrase in lower:
            return _title_known_entity(phrase)
    patterns = [
        r"\b(?:[A-Z][A-Za-z0-9'_-]+|[A-Z]{2,}|i[A-Z][A-Za-z0-9]+|[A-Za-z]+-\d+)(?:\s+(?:[A-Z][A-Za-z0-9'_-]+|[A-Z]{2,}|\d+|[A-Za-z]+-\d+)){0,4}\b",
        r"\b[A-Za-z]+(?:\s+[A-Za-z]+){0,2}\s+\d{1,4}\b",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, cleaned):
            phrase = _trim_entity_phrase(match.group(0))
            if phrase and not _looks_generic(phrase):
                return phrase[:80]
    return ""


def _title_known_entity(phrase: str) -> str:
    special = {
        "iphone 16": "iPhone 16",
        "chandrayaan-3": "Chandrayaan-3",
    }
    return special.get(phrase, " ".join(word.upper() if word in {"iit"} else word.capitalize() for word in phrase.split()))


def _trim_entity_phrase(phrase: str) -> str:
    words = phrase.strip(" .,:;-").split()
    while words and words[0].lower() in ENTITY_STOP_WORDS:
        words.pop(0)
    while words and words[-1].lower() in ENTITY_STOP_WORDS:
        words.pop()
    return " ".join(words)


def _aliases_for_subject(subject: str) -> list[str]:
    aliases = [subject]
    words = subject.split()
    if len(words) > 1:
        aliases.append(words[-1])
        aliases.append(" ".join(words[:2]))
    lower = subject.lower()
    if "thor" in lower:
        aliases.extend(["Avengers Thor", "Marvel Thor", "God of Thunder", "Mjolnir", "Avengers"])
    if "iron man" in lower:
        aliases.extend(["Tony Stark", "Avengers Iron Man", "Iron Man suit", "arc reactor"])
    if "avengers" in lower:
        aliases.extend(["Marvel Avengers", "Iron Man", "Tony Stark"])
    if any(word.lower() in {"iron", "batman", "naruto", "avengers"} for word in words):
        aliases.append(f"{subject} character")
    return list(dict.fromkeys([item for item in aliases if item]))


def _subject_type(subject: str) -> str:
    lower = subject.lower()
    if any(term in lower for term in ("iphone", "tesla", "nike", "cybertruck")):
        return "brand_product"
    if any(term in lower for term in ("war", "landing", "9/11")):
        return "event"
    if any(term in lower for term in ("taj mahal", "tower", "iim", "iit")):
        return "specific_place"
    if any(term in lower for term in ("batman", "naruto", "iron man", "thor", "harry potter")):
        return "fictional_character"
    return "named_entity"


def _looks_generic(text: str) -> bool:
    lower = text.lower().strip()
    if lower in ENTITY_STOP_WORDS or lower in GENERIC_TOPIC_HINTS:
        return True
    if re.fullmatch(r"duration\s+\d+", lower) or re.fullmatch(r"\d+\s*(seconds?|secs?|s)", lower):
        return True
    if any(hint in lower for hint in GENERIC_TOPIC_HINTS):
        return True
    if lower.startswith(("how to ", "ways to ", "tips for ", "why you ", "a scary story", "scary story")):
        return True
    return False


def _mentions_any(text: str, phrases: list[str]) -> bool:
    haystack = str(text or "").lower()
    return any(_contains_phrase(haystack, phrase) for phrase in phrases)


def _contains_phrase(text: str, phrase: str) -> bool:
    phrase = str(phrase or "").lower().strip()
    if not phrase:
        return False
    return phrase in text


def _candidate_text(candidate: Any) -> str:
    return " ".join(
        str(value or "")
        for value in (
            getattr(candidate, "title", ""),
            getattr(candidate, "description", ""),
            getattr(candidate, "url", ""),
            getattr(candidate, "page_url", ""),
            getattr(candidate, "creator", ""),
            getattr(candidate, "license", ""),
            getattr(candidate, "source", ""),
        )
    ).lower()


def _distinctive_subject_terms(subject: str) -> list[str]:
    blocked = {"the", "and", "for", "with", "movie", "show", "game"}
    return [word for word in re.findall(r"[a-z0-9]+", subject.lower()) if len(word) > 2 and word not in blocked]
