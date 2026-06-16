from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from modules.assets.image_services import USER_AGENT


@dataclass
class VideoResult:
    url: str
    source: str
    width: int = 0
    height: int = 0
    duration: float = 0.0
    description: str = ""


def search_pexels_videos(query: str, api_key: str, per_page: int = 4) -> list[VideoResult]:
    if not api_key:
        return []
    params = urllib.parse.urlencode(
        {"query": query, "per_page": per_page, "orientation": "portrait"}
    )
    request = urllib.request.Request(
        f"https://api.pexels.com/videos/search?{params}",
        headers={"Authorization": api_key, "User-Agent": USER_AGENT},
    )
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Pexels video search failed: HTTP {exc.code}: {body}") from exc
    except Exception as exc:
        raise RuntimeError(f"Pexels video search failed: {type(exc).__name__}: {exc}") from exc

    results: list[VideoResult] = []
    for item in data.get("videos", []):
        description = " ".join(
            part
            for part in [
                str(item.get("url") or ""),
                str(item.get("user", {}).get("name") or ""),
            ]
            if part
        )
        duration = float(item.get("duration", 0.0) or 0.0)
        for file_info in item.get("video_files", []):
            link = file_info.get("link") or ""
            if not link or ".mp4" not in link.lower():
                continue
            results.append(
                VideoResult(
                    url=link,
                    source="pexels_video",
                    width=int(file_info.get("width", 0) or 0),
                    height=int(file_info.get("height", 0) or 0),
                    duration=duration,
                    description=description,
                )
            )
    return [result for result in results if result.url]


def score_video(result: VideoResult, query: str) -> int:
    score = 0
    if result.height > result.width:
        score += 45
    if result.height >= 1920:
        score += 25
    elif result.height >= 1280:
        score += 15
    if result.width >= 720:
        score += 10
    if 3 <= result.duration <= 20:
        score += 12
    elif result.duration > 20:
        score += 6
    haystack = f"{result.url} {result.description}".lower()
    for word in [part for part in query.lower().split() if len(part) > 2]:
        if word in haystack:
            score += 5
    return score


def download_video(url: str, output_path: Path) -> str:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=25) as response:
        content_type = response.headers.get("Content-Type", "")
        data = response.read()
    if not data or ("video" not in content_type and len(data) < 64 * 1024):
        raise RuntimeError(f"Downloaded response is not a usable video: {content_type}")
    output_path.write_bytes(data)
    return str(output_path)
