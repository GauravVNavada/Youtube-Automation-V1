from __future__ import annotations

import re
from pathlib import Path

from app.schemas import ScriptOutput, ValidationResult


def validate_script(script: ScriptOutput, min_words: int, max_words: int) -> ValidationResult:
    issues: list[str] = []
    if not script.title.strip():
        issues.append("Title is missing")
    if len(script.title) > 60:
        issues.append("Title exceeds 60 characters")
    if not script.narration.strip():
        issues.append("Narration is missing")
    elif not _ends_complete_sentence(script.narration):
        issues.append("Narration appears to end mid-sentence")
    if script.word_count < min_words:
        issues.append(f"Narration too short: {script.word_count} < {min_words}")
    if script.word_count > max_words:
        issues.append(f"Narration too long: {script.word_count} > {max_words}")
    if len(script.image_cues) < 3:
        issues.append("At least 3 image cues are required")
    if not script.hook_line.strip():
        issues.append("Hook line is missing")
    return ValidationResult(passed=not issues, issues=issues)


def validate_files(paths: list[str], label: str) -> ValidationResult:
    issues = [f"Missing {label}: {p}" for p in paths if not Path(p).exists()]
    return ValidationResult(passed=not issues, issues=issues)


def _ends_complete_sentence(text: str) -> bool:
    return bool(re.search(r"[.!?][\"')\]]*$", text.strip()))
