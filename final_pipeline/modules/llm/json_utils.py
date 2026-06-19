from __future__ import annotations

import json
import re
from typing import Any


def parse_llm_json(text: str) -> dict[str, Any]:
    cleaned = _extract_json_object(text)
    attempts = [
        cleaned,
        _repair_missing_commas(cleaned),
        _remove_trailing_commas(_repair_missing_commas(cleaned)),
    ]
    last_error: Exception | None = None
    for attempt in attempts:
        try:
            data = json.loads(attempt)
            if not isinstance(data, dict):
                raise ValueError("Expected JSON object")
            return data
        except Exception as exc:
            last_error = exc
    raise ValueError(f"Could not parse LLM JSON: {last_error}")


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
        next_text = re.sub(r'(["}\]0-9])\s*\n\s*("[-A-Za-z0-9_ ]+"\s*:)', r"\1,\n\2", repaired)
        next_text = re.sub(r'(["}\]0-9])\s+("[-A-Za-z0-9_ ]+"\s*:)', r"\1, \2", next_text)
        next_text = re.sub(r'\b(true|false|null)\s*\n\s*("[-A-Za-z0-9_ ]+"\s*:)', r"\1,\n\2", next_text)
        next_text = re.sub(r'\b(true|false|null)\s+("[-A-Za-z0-9_ ]+"\s*:)', r"\1, \2", next_text)
        next_text = re.sub(r'(["}\]])\s*\n\s*([{\[])', r"\1,\n\2", next_text)
        next_text = re.sub(r"(\})\s*\n\s*(\{)", r"\1,\n\2", next_text)
        next_text = re.sub(r"(\])\s*\n\s*(\{)", r"\1,\n\2", next_text)
        if next_text == repaired:
            return repaired
        repaired = next_text
    return repaired


def _remove_trailing_commas(text: str) -> str:
    return re.sub(r",\s*([}\]])", r"\1", text)
