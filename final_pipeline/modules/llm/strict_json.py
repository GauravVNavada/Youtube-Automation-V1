from __future__ import annotations

import json
import re
from typing import Any


def loads_strict_json(text: str) -> dict[str, Any]:
    text = text.strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.S)
        if not match:
            raise
        data = json.loads(match.group(0))
    if not isinstance(data, dict):
        raise ValueError("Expected a JSON object")
    return data
