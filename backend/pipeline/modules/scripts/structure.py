from __future__ import annotations

import re
from typing import Any

from app.schemas import ScriptOutput, ScriptSection


SECTION_ORDER = ("header", "mid", "footer")

_ABRUPT_ENDING_PATTERNS = (
    r"\bthen it stopped\b",
    r"\bthen everything stopped\b",
    r"\band then silence\b",
    r"\bthere was only silence\b",
    r"\beverything went black\b",
    r"\bthe screen went black\b",
    r"\band that was it\b",
    r"\bto be continued\b",
    r"\bwhat happens next\b",
    r"\bfollow for part\b",
)

_VAGUE_ENDING_PATTERNS = (
    r"\bthe warning finally made sense\b",
    r"\bthe clue finally made sense\b",
    r"\bthen it all made sense\b",
    r"\beverything made sense\b",
    r"\bno one ever forgot\b",
    r"\bthey never went back\b",
    r"\bthat was the real horror\b",
)

_ALERT_BEAT_MARKERS = (
    "but the strange part",
    "but the scary part",
    "but here is the",
    "then they noticed",
    "then he noticed",
    "then she noticed",
    "what they found",
    "what he found",
    "what she found",
    "the detail no one expected",
    "the shocking part",
    "the worst part",
    "here is the part",
    "that is when",
    "until they",
    "until he",
    "until she",
)

_FACT_GENRES = {"history_facts", "science_facts", "motivational"}
_STORY_GENRES = {"scary_stories", "mystery_stories", "reddit_stories", "relationship"}


def parse_script_sections(data: dict[str, Any], narration: str) -> list[ScriptSection]:
    raw_sections = data.get("script_sections") or data.get("sections") or []
    sections: list[ScriptSection] = []
    if isinstance(raw_sections, list):
        for item in raw_sections:
            if not isinstance(item, dict):
                continue
            name = _normalize_section_name(item.get("name") or item.get("section") or "")
            if not name:
                continue
            text = _clean_text(item.get("narration") or item.get("text") or "")
            sections.append(
                ScriptSection(
                    name=name,
                    purpose=_clean_text(item.get("purpose") or _default_purpose(name)),
                    narration=text,
                    word_count=len(_words(text)),
                )
            )
    return normalize_script_sections(sections, narration)


def normalize_script_sections(sections: list[ScriptSection], narration: str) -> list[ScriptSection]:
    by_name: dict[str, ScriptSection] = {}
    for section in sections:
        name = _normalize_section_name(section.name)
        if name and section.narration.strip() and name not in by_name:
            by_name[name] = ScriptSection(
                name=name,
                purpose=section.purpose.strip() or _default_purpose(name),
                narration=_clean_text(section.narration),
                word_count=len(_words(section.narration)),
            )
    if all(name in by_name for name in SECTION_ORDER):
        return [by_name[name] for name in SECTION_ORDER]
    return derive_script_sections(narration)


