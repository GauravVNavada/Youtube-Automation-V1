from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import re
from pathlib import Path
from typing import Any

from app.schemas import GenreConfig, ImageCue
from modules.assets.candidates import AssetCandidate
from modules.assets.duckduckgo import search_duckduckgo_videos
from modules.assets.intent import (
    build_asset_intent,
    expand_query_for_intent,
    reject_for_intent,
    rewrite_query_for_intent,
    score_intent_alignment,
)
from modules.assets.subject_lock import scene_match_score, subject_match_score
from modules.assets.video_services import download_video, score_video, search_pexels_videos


VIDEO_QUERY_VARIANT_LIMIT = 4


def fetch_video_for_cue(
    cue: ImageCue,
    video_dir: Path,
    genre: GenreConfig,
    pexels_key: str = "",
    asset_intent_profile: dict | None = None,
    diagnostics: list[dict] | None = None,
) -> tuple[str, str]:
    video_dir.mkdir(parents=True, exist_ok=True)
    safe_name = hashlib.md5(cue.keyword.encode("utf-8")).hexdigest()[:12]
    target = video_dir / f"{safe_name}.mp4"
    if target.exists():
        _record(diagnostics, source="cache", stage="video", status="hit", path=str(target))
        return str(target), "cache"
    candidates = search_video_candidates(
        cue,
        genre,
        pexels_key=pexels_key,
        asset_intent_profile=asset_intent_profile,
        diagnostics=diagnostics,
    )
    if not candidates:
        _record(
            diagnostics,
            source="video_sources",
            stage="video_fallback",
            status="none_selected",
            reason="no accepted video candidates",
        )
        return "", ""
    download_errors = []
    for candidate in candidates[:8]:
        try:
            return download_video_candidate(candidate, cue, video_dir, diagnostics), candidate.source
        except Exception as exc:
            download_errors.append(f"{candidate.source}: {exc}")
            _record(
                diagnostics,
                source=candidate.source,
                stage="video_download",
                status="error",
                url=candidate.url,
                error=f"{type(exc).__name__}: {exc}",
            )
    _record(
        diagnostics,
        source="video_sources",
        stage="video_fallback",
        status="none_selected",
        reason="accepted video candidates failed download",
        download_errors=download_errors[:5],
    )
    return "", "; ".join(download_errors)


def search_video_candidates(
    cue: ImageCue,
    genre: GenreConfig,
    pexels_key: str = "",
    asset_intent_profile: dict | None = None,
    diagnostics: list[dict] | None = None,
) -> list[AssetCandidate]:
    intent = build_asset_intent(cue, genre, asset_intent_profile)
    variants = _query_variants(cue.keyword, genre, asset_intent_profile)
    candidates: list[tuple[str, Any]] = []
    futures = {}
    with ThreadPoolExecutor(max_workers=1 + max(1, len(variants))) as executor:
        futures[executor.submit(search_duckduckgo_videos, cue.keyword)] = ("duckduckgo", cue.keyword)
        if pexels_key:
            for query in variants:
                futures[executor.submit(search_pexels_videos, query, pexels_key)] = ("pexels", query)
        else:
            _record(
                diagnostics,
                source="pexels",
                stage="video_search",
                status="skipped_missing_key",
                env_keys=["PEXELS_API_KEY"],
            )
        for future in as_completed(futures):
            source, query = futures[future]
            try:
                results = future.result()
                _record(
                    diagnostics,
                    source=source,
                    stage="video_search",
                    status="ok",
                    query=query,
                    candidate_count=len(results),
                    candidates=[_candidate_summary(result) for result in results],
                )
                for result in results:
                    if not reject_for_intent(result, intent):
                        candidates.append((query, result))
            except Exception as exc:
                _record(
                    diagnostics,
                    source=source,
                    stage="video_search",
                    status="error",
                    query=query,
                    error=f"{type(exc).__name__}: {exc}",
                )
    scored = []
    rejected_subject = 0
    rejected_scene = 0
    rejected_samples = []
    for query, result in _dedupe_candidates(candidates):
        subject_score = subject_match_score(cue, result)
        scene_score = scene_match_score(query, result)
        if cue.subject_lock and subject_score < 0.8:
            rejected_subject += 1
            _append_rejected(rejected_samples, result, "subject_mismatch", subject_score, scene_score)
            continue
        if not cue.subject_lock and scene_score < 0.2:
            rejected_scene += 1
            _append_rejected(rejected_samples, result, "scene_mismatch", subject_score, scene_score)
            continue
        source_boost = 8.0 if result.source == "duckduckgo" else 4.0
        resolution_boost = 10.0 if result.height >= result.width and result.height >= 1080 else 4.0 if result.height >= result.width else 0.0
        score = (
            score_video(result, query) * 18.0
            + score_intent_alignment(result, intent) * 10.0
            + subject_score * 100.0
            + scene_score * 35.0
            + source_boost
            + resolution_boost
        )
        scored.append((score, result, subject_score, scene_score))
    scored.sort(key=lambda item: item[0], reverse=True)
    _record(
        diagnostics,
        source="video_sources",
        stage="video_filter",
        status="complete",
        candidate_count=len(candidates),
        accepted_count=len(scored),
        rejected_subject_count=rejected_subject,
        rejected_scene_count=rejected_scene,
        top_candidates=[
            {
                "score": round(score, 3),
                **_candidate_summary(result),
            }
            for score, result, _subject_score, _scene_score in scored[:10]
        ],
        rejected_samples=rejected_samples,
    )
    return [
        AssetCandidate(
            media_type="video",
            source=result.source,
            url=result.url,
            score=float(score),
            subject_match=subject_score,
            scene_match=scene_score,
            title=result.title,
            width=result.width,
            height=result.height,
            duration=result.duration,
            result=result,
        )
        for score, result, subject_score, scene_score in scored
    ]


