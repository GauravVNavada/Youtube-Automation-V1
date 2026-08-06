from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
from pathlib import Path
from typing import Any, Callable

from PIL import Image, ImageEnhance, UnidentifiedImageError

from app.schemas import GenreConfig, ImageCue
from modules.assets.candidates import AssetCandidate
from modules.assets.duckduckgo import search_duckduckgo_images
from modules.assets.fallback_image import create_fallback_image
from modules.assets.image_scoring import ImageResult, score_image
from modules.assets.image_services import download_image
from modules.assets.intent import build_asset_intent, reject_for_intent, rewrite_query_for_intent, score_intent_alignment
from modules.assets.openverse import search_openverse_images
from modules.assets.pexels import search_pexels_images
from modules.assets.pixabay import search_pixabay_images
from modules.assets.subject_lock import scene_match_score, source_allowed_for_cue, subject_match_score
from modules.assets.unsplash import search_unsplash_images
from modules.assets.wikimedia import search_wikimedia_images


ProviderCall = tuple[str, Callable[[], list[ImageResult]], bool, list[str]]


def fetch_image_for_cue(
    cue: ImageCue,
    image_dir: Path,
    genre: GenreConfig,
    pexels_key: str = "",
    pixabay_key: str = "",
    unsplash_key: str = "",
    diagnostics: list[dict] | None = None,
) -> tuple[str, str]:
    """Resolve one cue into an image path from free/source-aware providers."""
    image_dir.mkdir(parents=True, exist_ok=True)
    safe_name = hashlib.md5(cue.keyword.encode("utf-8")).hexdigest()[:12]
    target = image_dir / f"{safe_name}.jpg"
    if target.exists() and not cue.subject_lock:
        _record(diagnostics, source="cache", stage="image", status="hit", path=str(target))
        return str(target), "cache"

    if target.exists() and cue.subject_lock:
        _record(diagnostics, source="cache", stage="image", status="ignored_subject_lock", path=str(target))

    candidates = search_image_candidates(
        cue,
        genre,
        pexels_key=pexels_key,
        pixabay_key=pixabay_key,
        unsplash_key=unsplash_key,
        diagnostics=diagnostics,
    )
    if not candidates:
        _record(
            diagnostics,
            source="generated_fallback",
            stage="image_fallback",
            status="used",
            reason="no accepted free image candidates",
            path=str(target),
        )
        return create_fallback_image(cue.keyword, target), "generated_fallback"

    download_errors: list[str] = []
    for candidate in candidates[:8]:
        try:
            return download_image_candidate(candidate, cue, image_dir, diagnostics, genre=genre), candidate.source
        except Exception as exc:
            download_errors.append(f"{candidate.source}: {exc}")
            _record(
                diagnostics,
                source=candidate.source,
                stage="image_download",
                status="error",
                candidate=_asset_candidate_summary(candidate),
                error=f"{type(exc).__name__}: {exc}",
            )
            continue

    _record(
        diagnostics,
        source="generated_fallback",
        stage="image_fallback",
        status="used",
        reason="accepted free image candidates failed download",
        download_errors=download_errors[:5],
        path=str(target),
    )
    return create_fallback_image(cue.keyword, target), "generated_fallback"


def search_image_candidates(
    cue: ImageCue,
    genre: GenreConfig,
    pexels_key: str = "",
    pixabay_key: str = "",
    unsplash_key: str = "",
    diagnostics: list[dict] | None = None,
) -> list[AssetCandidate]:
    search_cue = _search_cue_for_genre(cue, genre)
    provider_calls: list[ProviderCall] = [
        ("duckduckgo", lambda: search_duckduckgo_images(search_cue.keyword), True, []),
        ("pexels", lambda: search_pexels_images(search_cue.keyword, pexels_key), bool(pexels_key), ["PEXELS_API_KEY"]),
        ("pixabay", lambda: search_pixabay_images(search_cue.keyword, pixabay_key), bool(pixabay_key), ["PIXABAY_API_KEY"]),
        ("unsplash", lambda: search_unsplash_images(search_cue.keyword, unsplash_key), bool(unsplash_key), ["UNSPLASH_ACCESS_KEY"]),
        ("wikimedia", lambda: search_wikimedia_images(search_cue.keyword), True, []),
        ("openverse", lambda: search_openverse_images(search_cue.keyword), True, []),
    ]
    candidates = _search_providers_parallel(search_cue, provider_calls, diagnostics)
    scored, filter_summary = _score_candidates(search_cue, candidates, genre)
    _record(
        diagnostics,
        source="free_image_sources",
        stage="image_filter",
        status="complete",
        candidate_count=len(candidates),
        accepted_count=len(scored),
        **filter_summary,
    )
    return [
        AssetCandidate(
            media_type="image",
            source=result.source,
            url=result.url,
            score=float(score),
            subject_match=subject_score,
            scene_match=scene_score,
            description=result.description,
            page_url=result.page_url,
            width=result.width,
            height=result.height,
            result=result,
        )
        for score, result, subject_score, scene_score in scored
    ]


