from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request

from modules.assets.image_scoring import ImageResult


def search_pexels_images(query: str, api_key: str, per_page: int = 8) -> list[ImageResult]:
    if not api_key:
        return []
    params = urllib.parse.urlencode({"query": query, "per_page": per_page, "orientation": "portrait"})
    request = urllib.request.Request(
        f"https://api.pexels.com/v1/search?{params}",
        headers={
            "Authorization": api_key,
            "Accept": "application/json",
            "User-Agent": "DesktopApp/0.1",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        if exc.code == 403 and "1010" in body:
            raise RuntimeError(
                "Pexels search blocked by Pexels/Cloudflare 1010. "
                "This usually means the request IP, API key, or bot-protection rules were denied."
            ) from exc
        raise RuntimeError(f"Pexels search failed: HTTP {exc.code}: {body}") from exc
    except Exception as exc:
        raise RuntimeError(f"Pexels search failed: {type(exc).__name__}: {exc}") from exc
    results = []
    for item in data.get("photos", []):
        src = item.get("src", {})
        results.append(
            ImageResult(
                url=src.get("large2x") or src.get("large") or "",
                source="pexels",
                width=int(item.get("width", 0) or 0),
                height=int(item.get("height", 0) or 0),
                description=" ".join(
                    str(value)
                    for value in (item.get("alt", ""), item.get("url", ""), item.get("photographer", ""))
                    if value
                ),
                page_url=str(item.get("url") or ""),
                creator=str(item.get("photographer") or ""),
                license="Pexels License",
            )
        )
    return [result for result in results if result.url]
