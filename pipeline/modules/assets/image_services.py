from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from modules.assets.image_scoring import ImageResult


def search_pexels(query: str, api_key: str, per_page: int = 5) -> list[ImageResult]:
    if not api_key:
        return []
    params = urllib.parse.urlencode({"query": query, "per_page": per_page, "orientation": "portrait"})
    request = urllib.request.Request(
        f"https://api.pexels.com/v1/search?{params}",
        headers={"Authorization": api_key},
    )
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
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
                description=item.get("alt", ""),
            )
        )
    return [r for r in results if r.url]


def search_pixabay(query: str, api_key: str, per_page: int = 5) -> list[ImageResult]:
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
                description=item.get("tags", ""),
            )
        )
    return [r for r in results if r.url]


def search_bing(
    query: str,
    api_key: str,
    endpoint: str = "https://api.bing.microsoft.com/v7.0/images/search",
    per_page: int = 5,
) -> list[ImageResult]:
    if not api_key:
        return []
    endpoint = (endpoint or "https://api.bing.microsoft.com/v7.0/images/search").rstrip("/")
    params = urllib.parse.urlencode({"q": query, "count": per_page, "safeSearch": "Moderate"})
    request = urllib.request.Request(
        f"{endpoint}?{params}",
        headers={"Ocp-Apim-Subscription-Key": api_key, "User-Agent": "DesktopApp/0.1"},
    )
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Bing image search failed: HTTP {exc.code}: {body}") from exc
    except Exception as exc:
        raise RuntimeError(f"Bing image search failed: {type(exc).__name__}: {exc}") from exc
    results = []
    for item in data.get("value", []):
        thumbnail = item.get("thumbnail") if isinstance(item.get("thumbnail"), dict) else {}
        results.append(
            ImageResult(
                url=item.get("contentUrl") or item.get("thumbnailUrl") or "",
                source="bing",
                width=int(item.get("width") or thumbnail.get("width") or 0),
                height=int(item.get("height") or thumbnail.get("height") or 0),
                description=item.get("name", ""),
            )
        )
    return [r for r in results if r.url]


def search_wikimedia(query: str, max_results: int = 5) -> list[ImageResult]:
    params = urllib.parse.urlencode(
        {
            "action": "query",
            "format": "json",
            "generator": "search",
            "gsrsearch": f"File:{query}",
            "gsrlimit": str(max_results),
            "prop": "imageinfo",
            "iiprop": "url|size",
            "iiurlwidth": "1080",
        }
    )
    try:
        with urllib.request.urlopen(f"https://commons.wikimedia.org/w/api.php?{params}", timeout=8) as response:
            data = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        raise RuntimeError(f"Wikimedia search failed: {type(exc).__name__}: {exc}") from exc
    results: list[ImageResult] = []
    pages = data.get("query", {}).get("pages", {})
    if not isinstance(pages, dict):
        return results
    for page in pages.values():
        info_list = page.get("imageinfo", [])
        if not info_list:
            continue
        info = info_list[0]
        url = info.get("thumburl") or info.get("url") or ""
        if url:
            results.append(
                ImageResult(
                    url=url,
                    source="wikimedia",
                    width=int(info.get("thumbwidth", info.get("width", 0)) or 0),
                    height=int(info.get("thumbheight", info.get("height", 0)) or 0),
                    description=page.get("title", ""),
                )
            )
    return results


def download_image(url: str, output_path: Path) -> str:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": "ModularShorts/0.1"})
    with urllib.request.urlopen(request, timeout=12) as response:
        content_type = response.headers.get("Content-Type", "")
        data = response.read()
    if not data or ("image" not in content_type and len(data) < 1024):
        raise RuntimeError(f"Downloaded response is not a usable image: {content_type}")
    output_path.write_bytes(data)
    return str(output_path)
