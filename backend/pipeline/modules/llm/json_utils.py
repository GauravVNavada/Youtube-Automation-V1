from __future__ import annotations

import json
import re
from typing import Any


def parse_llm_json(text: str) -> dict[str, Any]:
    """Parse JSON returned by an LLM, repairing common formatting slips."""
    cleaned = _extract_json_object(text)
    repaired = _repair_missing_commas(cleaned)
    attempts = [
        cleaned,
        repaired,
        _remove_trailing_commas(repaired),
    ]
    last_error: json.JSONDecodeError | None = None
    for candidate in attempts:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError as exc:
            last_error = exc
            continue
        if not isinstance(parsed, dict):
            raise ValueError("LLM response JSON must be an object")
        return parsed
    if last_error:
        raise ValueError(f"LLM returned malformed JSON: {last_error}") from last_error
    raise ValueError("LLM returned empty JSON")


def _extract_json_object(text: str) -> str:
    cleaned = re.sub(r"```(?:json)?|```", "", text.strip()).strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start >= 0 and end >= start:
        return cleaned[start : end + 1]
    return cleaned


def _repair_missing_commas(text: str) -> str:
    repaired = text
    for _ in range(3):
        next_text = re.sub(r'(["}\]])\s*\n\s*("[-A-Za-z0-9_ ]+"\s*:)', r'\1,\n\2', repaired)
        next_text = re.sub(r'(["}\]])\s+("[-A-Za-z0-9_ ]+"\s*:)', r'\1, \2', next_text)
        next_text = re.sub(r'(["}\]])\s*\n\s*([{\[])', r'\1,\n\2', next_text)
        next_text = re.sub(r'(\})\s*\n\s*(\{)', r'\1,\n\2', next_text)
        next_text = re.sub(r'(\])\s*\n\s*(\{)', r'\1,\n\2', next_text)
        next_text = re.sub(r'("[^"]*")\s*\n\s*("[^"]*")(?=\s*[,}\]])', r'\1,\n\2', next_text)
        if next_text == repaired:
            break
        repaired = next_text
    return repaired


def _remove_trailing_commas(text: str) -> str:
    return re.sub(r",\s*([}\]])", r"\1", text)