def derive_script_sections(narration: str) -> list[ScriptSection]:
    sentences = _sentences(narration)
    if not sentences:
        return []
    if len(sentences) == 1:
        thirds = [sentences[0], sentences[0], sentences[0]]
    elif len(sentences) == 2:
        thirds = [sentences[0], sentences[1], sentences[1]]
    else:
        header_end = max(1, len(sentences) // 3)
        footer_start = max(header_end + 1, len(sentences) - max(1, len(sentences) // 3))
        thirds = [
            " ".join(sentences[:header_end]),
            " ".join(sentences[header_end:footer_start]),
            " ".join(sentences[footer_start:]),
        ]
    return [
        ScriptSection("header", _default_purpose("header"), _clean_text(thirds[0]), len(_words(thirds[0]))),
        ScriptSection("mid", _default_purpose("mid"), _clean_text(thirds[1]), len(_words(thirds[1]))),
        ScriptSection("footer", _default_purpose("footer"), _clean_text(thirds[2]), len(_words(thirds[2]))),
    ]


def validate_narrative_structure(script: ScriptOutput, genre_id: str = "") -> list[str]:
    issues: list[str] = []
    sections = normalize_script_sections(script.script_sections, script.narration)
    names = [section.name for section in sections]
    for name in SECTION_ORDER:
        if name not in names:
            issues.append(f"Script section is missing: {name}")

    if sections:
        for section in sections:
            if section.word_count < 5:
                issues.append(f"Script section is too thin: {section.name}")
        footer = next((section for section in sections if section.name == "footer"), None)
        if footer and len(_sentences(footer.narration)) < 1:
            issues.append("Footer section must contain the payoff or conclusion")

    last = last_sentence(script.narration)
    if not last:
        issues.append("Narration needs a final payoff sentence")
        return issues
    last_words = _words(last)
    lowered_last = last.lower()
    if len(last_words) < 6:
        issues.append("Narration ending is too abrupt; add a clear payoff or conclusion sentence")
    if any(re.search(pattern, lowered_last) for pattern in _ABRUPT_ENDING_PATTERNS):
        issues.append("Narration ending feels like a direct stop or pause; resolve the idea instead")
    if any(re.search(pattern, lowered_last) for pattern in _VAGUE_ENDING_PATTERNS):
        issues.append("Narration ending is too vague; explain the actual reveal, warning, consequence, or lesson")

    genre = (genre_id or "").lower()
    if genre in _FACT_GENRES and not _has_fact_conclusion(last):
        issues.append("Fact-style narration must end by explaining why the fact matters")
    if genre in _STORY_GENRES and len(_sentences(script.narration)) >= 3 and not _has_story_payoff(last):
        issues.append("Story narration must end with a concrete reveal, consequence, or emotional payoff")
    if len(_sentences(script.narration)) >= 4 and not _has_alert_beat(script.narration):
        issues.append("Narration needs a clear mid-story alert beat or surprising turn")

    return _dedupe(issues)


def polish_script_ending(script: ScriptOutput, genre_id: str, max_words: int) -> ScriptOutput:
    """Deterministically strengthen simple abrupt endings without calling another model."""
    issues = validate_narrative_structure(script, genre_id)
    if not any("ending" in issue.lower() or "payoff" in issue.lower() or "matters" in issue.lower() for issue in issues):
        script.script_sections = normalize_script_sections(script.script_sections, script.narration)
        return script

    sentence = _fallback_closing_sentence(genre_id)
    current_words = _words(script.narration)
    closing_words = _words(sentence)
    if len(current_words) + len(closing_words) <= max_words:
        script.narration = _clean_text(f"{script.narration.rstrip()} {sentence}")
    else:
        script.narration = replace_last_sentence(script.narration, sentence)
    script.word_count = len(_words(script.narration))
    script.hook_line = _first_sentence(script.narration) or script.hook_line
    script.script_sections = derive_script_sections(script.narration)
    return script


def last_sentence(text: str) -> str:
    sentences = _sentences(text)
    return sentences[-1] if sentences else ""


def replace_last_sentence(text: str, replacement: str) -> str:
    sentences = _sentences(text)
    if not sentences:
        return replacement
    sentences[-1] = replacement
    return _clean_text(" ".join(sentences))


def _normalize_section_name(value: Any) -> str:
    text = re.sub(r"[^a-z]", "", str(value or "").lower())
    if text in {"hook", "intro", "opening", "setup", "start"}:
        return "header"
    if text in {"body", "middle", "context", "development", "turn"}:
        return "mid"
    if text in {"ending", "end", "outro", "payoff", "conclusion", "close"}:
        return "footer"
    return text if text in SECTION_ORDER else ""


def _default_purpose(name: str) -> str:
    return {
        "header": "Hook the viewer and make a clear promise.",
        "mid": "Develop only the most relevant beats or facts.",
        "footer": "Deliver the reveal, consequence, lesson, or why-it-matters conclusion.",
    }.get(name, "Support the main idea.")


def _fallback_closing_sentence(genre_id: str) -> str:
    genre = (genre_id or "").lower()
    if genre == "history_facts":
        return "That is why this detail still changes how the past feels today."
    if genre == "science_facts":
        return "That is the part that turns a strange fact into the real lesson."
    if genre == "motivational":
        return "That is the moment the struggle finally becomes the lesson."
    if genre in {"reddit_stories", "relationship"}:
        return "That was the moment everyone finally understood the truth."
    if genre == "mystery_stories":
        return "That final clue made the whole story impossible to ignore."
    if genre == "scary_stories":
        return "The warning was simple: someone had been inside before them, and it wanted the room opened again."
    return "That is why the ending matters, not just the moment before it."


def _has_fact_conclusion(sentence: str) -> bool:
    text = f" {sentence.lower()} "
    markers = (
        " that is why ",
        " this is why ",
        " that means ",
        " it means ",
        " matters ",
        " today ",
        " still ",
        " lesson ",
        " shows ",
        " proves ",
        " changes ",
        " because ",
        " under your tires ",
        " not buried ",
    )
    return any(marker in text for marker in markers)


def _has_story_payoff(sentence: str) -> bool:
    text = f" {sentence.lower()} "
    markers = (
        " finally ",
        " truth ",
        " reveal ",
        " revealed ",
        " realized ",
        " understood ",
        " because ",
        " warning ",
        " clue ",
        " still ",
        " never ",
        " always ",
        " made sense ",
        " mattered ",
        " saved ",
        " lost ",
        " cost ",
        " behind ",
        " inside ",
        " answered ",
        " returned ",
        " remained ",
        " changed ",
        " knocked ",
        " knew ",
        " next ",
        " opened ",
        " whispered ",
        " watched ",
    )
    return any(marker in text for marker in markers)


def _has_alert_beat(text: str) -> bool:
    lowered = f" {_clean_text(text).lower()} "
    return any(marker in lowered for marker in _ALERT_BEAT_MARKERS)


def _sentences(text: str) -> list[str]:
    cleaned = _clean_text(text)
    if not cleaned:
        return []
    matches = re.findall(r"[^.!?]+[.!?][\"')\]]*", cleaned)
    if matches:
        return [_clean_text(match) for match in matches if _clean_text(match)]
    return [cleaned]


def _first_sentence(text: str) -> str:
    sentences = _sentences(text)
    return sentences[0] if sentences else ""


def _words(text: str) -> list[str]:
    return [word for word in str(text or "").split() if word.strip()]


def _clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _dedupe(items: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for item in items:
        if item not in seen:
            deduped.append(item)
            seen.add(item)
    return deduped