def download_image_candidate(
    candidate: AssetCandidate,
    cue: ImageCue,
    image_dir: Path,
    diagnostics: list[dict] | None = None,
    genre: GenreConfig | None = None,
) -> str:
    image_dir.mkdir(parents=True, exist_ok=True)
    target = image_dir / f"{_candidate_file_stem(cue.keyword, candidate.url)}.jpg"
    if target.exists() and not cue.subject_lock:
        _normalize_downloaded_image(target, genre)
        _record(diagnostics, source="cache", stage="image", status="hit", path=str(target), url=candidate.url)
        return str(target)
    path = download_image(candidate.url, target)
    _normalize_downloaded_image(Path(path), genre)
    _record(
        diagnostics,
        source=candidate.source,
        stage="image_download",
        status="selected",
        score=round(candidate.score, 3),
        subject_match=round(candidate.subject_match, 3),
        scene_match=round(candidate.scene_match, 3),
        candidate=_asset_candidate_summary(candidate),
        path=path,
    )
    return path


def _normalize_downloaded_image(path: Path, genre: GenreConfig | None = None) -> None:
    try:
        with Image.open(path) as image:
            image.load()
            rgb_image = image.convert("RGB")
            rgb_image = _apply_genre_grade(rgb_image, genre)
            rgb_image.save(path, format="JPEG", quality=92, optimize=True)
    except (OSError, UnidentifiedImageError) as exc:
        raise RuntimeError(f"Downloaded image is not a valid renderable image: {path}") from exc


def _apply_genre_grade(image: Image.Image, genre: GenreConfig | None) -> Image.Image:
    if genre is None:
        return image
    genre_id = str(getattr(genre, "genre_id", "") or "").lower()
    tone = str(getattr(genre, "tone", "") or "").lower()
    mood = str(getattr(genre, "music_mood", "") or "").lower()
    dark_genre = genre_id in {"scary_stories", "true_crime"} or "dark" in tone or "dark" in mood or "tense" in tone
    if not dark_genre:
        return image
    graded = ImageEnhance.Color(image).enhance(0.72)
    graded = ImageEnhance.Brightness(graded).enhance(0.78)
    graded = ImageEnhance.Contrast(graded).enhance(1.18)
    return graded


def _asset_candidate_summary(candidate: AssetCandidate) -> dict[str, Any]:
    return {
        "source": candidate.source,
        "url": candidate.url,
        "page_url": candidate.page_url,
        "width": candidate.width,
        "height": candidate.height,
        "description": candidate.description[:240],
        "score": round(candidate.score, 3),
        "subject_match": round(candidate.subject_match, 3),
        "scene_match": round(candidate.scene_match, 3),
    }


def _candidate_file_stem(keyword: str, url: str) -> str:
    return hashlib.md5(f"{keyword}:{url}".encode("utf-8")).hexdigest()[:12]


def _search_providers_parallel(
    cue: ImageCue,
    provider_calls: list[ProviderCall],
    diagnostics: list[dict] | None,
) -> list[ImageResult]:
    candidates: list[ImageResult] = []
    futures = {}
    with ThreadPoolExecutor(max_workers=len(provider_calls)) as executor:
        for source_name, fn, has_credentials, env_keys in provider_calls:
            if not has_credentials:
                _record(
                    diagnostics,
                    source=source_name,
                    stage="image_search",
                    status="skipped_missing_key",
                    query=cue.keyword,
                    env_keys=env_keys,
                    candidates=[],
                )
                continue
            futures[executor.submit(fn)] = source_name
        for future in as_completed(futures):
            source_name = futures[future]
            try:
                results = future.result()
                candidates.extend(results)
                _record(
                    diagnostics,
                    source=source_name,
                    stage="image_search",
                    status="ok",
                    query=cue.keyword,
                    candidate_count=len(results),
                    candidates=[_candidate_summary(result) for result in results],
                )
            except Exception as exc:
                _record(
                    diagnostics,
                    source=source_name,
                    stage="image_search",
                    status="error",
                    query=cue.keyword,
                    error=f"{type(exc).__name__}: {exc}",
                    candidates=[],
                )
    return candidates


