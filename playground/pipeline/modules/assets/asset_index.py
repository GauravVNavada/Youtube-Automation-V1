from __future__ import annotations

import hashlib
import json
import shutil
import threading
from pathlib import Path
from typing import Any

from app.paths import DATA_DIR


INDEX_PATH = DATA_DIR / "assets" / "asset_index.json"
CACHE_DIR = DATA_DIR / "assets" / "cache" / "images"
_INDEX_LOCK = threading.Lock()


def restore_cached_image(query: str, target_path: Path) -> tuple[str, str] | None:
    """Copy a reusable cached image into the current run if available."""
    with _INDEX_LOCK:
        index = _read_index()
    key = _query_key(query)
    for entry in index.get("images", {}).get(key, []):
        cache_path = Path(str(entry.get("cache_path") or ""))
        if not cache_path.exists():
            continue
        target_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(cache_path, target_path)
        source = str(entry.get("source") or "asset_cache")
        return str(target_path), f"asset_cache:{source}"
    return None


def record_image_asset(query: str, source: str, original_url: str, run_path: str | Path) -> None:
    """Persist metadata and a reusable copy for future playground runs."""
    run_path = Path(run_path)
    if not run_path.exists() or run_path.stat().st_size < 1024:
        return
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    ext = _extension(run_path)
    cache_name = f"{_query_key(query)}_{_url_key(original_url)}{ext}"
    cache_path = CACHE_DIR / cache_name
    if not cache_path.exists():
        shutil.copyfile(run_path, cache_path)

    with _INDEX_LOCK:
        index = _read_index()
        images: dict[str, list[dict[str, Any]]] = index.setdefault("images", {})
        key = _query_key(query)
        entries = images.setdefault(key, [])
        new_entry = {
            "query": query,
            "source": source,
            "original_url": original_url,
            "cache_path": str(cache_path),
        }
        if not any(entry.get("cache_path") == str(cache_path) for entry in entries):
            entries.insert(0, new_entry)
            del entries[8:]
            _write_index(index)


def _read_index() -> dict[str, Any]:
    if not INDEX_PATH.exists():
        return {"images": {}}
    try:
        data = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"images": {}}
    return data if isinstance(data, dict) else {"images": {}}


def _write_index(index: dict[str, Any]) -> None:
    INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = INDEX_PATH.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(index, indent=2, ensure_ascii=True), encoding="utf-8")
    tmp_path.replace(INDEX_PATH)


def _query_key(query: str) -> str:
    normalized = " ".join(str(query or "").lower().split())
    return hashlib.md5(normalized.encode("utf-8")).hexdigest()[:16]


def _url_key(url: str) -> str:
    return hashlib.md5(str(url or "").encode("utf-8")).hexdigest()[:10]


def _extension(path: Path) -> str:
    suffix = path.suffix.lower()
    return suffix if suffix in {".jpg", ".jpeg", ".png", ".webp"} else ".jpg"
