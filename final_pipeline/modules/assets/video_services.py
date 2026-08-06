from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import urllib.request


@dataclass
class VideoResult:
    url: str
    title: str = ""
    source: str = "pexels"
    width: int = 0
    height: int = 0
    duration: float = 0.0


def search_pexels_videos(query: str, api_key: str, max_results: int = 8) -> list[VideoResult]:
    if not api_key:
        return []
    import json
    import urllib.parse

    params = urllib.parse.urlencode({"query": query, "orientation": "portrait", "per_page": max_results})
    request = urllib.request.Request(
        f"https://api.pexels.com/videos/search?{params}",
        headers={"Authorization": api_key, "User-Agent": "DesktopApp/0.1"},
    )
    with urllib.request.urlopen(request, timeout=12) as response:
        data = json.loads(response.read().decode("utf-8", errors="replace"))
    results: list[VideoResult] = []
    for item in data.get("videos", []):
        files = sorted(item.get("video_files", []), key=lambda f: (f.get("width", 0) * f.get("height", 0)), reverse=True)
        file_item = next((f for f in files if f.get("link")), None)
        if file_item:
            results.append(
                VideoResult(
                    url=file_item["link"],
                    title=str(item.get("url") or query),
                    source="pexels",
                    width=int(file_item.get("width") or 0),
                    height=int(file_item.get("height") or 0),
                    duration=float(item.get("duration") or 0.0),
                )
            )
    return results


def score_video(result: VideoResult, query: str) -> float:
    score = 1.0
    if result.height >= result.width:
        score += 1.0
    if result.duration >= 3:
        score += 0.5
    title = result.title.lower()
    for word in query.lower().split():
        if len(word) > 2 and word in title:
            score += 0.2
    return score


def download_video(url: str, target: Path) -> str:
    target.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": "DesktopApp/0.1"})
    with urllib.request.urlopen(request, timeout=30) as response:
        target.write_bytes(response.read())
    return str(target)