def _score_candidates(cue: ImageCue, candidates: list[ImageResult], genre: GenreConfig) -> tuple[list[tuple[int, ImageResult, float, float]], dict[str, Any]]:
    scored: list[tuple[int, ImageResult, float, float]] = []
    intent = build_asset_intent(cue, genre)
    rejected_subject = 0
    rejected_scene = 0
    rejected_source = 0
    rejected_intent = 0
    rejected_empty = 0
    rejected_score = 0
    rejected_samples: list[dict[str, Any]] = []
    for result in candidates:
        if not result.url:
            rejected_empty += 1
            continue
        if not source_allowed_for_cue(cue, result.source):
            rejected_source += 1
            _append_rejected(rejected_samples, result, "source_not_allowed")
            continue
        if reject_for_intent(result, intent):
            rejected_intent += 1
            _append_rejected(rejected_samples, result, "genre_mood_mismatch")
            continue
        subject_score = subject_match_score(cue, result)
        scene_score = scene_match_score(cue.keyword, result)
        if cue.subject_lock and subject_score < 0.8:
            rejected_subject += 1
            _append_rejected(rejected_samples, result, "subject_mismatch", subject_score, scene_score)
            continue
        if not cue.subject_lock and scene_score < 0.2:
            rejected_scene += 1
            _append_rejected(rejected_samples, result, "scene_mismatch", subject_score, scene_score)
            continue
        intent_score = score_intent_alignment(result, intent)
        score = (
            score_image(result, cue.keyword, strict=not cue.subject_lock)
            + int(subject_score * 100)
            + int(scene_score * 35)
            + int(intent_score * 18)
        )
        if score <= 0:
            rejected_score += 1
            _append_rejected(rejected_samples, result, "low_score", subject_score, scene_score)
            continue
        scored.append((score, result, subject_score, scene_score))
    scored.sort(key=lambda item: item[0], reverse=True)
    return scored, {
        "rejected_subject_count": rejected_subject,
        "rejected_scene_count": rejected_scene,
        "rejected_source_count": rejected_source,
        "rejected_intent_count": rejected_intent,
        "rejected_empty_count": rejected_empty,
        "rejected_score_count": rejected_score,
        "top_candidates": [
            {
                "score": score,
                "subject_match": round(subject_score, 3),
                "scene_match": round(scene_score, 3),
                **_candidate_summary(result),
            }
            for score, result, subject_score, scene_score in scored[:10]
        ],
        "rejected_samples": rejected_samples,
    }


def _search_cue_for_genre(cue: ImageCue, genre: GenreConfig) -> ImageCue:
    intent_query = rewrite_query_for_intent(cue.keyword, genre)
    if cue.subject_lock:
        modifiers = " ".join(str(item) for item in build_asset_intent(cue, genre).get("query_modifiers", [])[:2])
        keyword = f"{cue.keyword} {modifiers}".strip()
    else:
        keyword = intent_query or cue.keyword
    keyword = " ".join(keyword.split())
    if not keyword or keyword == cue.keyword:
        return cue
    return ImageCue(
        keyword=keyword,
        timestamp_hint=cue.timestamp_hint,
        mood=cue.mood,
        role=cue.role,
        subject_lock=cue.subject_lock,
        required_subjects=list(cue.required_subjects),
        aliases=list(cue.aliases),
        allowed_fallback_level=cue.allowed_fallback_level,
    )


def _append_rejected(
    rejected_samples: list[dict[str, Any]],
    result: ImageResult,
    reason: str,
    subject_score: float = 0.0,
    scene_score: float = 0.0,
) -> None:
    if len(rejected_samples) >= 10:
        return
    rejected_samples.append(
        {
            "reason": reason,
            "subject_match": round(subject_score, 3),
            "scene_match": round(scene_score, 3),
            **_candidate_summary(result),
        }
    )


def _candidate_summary(result: ImageResult) -> dict[str, Any]:
    return {
        "source": result.source,
        "url": result.url,
        "page_url": result.page_url,
        "width": result.width,
        "height": result.height,
        "description": result.description[:240],
        "creator": result.creator,
        "license": result.license,
    }


def _record(diagnostics: list[dict] | None, **event) -> None:
    if diagnostics is not None:
        diagnostics.append(event)
