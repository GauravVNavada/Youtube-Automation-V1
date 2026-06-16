from __future__ import annotations

import hashlib
from pathlib import Path

from app.schemas import GenreConfig, ImageCue
from modules.assets.image_scoring import score_image
from modules.assets.image_services import (
    download_image,
    search_pexels,
    search_pixabay,
    search_wikimedia,
)


def fetch_image_for_cue(
    cue: ImageCue,
    image_dir: Path,
    genre: GenreConfig,
    pexels_key: str = "",
    pixabay_key: str = "",
) -> tuple[str, str]:
    """Resolve one cue into an image path from online sources."""
    image_dir.mkdir(parents=True, exist_ok=True)
    safe_name = hashlib.md5(cue.keyword.encode("utf-8")).hexdigest()[:12]
    target = image_dir / f"{safe_name}.jpg"
    if target.exists():
        return str(target), "cache"

    candidates = []
    search_errors: list[str] = []
    for source_name, search_fn, args in (
        ("pexels", search_pexels, (cue.keyword, pexels_key)),
        ("pixabay", search_pixabay, (cue.keyword, pixabay_key)),
        ("wikimedia", search_wikimedia, (cue.keyword,)),
    ):
        try:
            candidates.extend(search_fn(*args))
        except Exception as exc:
            search_errors.append(f"{source_name}: {exc}")

    scored = [
        (score_image(result, cue.keyword), result)
        for result in candidates
        if result.url
    ]
    scored = [(score, result) for score, result in scored if score > 0]
    scored.sort(key=lambda item: item[0], reverse=True)
    if not scored:
        details = f" Search errors: {'; '.join(search_errors)}" if search_errors else ""
        raise RuntimeError(f"No online image candidates found for cue: {cue.keyword}.{details}")

    download_errors: list[str] = []
    for _, result in scored[:3]:
        try:
            return download_image(result.url, target), result.source
        except Exception as exc:
            download_errors.append(f"{result.source}: {exc}")
            continue

    details_parts = download_errors + [f"search {error}" for error in search_errors]
    details = "; ".join(details_parts) if details_parts else "no download attempts"
    raise RuntimeError(f"Could not download an online image for cue '{cue.keyword}': {details}")
