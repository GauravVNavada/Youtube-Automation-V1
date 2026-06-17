from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request

from modules.assets.image_scoring import ImageResult


def search_unsplash_images(query: str, access_key: str, per_page: int = 8) -> list[ImageResult]:
    if not access_key:
        return []
    params = urllib.parse.urlencode({"query": query, "per_page": per_page, "orientation": "portrait"})
    request = urllib.request.Request(
        f"https://api.unsplash.com/search/photos?{params}",
        headers={"Authorization": f"Client-ID {access_key}", "Accept-Version": "v1"},
    )
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Unsplash search failed: HTTP {exc.code}: {body}") from exc
    except Exception as exc:
        raise RuntimeError(f"Unsplash search failed: {type(exc).__name__}: {exc}") from exc
    results = []
    for item in data.get("results", []):
        urls = item.get("urls", {}) if isinstance(item.get("urls"), dict) else {}
        user = item.get("user", {}) if isinstance(item.get("user"), dict) else {}
        alt = item.get("alt_description") or item.get("description") or ""
        photographer = user.get("name") or user.get("username") or ""
        page_url = ""
        links = item.get("links", {}) if isinstance(item.get("links"), dict) else {}
        if links:
            page_url = str(links.get("html") or "")
        results.append(
            ImageResult(
                url=urls.get("regular") or urls.get("full") or "",
                source="unsplash",
                width=int(item.get("width", 0) or 0),
                height=int(item.get("height", 0) or 0),
                description=" ".join(str(value) for value in (alt, page_url, photographer) if value),
                page_url=page_url,
                creator=str(photographer or ""),
                license="Unsplash License",
            )
        )
    return [result for result in results if result.url]
