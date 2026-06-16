from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from modules.assets.image_scoring import ImageResult


USER_AGENT = "DesktopAppVideoPipeline/0.1 (online image search; contact: local-app)"


def search_pexels(query: str, api_key: str, per_page: int = 5) -> list[ImageResult]:
    if not api_key:
        return []
    params = urllib.parse.urlencode({"query": query, "per_page": per_page, "orientation": "portrait"})
    request = urllib.request.Request(
        f"https://api.pexels.com/v1/search?{params}",
        headers={"Authorization": api_key, "User-Agent": USER_AGENT},
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


def search_pixabay(query: str, api_key: str, per_page: int = 5, image_type: str = "photo") -> list[ImageResult]:
    if not api_key:
        return []
    params = urllib.parse.urlencode(
        {
            "key": api_key,
            "q": query,
            "per_page": per_page,
            "safesearch": "true",
            "image_type": image_type,
        }
    )
    try:
        request = urllib.request.Request(f"https://pixabay.com/api/?{params}", headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(request, timeout=8) as response:
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
        request = urllib.request.Request(
            f"https://commons.wikimedia.org/w/api.php?{params}",
            headers={"User-Agent": USER_AGENT},
        )
        with urllib.request.urlopen(request, timeout=8) as response:
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


def search_openverse(query: str, max_results: int = 8) -> list[ImageResult]:
    params = urllib.parse.urlencode(
        {
            "q": query,
            "page_size": max_results,
            "mature": "false",
            "extension": "jpg,png,jpeg",
        }
    )
    try:
        request = urllib.request.Request(
            f"https://api.openverse.org/v1/images/?{params}",
            headers={"User-Agent": USER_AGENT},
        )
        with urllib.request.urlopen(request, timeout=8) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Openverse search failed: HTTP {exc.code}: {body}") from exc
    except Exception as exc:
        raise RuntimeError(f"Openverse search failed: {type(exc).__name__}: {exc}") from exc

    results = []
    for item in data.get("results", []):
        width = int(item.get("width", 0) or 0)
        height = int(item.get("height", 0) or 0)
        results.append(
            ImageResult(
                url=item.get("url") or item.get("thumbnail") or "",
                source="openverse",
                width=width,
                height=height,
                description=item.get("title", "") or item.get("creator", "") or "",
            )
        )
    return [result for result in results if result.url]


def search_bing_images(query: str, max_results: int = 8) -> list[ImageResult]:
    """Free no-key Bing image fallback, inspired by ShortGPT's scraper."""
    params = urllib.parse.urlencode({"q": query, "first": "1", "safeSearch": "strict"})
    request = urllib.request.Request(
        f"https://www.bing.com/images/search?{params}",
        headers={"User-Agent": USER_AGENT},
    )
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            html = response.read().decode("utf-8", errors="replace")
    except Exception as exc:
        raise RuntimeError(f"Bing image search failed: {type(exc).__name__}: {exc}") from exc

    results: list[ImageResult] = []
    seen: set[str] = set()
    for url, width, height in _extract_bing_mediaurl_results(html):
        key = url.split("?")[0].lower()
        if key in seen:
            continue
        seen.add(key)
        results.append(
            ImageResult(
                url=url,
                source="bing",
                width=width,
                height=height,
                description=query,
            )
        )
        if len(results) >= max_results:
            break
    for url in _extract_bing_murl_results(html):
        key = url.split("?")[0].lower()
        if key in seen:
            continue
        seen.add(key)
        results.append(ImageResult(url=url, source="bing", description=query))
        if len(results) >= max_results:
            break
    return results


def download_image(url: str, output_path: Path) -> str:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=12) as response:
        content_type = response.headers.get("Content-Type", "")
        data = response.read()
    if not data or ("image" not in content_type and len(data) < 1024):
        raise RuntimeError(f"Downloaded response is not a usable image: {content_type}")
    output_path.write_bytes(data)
    return str(output_path)


def _extract_bing_mediaurl_results(html: str) -> list[tuple[str, int, int]]:
    pattern = r"mediaurl=(.*?)&amp;.*?expw=(\d+).*?exph=(\d+)"
    results: list[tuple[str, int, int]] = []
    for raw_url, width, height in re.findall(pattern, html):
        url = urllib.parse.unquote(raw_url)
        if _looks_like_image_url(url):
            results.append((url, int(width), int(height)))
    return results


def _extract_bing_murl_results(html: str) -> list[str]:
    results: list[str] = []
    patterns = (
        r"&quot;murl&quot;:&quot;(.*?)&quot;",
        r'"murl":"(.*?)"',
    )
    for pattern in patterns:
        for raw_url in re.findall(pattern, html):
            url = urllib.parse.unquote(raw_url.replace("\\/", "/"))
            if _looks_like_image_url(url):
                results.append(url)
    return results


def _looks_like_image_url(url: str) -> bool:
    lowered = url.lower().split("?")[0]
    return lowered.startswith(("http://", "https://")) and lowered.endswith((".jpg", ".jpeg", ".png", ".webp"))
