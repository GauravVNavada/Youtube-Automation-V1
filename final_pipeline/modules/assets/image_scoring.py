from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class ImageResult:
    url: str
    source: str
    width: int = 0
    height: int = 0
    description: str = ""
    page_url: str = ""
    creator: str = ""
    license: str = ""


def score_image(result: ImageResult, query: str, strict: bool = True) -> int:
    """Score image relevance without trusting source ordering blindly."""
    words = [w for w in re.split(r"[\s_,-]+", query.lower()) if len(w) > 2]
    haystack = f"{result.url} {result.description} {result.page_url} {result.creator} {result.license}".lower()
    matches = sum(1 for word in words if word in haystack)
    ratio = matches / max(1, len(words))
    if strict and result.source in {"pexels", "pixabay", "unsplash"} and ratio < 0.35:
        return 0
    if result.source not in {"pexels", "pixabay", "unsplash"} and ratio < 0.2:
        return 0

    score = matches * 20
    if result.width >= 1080 or result.height >= 1080:
        score += 20
    elif result.width >= 720 or result.height >= 720:
        score += 10
    score += {"duckduckgo": 22, "pexels": 18, "pixabay": 16, "unsplash": 15, "wikimedia": 14, "openverse": 13}.get(result.source, 6)
    if result.url.lower().split("?")[0].endswith((".jpg", ".jpeg", ".png", ".webp")):
        score += 8
    return score
