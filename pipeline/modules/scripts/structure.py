from __future__ import annotations

import re


_ABRUPT_ENDING_PATTERNS = [
    r"\b(and then|but then|until|when|because|as soon as)\.?$",
    r",\s*$",
]

_VAGUE_ENDING_PATTERNS = [
    r"\bit all made sense\.?$",
    r"\bthat was when everything changed\.?$",
    r"\bno one knew why\.?$",
]

_ALERT_BEAT_MARKERS = {
    "but",
    "then",
    "strange",
    "warning",
    "found",
    "noticed",
    "reported",
    "realized",
    "suddenly",
}


def parse_script_sections(narration: str) -> dict[str, str]:
    sentences = _sentences(narration)
    if not sentences:
        return {"hook": "", "body": "", "ending": ""}
    return {
        "hook": sentences[0],
        "body": " ".join(sentences[1:-1]),
        "ending": sentences[-1] if len(sentences) > 1 else "",
    }


def normalize_script_sections(narration: str) -> str:
    return " ".join(_sentences(narration))


def derive_script_sections(narration: str) -> list[str]:
    return _sentences(narration)


def validate_narrative_structure(narration: str) -> list[str]:
    issues: list[str] = []
    sentences = _sentences(narration)
    if len(sentences) < 4:
        issues.append("narration needs a hook, body, alert beat, and ending")
    ending = sentences[-1] if sentences else ""
    if not re.search(r"[.!?][\"')\]]*$", narration.strip()):
        issues.append("narration must end with final punctuation")
    if any(re.search(pattern, ending.strip(), re.I) for pattern in _ABRUPT_ENDING_PATTERNS):
        issues.append("ending feels cut off; close the idea with a complete final sentence")
    if any(re.search(pattern, ending.strip(), re.I) for pattern in _VAGUE_ENDING_PATTERNS):
        issues.append("ending is too vague; use a concrete final reveal")
    middle = " ".join(sentences[1:-1]).lower()
    if sentences and not any(marker in middle for marker in _ALERT_BEAT_MARKERS):
        issues.append("middle needs at least one alert beat or surprising concrete detail")
    return issues


def polish_script_ending(narration: str, genre_id: str = "") -> str:
    text = " ".join(narration.split()).strip()
    if not text:
        return text
    if not re.search(r"[.!?][\"')\]]*$", text):
        text = text.rstrip(",;:") + "."
    ending = last_sentence(text)
    if any(re.search(pattern, ending, re.I) for pattern in _ABRUPT_ENDING_PATTERNS):
        replacement = "That was the detail people remembered later."
        if genre_id in {"scary_stories", "mystery_stories"}:
            replacement = "That was the moment the warning finally felt real."
        text = replace_last_sentence(text, replacement)
    return text


def last_sentence(text: str) -> str:
    sentences = _sentences(text)
    return sentences[-1] if sentences else ""


def replace_last_sentence(text: str, replacement: str) -> str:
    sentences = _sentences(text)
    if not sentences:
        return replacement
    sentences[-1] = replacement
    return " ".join(sentences)


def _sentences(text: str) -> list[str]:
    return [item.strip() for item in re.findall(r"[^.!?]+[.!?]", text.strip()) if item.strip()]
