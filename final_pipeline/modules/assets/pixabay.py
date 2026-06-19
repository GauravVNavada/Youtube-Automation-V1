from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request

from modules.assets.image_scoring import ImageResult


def search_pixabay_images(query: str, api_key: str, per_page: int = 8) -> list[ImageResult]:
    if not api_key:
        return []
    params = urllib.parse.urlencode(
        {
            "key": api_key,
            "q": query,
            "per_page": per_page,
            "safesearch": "true",
            "image_type": "photo",
        }
    )
    try:
        with urllib.request.urlopen(f"https://pixabay.com/api/?{params}", timeout=8) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Pixabay search failed: HTTP {exc.code}: {body}") from exc
    except Exception as exc:
        raise RuntimeError(f"Pixabay search failed: {type(exc).__name__}: {exc}") from exc
    results = []
    for item in data.get("hits", []):
        results.append(
            ImageResult(
                url=item.get("largeImageURL") or item.get("webformatURL") or "",
                source="pixabay",
                width=int(item.get("imageWidth", 0) or 0),
                height=int(item.get("imageHeight", 0) or 0),
                description=" ".join(str(value) for value in (item.get("tags", ""), item.get("pageURL", ""), item.get("user", "")) if value),
                page_url=str(item.get("pageURL") or ""),
                creator=str(item.get("user") or ""),
                license="Pixabay Content License",
            )
        )
    return [result for result in results if result.url]
