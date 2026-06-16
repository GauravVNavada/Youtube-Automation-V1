from __future__ import annotations

import re
from pathlib import Path

from app.schemas import ScriptOutput, ValidationResult
from modules.safety.guardrails import validate_generated_text
from modules.scripts.structure import validate_narrative_structure


def validate_script(script: ScriptOutput, min_words: int, max_words: int, genre_id: str = "") -> ValidationResult:
    issues: list[str] = []
    if not script.title.strip():
        issues.append("Title is missing")
    if len(script.title) > 60:
        issues.append("Title exceeds 60 characters")
    if not script.narration.strip():
        issues.append("Narration is missing")
    elif not _ends_complete_sentence(script.narration):
        issues.append("Narration appears to end mid-sentence")
    try:
        validate_generated_text(" ".join([script.title, script.narration, script.description]))
    except RuntimeError as exc:
        issues.append(str(exc))
    issues.extend(_plain_language_issues(script.narration))
    if script.word_count < min_words:
        issues.append(f"Narration too short: {script.word_count} < {min_words}")
    if script.word_count > max_words:
        issues.append(f"Narration too long: {script.word_count} > {max_words}")
    minimum_image_cues = _minimum_image_cues(script.estimated_duration)
    if len(script.image_cues) < minimum_image_cues:
        issues.append(f"At least {minimum_image_cues} image cues are required")
    if not script.hook_line.strip():
        issues.append("Hook line is missing")
    issues.extend(validate_narrative_structure(script, genre_id))
    return ValidationResult(passed=not issues, issues=issues)


def validate_files(paths: list[str], label: str) -> ValidationResult:
    issues = [f"Missing {label}: {p}" for p in paths if not Path(p).exists()]
    return ValidationResult(passed=not issues, issues=issues)


def _ends_complete_sentence(text: str) -> bool:
    return bool(re.search(r"[.!?][\"')\]]*$", text.strip()))


def _minimum_image_cues(duration: int) -> int:
    if duration >= 120:
        return 18
    if duration >= 90:
        return 14
    if duration >= 60:
        return 10
    if duration >= 45:
        return 8
    if duration >= 30:
        return 6
    return 6


def _plain_language_issues(text: str) -> list[str]:
    sentences = [part.strip() for part in re.findall(r"[^.!?]+[.!?]", text) if part.strip()]
    words = re.findall(r"[A-Za-z]+", text)
    if not words:
        return []
    issues: list[str] = []
    if sentences:
        average_sentence_words = len(words) / len(sentences)
        if average_sentence_words > 18:
            issues.append("Narration sentences are too long; use shorter layman sentences")
    hard_words = [
        word
        for word in words
        if len(word) >= 12 and not word[:1].isupper()
    ]
    if len(hard_words) > max(3, len(words) // 18):
        issues.append("Narration uses too many hard words; rewrite in simple everyday English")
    return issues