def download_video_candidate(
    candidate: AssetCandidate,
    cue: ImageCue,
    video_dir: Path,
    diagnostics: list[dict] | None = None,
) -> str:
    video_dir.mkdir(parents=True, exist_ok=True)
    target = video_dir / f"{_candidate_file_stem(cue.keyword, candidate.url)}.mp4"
    if target.exists():
        _record(diagnostics, source="cache", stage="video", status="hit", path=str(target), url=candidate.url)
        return str(target)
    path = download_video(candidate.url, target)
    _record(
        diagnostics,
        source=candidate.source,
        stage="video_download",
        status="selected",
        url=candidate.url,
        title=candidate.title,
        score=round(candidate.score, 3),
        subject_match=round(candidate.subject_match, 3),
        scene_match=round(candidate.scene_match, 3),
        path=path,
    )
    return path


def _candidate_file_stem(keyword: str, url: str) -> str:
    return hashlib.md5(f"{keyword}:{url}".encode("utf-8")).hexdigest()[:12]


def _query_variants(keyword: str, genre: GenreConfig, asset_intent_profile: dict | None = None) -> list[str]:
    text = rewrite_query_for_intent(_remove_abstract_words(keyword), genre, asset_intent_profile)
    intent = build_asset_intent(ImageCue(text, "word_0"), genre, asset_intent_profile)
    words = _important_words(text)
    subject = " ".join(words[:3])
    genre_hint = genre.display_name.replace("Stories", "").replace("Facts", "").strip().lower()
    variants = expand_query_for_intent(text, intent) + [
        subject,
        f"{subject} vertical video",
        f"{subject} cinematic b roll",
        f"{genre_hint} {subject}".strip(),
        _generic_visual_query(words, genre),
    ]
    cleaned = []
    seen = set()
    for query in variants:
        normalized = re.sub(r"\s+", " ", query).strip()
        if normalized and normalized.lower() not in seen:
            cleaned.append(normalized)
            seen.add(normalized.lower())
    return cleaned[:VIDEO_QUERY_VARIANT_LIMIT]


def _remove_abstract_words(text: str) -> str:
    blocked = ("feeling", "feelings", "emotion", "overwhelmed", "pressure", "stress", "anxiety", "fear", "dramatic", "cinematic", "mysterious", "scary")
    cleaned = text.lower()
    for word in blocked:
        cleaned = re.sub(rf"\b{re.escape(word)}\b", " ", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def _important_words(text: str) -> list[str]:
    blocked = {"old", "thing", "image", "dark", "vertical", "stock", "photo", "video", "moment"}
    words = []
    for raw in text.split():
        word = re.sub(r"[^A-Za-z0-9]", "", raw).lower()
        if len(word) < 3 or word in blocked:
            continue
        words.append(word)
    return words or ["person", "room"]


def _generic_visual_query(words: list[str], genre: GenreConfig) -> str:
    joined = " ".join(words[:3])
    if genre.genre_id == "scary_stories":
        return f"dark hallway {joined}".strip()
    if genre.genre_id == "reddit_stories":
        return f"person conversation {joined}".strip()
    if genre.genre_id == "history_facts":
        return f"historic city street {joined}".strip()
    if genre.genre_id == "comics":
        return f"comic hero city {joined}".strip()
    return joined


def _dedupe_candidates(candidates):
    deduped = []
    seen = set()
    for query, result in candidates:
        key = result.url.split("?", 1)[0].strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append((query, result))
    return deduped


def _append_rejected(rejected_samples: list[dict], result, reason: str, subject_score: float, scene_score: float) -> None:
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


def _candidate_summary(result) -> dict:
    return {
        "source": result.source,
        "url": result.url,
        "title": result.title[:240],
        "width": result.width,
        "height": result.height,
        "duration": result.duration,
    }


def _record(diagnostics: list[dict] | None, **event) -> None:
    if diagnostics is not None:
        diagnostics.append(event)
