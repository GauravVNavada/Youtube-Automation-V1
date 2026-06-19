from __future__ import annotations

import json
import urllib.parse
import urllib.request

from modules.assets.image_scoring import ImageResult


def search_openverse_images(query: str, max_results: int = 8) -> list[ImageResult]:
    params = urllib.parse.urlencode(
        {
            "q": query,
            "page_size": max_results,
            "mature": "false",
        }
    )
    request = urllib.request.Request(
        f"https://api.openverse.engineering/v1/images/?{params}",
        headers={"User-Agent": "ModularShorts/0.1"},
    )
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            data = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        raise RuntimeError(f"Openverse search failed: {type(exc).__name__}: {exc}") from exc
    results: list[ImageResult] = []
    for item in data.get("results", []) or []:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or item.get("thumbnail") or "")
        if not url:
            continue
        license_name = " ".join(str(part) for part in (item.get("license"), item.get("license_version")) if part)
        page_url = str(item.get("foreign_landing_url") or item.get("creator_url") or "")
        results.append(
            ImageResult(
                url=url,
                source="openverse",
                width=int(item.get("width", 0) or 0),
                height=int(item.get("height", 0) or 0),
                description=" ".join(
                    str(value)
                    for value in (
                        item.get("title", ""),
                        page_url,
                        item.get("creator", ""),
                        license_name,
                        item.get("source", ""),
                    )
                    if value
                ),
                page_url=page_url,
                creator=str(item.get("creator") or ""),
                license=license_name or "Openverse",
            )
        )
    return results
