from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request

from modules.assets.image_scoring import ImageResult
from modules.assets.video_services import VideoResult


USER_AGENT = "DesktopApp/0.1"


def search_duckduckgo_images(query: str, max_results: int = 8) -> list[ImageResult]:
    vqd = _duckduckgo_vqd(query)
    if not vqd:
        return []
    params = urllib.parse.urlencode(
        {
            "l": "us-en",
            "o": "json",
            "q": query,
            "vqd": vqd,
            "f": ",,,",
            "p": "1",
        }
    )
    data = _read_json(f"https://duckduckgo.com/i.js?{params}", timeout=10)
    results: list[ImageResult] = []
    for item in data.get("results", [])[:max_results]:
        url = str(item.get("image") or "")
        if not url:
            continue
        results.append(
            ImageResult(
                url=url,
                source="duckduckgo",
                width=int(item.get("width") or 0),
                height=int(item.get("height") or 0),
                description=" ".join(
                    str(value)
                    for value in (item.get("title", ""), item.get("source", ""), item.get("url", ""))
                    if value
                ),
                page_url=str(item.get("url") or ""),
                creator=str(item.get("source") or ""),
                license="DuckDuckGo result",
            )
        )
    return results


def search_duckduckgo_videos(query: str, max_results: int = 8) -> list[VideoResult]:
    vqd = _duckduckgo_vqd(query)
    if not vqd:
        return []
    params = urllib.parse.urlencode(
        {
            "l": "us-en",
            "o": "json",
            "q": query,
            "vqd": vqd,
            "f": ",,,",
            "p": "1",
        }
    )
    data = _read_json(f"https://duckduckgo.com/v.js?{params}", timeout=10)
    results: list[VideoResult] = []
    for item in data.get("results", [])[:max_results]:
        url = str(item.get("content") or item.get("embed_url") or item.get("url") or "")
        if not _direct_video_url(url):
            continue
        results.append(
            VideoResult(
                url=url,
                title=" ".join(
                    str(value)
                    for value in (item.get("title", ""), item.get("publisher", ""), item.get("description", ""))
                    if value
                )[:300],
                source="duckduckgo",
                width=int(item.get("width") or 0),
                height=int(item.get("height") or 0),
                duration=_duration_seconds(item.get("duration")),
            )
        )
    return results


def _duckduckgo_vqd(query: str) -> str:
    params = urllib.parse.urlencode({"q": query})
    request = urllib.request.Request(
        f"https://duckduckgo.com/?{params}",
        headers={"User-Agent": USER_AGENT},
    )
    with urllib.request.urlopen(request, timeout=8) as response:
        body = response.read().decode("utf-8", errors="replace")
    patterns = (
        r"vqd=['\"]([^'\"]+)['\"]",
        r"vqd=([^&\"']+)",
        r'"vqd"\s*:\s*"([^"]+)"',
    )
    for pattern in patterns:
        match = re.search(pattern, body)
        if match:
            return urllib.parse.unquote(match.group(1))
    return ""


def _read_json(url: str, timeout: float) -> dict:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Referer": "https://duckduckgo.com/",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8", errors="replace"))


def _direct_video_url(url: str) -> bool:
    parsed = urllib.parse.urlparse(str(url or ""))
    path = parsed.path.lower()
    return path.endswith((".mp4", ".webm", ".mov", ".m4v"))


def _duration_seconds(value) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value or "")
    parts = [int(part) for part in re.findall(r"\d+", text)]
    if not parts:
        return 0.0
    seconds = 0
    for part in parts:
        seconds = seconds * 60 + part
    return float(seconds)
