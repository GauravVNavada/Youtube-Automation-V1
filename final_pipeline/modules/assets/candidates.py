from __future__ import annotations

from dataclasses import dataclass
from typing import Any
import urllib.parse


@dataclass
class AssetCandidate:
    media_type: str
    source: str
    url: str
    score: float
    subject_match: float = 0.0
    scene_match: float = 0.0
    title: str = ""
    description: str = ""
    page_url: str = ""
    width: int = 0
    height: int = 0
    duration: float = 0.0
    result: Any = None


def asset_key(candidate: AssetCandidate) -> str:
    return normalized_url(candidate.url)


def normalized_url(url: str) -> str:
    parsed = urllib.parse.urlparse(str(url or "").strip())
    if not parsed.scheme or not parsed.netloc:
        return str(url or "").strip().lower()
    path = parsed.path.rstrip("/")
    return urllib.parse.urlunparse((parsed.scheme.lower(), parsed.netloc.lower(), path, "", "", "")).lower()
