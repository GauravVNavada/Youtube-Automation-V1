from __future__ import annotations

import json
import urllib.parse
import urllib.request

from modules.assets.image_scoring import ImageResult


def search_wikimedia_images(query: str, max_results: int = 8) -> list[ImageResult]:
    params = urllib.parse.urlencode(
        {
            "action": "query",
            "format": "json",
            "generator": "search",
            "gsrsearch": f"File:{query}",
            "gsrlimit": str(max_results),
            "prop": "imageinfo",
            "iiprop": "url|size|extmetadata",
            "iiurlwidth": "1080",
        }
    )
    request = urllib.request.Request(
        f"https://commons.wikimedia.org/w/api.php?{params}",
        headers={"User-Agent": "ModularShorts/0.1"},
    )
    try:
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
        metadata = info.get("extmetadata", {}) if isinstance(info.get("extmetadata"), dict) else {}
        license_short = _meta_value(metadata, "LicenseShortName")
        artist = _meta_value(metadata, "Artist")
        page_url = _meta_value(metadata, "ObjectURL") or info.get("descriptionurl") or ""
        url = info.get("thumburl") or info.get("url") or ""
        if url:
            results.append(
                ImageResult(
                    url=url,
                    source="wikimedia",
                    width=int(info.get("thumbwidth", info.get("width", 0)) or 0),
                    height=int(info.get("thumbheight", info.get("height", 0)) or 0),
                    description=" ".join(str(value) for value in (page.get("title", ""), page_url, artist, license_short) if value),
                    page_url=str(page_url or ""),
                    creator=str(artist or ""),
                    license=str(license_short or "Wikimedia Commons"),
                )
            )
    return results


def _meta_value(metadata: dict, key: str) -> str:
    value = metadata.get(key, {})
    if isinstance(value, dict):
        return str(value.get("value") or "")
    return str(value or "")
