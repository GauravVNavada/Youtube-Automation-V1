from __future__ import annotations

import json
import random
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from agents.base import BaseAgent
from agents.prompts.asset_prompts import (
    MAX_OUTPUT_TOKENS as ASSET_QUERY_MAX_OUTPUT_TOKENS,
    SYSTEM_PROMPT as ASSET_QUERY_SYSTEM_PROMPT,
    messages_with_user as asset_query_messages_with_user,
    parse_asset_query_response,
)
from agents.prompts.message_base import render_messages_for_single_prompt
from app.paths import DATA_DIR
from app.schemas import AssetBundle, GenreConfig, ImageCue, SfxCue, TimedVisualCue
from modules.assets.candidates import AssetCandidate, asset_key
from modules.assets.fallback_image import create_fallback_image
from modules.assets.intent_generator import build_asset_intent_profile
from modules.assets.image_fetcher import download_image_candidate, search_image_candidates
from modules.assets.subject_lock import source_allowed_for_cue, subject_lock_repair_issue
from modules.assets.video_fetcher import download_video_candidate, search_video_candidates
from modules.visuals.timed_cues import timed_cue_to_image_cue


class AssetAgent(BaseAgent):
    name = "asset_agent"

    def run(
        self,
        image_cues: list[ImageCue],
        sfx_cues: list[SfxCue],
        genre: GenreConfig,
        pexels_key: str = "",
        pixabay_key: str = "",
        unsplash_key: str = "",
        provider=None,
        timed_visual_cues: list[TimedVisualCue] | None = None,
    ) -> AssetBundle:
        cue_pairs = _asset_cue_pairs(image_cues, timed_visual_cues or [])
        payload = {
            "image_cues": image_cues,
            "timed_visual_cue_count": len(timed_visual_cues or []),
            "asset_cue_count": len(cue_pairs),
            "sfx_cues": sfx_cues,
            "genre_id": genre.genre_id,
            "has_pexels_key": bool(pexels_key),
            "has_pixabay_key": bool(pixabay_key),
            "has_unsplash_key": bool(unsplash_key),
            "asset_query_provider": getattr(provider, "name", "none") if provider else "none",
            "asset_query_rewrite_max_input_chars": 500,
            "asset_query_rewrite_max_output_tokens": ASSET_QUERY_MAX_OUTPUT_TOKENS,
            "asset_source_order": [
                "duckduckgo_video",
                "duckduckgo_image",
                "pexels_video",
                "pexels_image",
                "pixabay_image",
                "unsplash_image",
                "wikimedia_image",
                "openverse_image",
                "generated_fallback",
            ],
            "subject_locked_cues": [
                {
                    "keyword": cue.keyword,
                    "required_subjects": cue.required_subjects,
                    "allowed_fallback_level": cue.allowed_fallback_level,
                }
                for cue in image_cues
                if cue.subject_lock
            ],
        }
        self.log_input(payload)
        image_dir = self.run_dir / "intermediate" / "images"
        video_dir = self.run_dir / "intermediate" / "videos"
        asset_cues = [cue for cue, _timed in cue_pairs]
        asset_intent_profile = build_asset_intent_profile(asset_cues, genre)
        image_paths: list[str] = []
        video_paths: list[str] = []
        media_paths: list[str] = []
        media_types: list[str] = []
        media_start_ms: list[int] = []
        media_end_ms: list[int] = []
        media_durations_ms: list[int] = []
        sources: list[str] = []
        subject_lock_issues: list[str] = []
        stock_video_search_terms: list[str] = []
        asset_selection_trace: list[dict] = []
        used_asset_keys: set[str] = set()
        used_asset_paths: set[str] = set()
        for cue, timed_cue in cue_pairs:
            if timed_cue is None:
                fetch_cue, rewrite = _rewrite_asset_query(cue, genre, provider)
            else:
                fetch_cue, rewrite = cue, {"reason": "timed visual cue already rewritten in batch"}
            if rewrite.get("error"):
                self.event("Asset query rewrite skipped", keyword=cue.keyword, error=str(rewrite["error"])[:240])
            elif rewrite.get("query") and rewrite["query"] != cue.keyword:
                self.event("Asset query rewritten", original=cue.keyword, query=rewrite["query"], reason=rewrite.get("reason", ""))
            stock_video_search_terms.append(fetch_cue.keyword)

            self.event(
                "Fetching timed media" if timed_cue else "Fetching media",
                keyword=fetch_cue.keyword,
                start_ms=timed_cue.start_ms if timed_cue else None,
                end_ms=timed_cue.end_ms if timed_cue else None,
                source_order=["duckduckgo_video", "duckduckgo_image", "pexels_video", "pexels", "pixabay", "unsplash", "wikimedia", "openverse"],
            )
            video_attempts: list[dict] = []
            image_attempts: list[dict] = []
            selected = _select_media_for_cue(
                fetch_cue=fetch_cue,
                image_dir=image_dir,
                video_dir=video_dir,
                genre=genre,
                pexels_key=pexels_key,
                pixabay_key=pixabay_key,
                unsplash_key=unsplash_key,
                asset_intent_profile=asset_intent_profile,
                video_attempts=video_attempts,
                image_attempts=image_attempts,
                used_asset_keys=used_asset_keys,
                used_asset_paths=used_asset_paths,
                timed_cue=timed_cue,
            )
            source_attempts = video_attempts + image_attempts
            if selected.media_type == "video":
                video_paths.append(selected.path)
                media_paths.append(selected.path)
                media_types.append("video")
                _append_timing(timed_cue, media_start_ms, media_end_ms, media_durations_ms)
                sources.append(f"{selected.source}_video")
                frame_path = _extract_video_frame(selected.path, _video_frame_path(image_dir, cue))
                poster_path = frame_path or selected.poster_path
                if poster_path:
                    image_paths.append(poster_path)
                asset_selection_trace.append(
                    _trace_entry(
                        fetch_cue,
                        source_attempts,
                        timed_cue=timed_cue,
                        selected_path=selected.path,
                        selected_source=f"{selected.source}_video",
                        selected_media_type="video",
                        poster_path=poster_path,
                        selected_url=selected.url,
                        selected_score=selected.score,
                    )
                )
                self.event(
                    "Video ready",
                    video_path=selected.path,
                    poster_path=poster_path,
                    source=selected.source,
                    url=selected.url,
                    score=selected.score,
                    start_ms=timed_cue.start_ms if timed_cue else None,
                    end_ms=timed_cue.end_ms if timed_cue else None,
                )
                self.event("Asset source attempts", keyword=fetch_cue.keyword, attempts=source_attempts)
                continue

            image_paths.append(selected.path)
            media_paths.append(selected.path)
            media_types.append("image")
            _append_timing(timed_cue, media_start_ms, media_end_ms, media_durations_ms)
            sources.append(selected.source)
            if not source_allowed_for_cue(fetch_cue, selected.source):
                subject_lock_issues.append(subject_lock_repair_issue(fetch_cue, selected.source))
            asset_selection_trace.append(
                _trace_entry(
                    fetch_cue,
                    source_attempts,
                    timed_cue=timed_cue,
                    selected_path=selected.path,
                    selected_source=selected.source,
                    selected_media_type="image",
                    selected_url=selected.url,
                    selected_score=selected.score,
                )
            )
            self.event(
                "Image ready",
                path=selected.path,
                source=selected.source,
                url=selected.url,
                score=selected.score,
                start_ms=timed_cue.start_ms if timed_cue else None,
                end_ms=timed_cue.end_ms if timed_cue else None,
            )
            self.event("Asset source attempts", keyword=fetch_cue.keyword, attempts=source_attempts)

        music_path = _pick_music_track()
        if music_path:
            self.event("Background music ready", path=music_path)
        asset_trace_path = _write_asset_trace(self.run_dir, asset_selection_trace)
        timed_visual_cues_path = _existing_timed_visual_cues_path(self.run_dir)
        bundle = AssetBundle(
            image_paths=image_paths,
            sfx_paths=[],
            music_path=music_path,
            sources=sources,
            video_paths=video_paths,
            media_paths=media_paths,
            media_types=media_types,
            stock_video_search_terms=stock_video_search_terms,
            subject_lock_issues=subject_lock_issues,
            asset_selection_trace=asset_selection_trace,
            asset_trace_path=asset_trace_path,
            media_start_ms=media_start_ms,
            media_end_ms=media_end_ms,
            media_durations_ms=media_durations_ms,
            timed_visual_cues=list(timed_visual_cues or []),
            timed_visual_cues_path=timed_visual_cues_path,
        )
        self.event(
            "Asset search terms ready",
            stock_video_search_terms=stock_video_search_terms,
            video_count=len(video_paths),
            image_count=len(image_paths),
            media_count=len(media_paths),
            timed_media_count=len(media_durations_ms),
            subject_lock_issues=subject_lock_issues,
            asset_trace_path=asset_trace_path,
            timed_visual_cues_path=timed_visual_cues_path,
        )
        self.log_output(bundle)
        return bundle


@dataclass
class SelectedMedia:
    path: str
    source: str
    media_type: str
    url: str = ""
    score: float = 0.0
    poster_path: str = ""


def _rewrite_asset_query(cue: ImageCue, genre: GenreConfig, provider) -> tuple[ImageCue, dict[str, str]]:
    if cue.subject_lock:
        return cue, {"reason": "subject lock keeps original entity query"}
    if not provider:
        return cue, {}
    try:
        messages = asset_query_messages_with_user(
            raw_query=cue.keyword,
            genre_id=genre.genre_id,
            mood=cue.mood,
            subject_lock=cue.subject_lock,
            required_subjects=cue.required_subjects,
            aliases=cue.aliases,
        )
        prompt = render_messages_for_single_prompt(messages[1:])
        data = provider.generate_json(
            ASSET_QUERY_SYSTEM_PROMPT,
            prompt,
            ASSET_QUERY_MAX_OUTPUT_TOKENS,
        )
        parsed = parse_asset_query_response(json.dumps(data, ensure_ascii=False) if isinstance(data, dict) else str(data))
        query = parsed["query"]
        if cue.subject_lock and cue.required_subjects and not _mentions_subject(query, cue):
            query = f"{cue.required_subjects[0]} {query}"
        if not query or query.strip().lower() == cue.keyword.strip().lower():
            return cue, parsed
        return ImageCue(
            keyword=query,
            timestamp_hint=cue.timestamp_hint,
            mood=cue.mood,
            role=cue.role,
            subject_lock=cue.subject_lock,
            required_subjects=list(cue.required_subjects),
            aliases=list(cue.aliases),
            allowed_fallback_level=cue.allowed_fallback_level,
        ), parsed
    except ValueError as exc:
        return cue, {"reason": f"asset query rewrite skipped; keeping original query ({type(exc).__name__})"}
    except Exception as exc:
        return cue, {"error": f"{type(exc).__name__}: {exc}"}


def _mentions_subject(text: str, cue: ImageCue) -> bool:
    lower = text.lower()
    return any(str(item).lower() in lower for item in [*cue.required_subjects, *cue.aliases] if str(item).strip())


def _asset_cue_pairs(
    fallback_image_cues: list[ImageCue],
    timed_visual_cues: list[TimedVisualCue],
) -> list[tuple[ImageCue, TimedVisualCue | None]]:
    if timed_visual_cues:
        return [(timed_cue_to_image_cue(cue), cue) for cue in timed_visual_cues]
    return [(cue, None) for cue in fallback_image_cues]


def _select_media_for_cue(
    *,
    fetch_cue: ImageCue,
    image_dir: Path,
    video_dir: Path,
    genre: GenreConfig,
    pexels_key: str,
    pixabay_key: str,
    unsplash_key: str,
    asset_intent_profile: dict,
    video_attempts: list[dict],
    image_attempts: list[dict],
    used_asset_keys: set[str],
    used_asset_paths: set[str],
    timed_cue: TimedVisualCue | None = None,
) -> SelectedMedia:
    with ThreadPoolExecutor(max_workers=2) as executor:
        video_future = executor.submit(
            search_video_candidates,
            fetch_cue,
            genre,
            pexels_key=pexels_key,
            asset_intent_profile=asset_intent_profile,
            diagnostics=video_attempts,
        )
        image_future = executor.submit(
            search_image_candidates,
            fetch_cue,
            genre,
            pexels_key=pexels_key,
            pixabay_key=pixabay_key,
            unsplash_key=unsplash_key,
            diagnostics=image_attempts,
        )
        try:
            video_candidates = video_future.result()
        except Exception as exc:
            video_attempts.append(
                {
                    "source": "video_sources",
                    "stage": "video_search",
                    "status": "error",
                    "query": fetch_cue.keyword,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
            video_candidates = []
        try:
            image_candidates = image_future.result()
        except Exception as exc:
            image_attempts.append(
                {
                    "source": "image_sources",
                    "stage": "image_search",
                    "status": "error",
                    "query": fetch_cue.keyword,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
            image_candidates = []

    combined = _rank_media_candidates(video_candidates, image_candidates, timed_cue)
    _record_candidate_pool(video_attempts, image_attempts, combined, used_asset_keys)
    download_errors: list[str] = []
    for candidate in combined:
        key = asset_key(candidate)
        if key and key in used_asset_keys:
            _record_duplicate(candidate, video_attempts if candidate.media_type == "video" else image_attempts)
            continue
        try:
            if candidate.media_type == "video":
                path = download_video_candidate(candidate, fetch_cue, video_dir, video_attempts)
                if path in used_asset_paths:
                    _record_duplicate_path(candidate, path, video_attempts)
                    continue
                if key:
                    used_asset_keys.add(key)
                used_asset_paths.add(path)
                return SelectedMedia(
                    path=path,
                    source=candidate.source,
                    media_type="video",
                    url=candidate.url,
                    score=candidate.score,
                )
            path = download_image_candidate(candidate, fetch_cue, image_dir, image_attempts)
            if path in used_asset_paths:
                _record_duplicate_path(candidate, path, image_attempts)
                continue
            if key:
                used_asset_keys.add(key)
            used_asset_paths.add(path)
            return SelectedMedia(
                path=path,
                source=candidate.source,
                media_type="image",
                url=candidate.url,
                score=candidate.score,
            )
        except Exception as exc:
            download_errors.append(f"{candidate.source}: {exc}")
            target_attempts = video_attempts if candidate.media_type == "video" else image_attempts
            target_attempts.append(
                {
                    "source": candidate.source,
                    "stage": f"{candidate.media_type}_download",
                    "status": "error",
                    "url": candidate.url,
                    "score": round(candidate.score, 3),
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )

    target = image_dir / f"{_safe_asset_name(fetch_cue.keyword)}_{len(used_asset_paths):03d}.jpg"
    path = create_fallback_image(fetch_cue.keyword, target)
    used_asset_paths.add(path)
    image_attempts.append(
        {
            "source": "generated_fallback",
            "stage": "image_fallback",
            "status": "used",
            "query": fetch_cue.keyword,
            "reason": "no unused downloadable asset candidate",
            "download_errors": download_errors[:5],
            "path": path,
        }
    )
    return SelectedMedia(path=path, source="generated_fallback", media_type="image", score=0.0)


def _rank_media_candidates(
    video_candidates: list[AssetCandidate],
    image_candidates: list[AssetCandidate],
    timed_cue: TimedVisualCue | None,
) -> list[AssetCandidate]:
    cue_duration = max(0.1, ((timed_cue.end_ms - timed_cue.start_ms) / 1000.0) if timed_cue else 3.0)
    ranked: list[AssetCandidate] = []
    for candidate in [*video_candidates, *image_candidates]:
        adjusted = AssetCandidate(**{**candidate.__dict__})
        adjusted.score = float(candidate.score) + _duration_fit_bonus(candidate, cue_duration)
        if candidate.media_type == "video":
            adjusted.score += 8.0
        ranked.append(adjusted)
    ranked.sort(key=lambda item: item.score, reverse=True)
    return ranked


def _duration_fit_bonus(candidate: AssetCandidate, cue_duration: float) -> float:
    if candidate.media_type != "video":
        return 0.0
    if candidate.duration <= 0:
        return -2.0
    if candidate.duration >= cue_duration:
        return 6.0
    ratio = candidate.duration / cue_duration
    if ratio >= 0.7:
        return 2.0
    if ratio >= 0.45:
        return -6.0
    return -18.0


def _record_candidate_pool(
    video_attempts: list[dict],
    image_attempts: list[dict],
    candidates: list[AssetCandidate],
    used_asset_keys: set[str],
) -> None:
    summary = [
        {
            "media_type": candidate.media_type,
            "source": candidate.source,
            "url": candidate.url,
            "score": round(candidate.score, 3),
            "already_used": bool(asset_key(candidate) and asset_key(candidate) in used_asset_keys),
        }
        for candidate in candidates[:20]
    ]
    event = {
        "source": "asset_pool",
        "stage": "asset_candidate_pool",
        "status": "ranked",
        "candidate_count": len(candidates),
        "top_candidates": summary,
    }
    video_attempts.append(event)
    image_attempts.append(dict(event))


def _record_duplicate(candidate: AssetCandidate, attempts: list[dict]) -> None:
    attempts.append(
        {
            "source": candidate.source,
            "stage": "asset_duplicate",
            "status": "rejected",
            "media_type": candidate.media_type,
            "reason": "same asset URL already selected in this run",
            "url": candidate.url,
            "score": round(candidate.score, 3),
        }
    )


def _record_duplicate_path(candidate: AssetCandidate, path: str, attempts: list[dict]) -> None:
    attempts.append(
        {
            "source": candidate.source,
            "stage": "asset_duplicate",
            "status": "rejected",
            "media_type": candidate.media_type,
            "reason": "same local asset path already selected in this run",
            "url": candidate.url,
            "path": path,
            "score": round(candidate.score, 3),
        }
    )


def _append_timing(
    timed_cue: TimedVisualCue | None,
    starts: list[int],
    ends: list[int],
    durations: list[int],
) -> None:
    if timed_cue is None:
        return
    start_ms = max(0, int(timed_cue.start_ms))
    end_ms = max(start_ms + 1, int(timed_cue.end_ms))
    starts.append(start_ms)
    ends.append(end_ms)
    durations.append(end_ms - start_ms)


def _trace_entry(
    cue: ImageCue,
    attempts: list[dict],
    *,
    timed_cue: TimedVisualCue | None = None,
    selected_path: str,
    selected_source: str,
    selected_media_type: str,
    poster_path: str = "",
    selected_url: str = "",
    selected_score: float = 0.0,
) -> dict:
    selected_start_ms = int(timed_cue.start_ms) if timed_cue else None
    selected_end_ms = int(timed_cue.end_ms) if timed_cue else None
    entry = {
        "keyword": cue.keyword,
        "timestamp_hint": cue.timestamp_hint,
        "mood": cue.mood,
        "subject_lock": cue.subject_lock,
        "required_subjects": list(cue.required_subjects),
        "aliases": list(cue.aliases),
        "timed_text_window": _timed_text_window(timed_cue),
        "provider_searches": _provider_search_summary(attempts),
        "candidate_count": _candidate_count(attempts),
        "rejected_samples": _rejected_samples(attempts),
        "selected_source": selected_source,
        "selected_media_type": selected_media_type,
        "selected_path": selected_path,
        "selected_url": selected_url,
        "selected_score": round(float(selected_score or 0.0), 3),
        "poster_path": poster_path,
        "selected_start_ms": selected_start_ms,
        "selected_end_ms": selected_end_ms,
        "selected_duration_ms": (selected_end_ms - selected_start_ms) if selected_start_ms is not None and selected_end_ms is not None else None,
        "attempts": attempts,
    }
    return entry


def _timed_text_window(timed_cue: TimedVisualCue | None) -> dict:
    if timed_cue is None:
        return {}
    return {
        "start_ms": timed_cue.start_ms,
        "end_ms": timed_cue.end_ms,
        "duration_ms": max(0, timed_cue.end_ms - timed_cue.start_ms),
        "text": timed_cue.text,
    }


def _provider_search_summary(attempts: list[dict]) -> list[dict]:
    summary = []
    for attempt in attempts:
        if str(attempt.get("stage") or "").endswith("_search"):
            summary.append(
                {
                    "source": attempt.get("source", ""),
                    "stage": attempt.get("stage", ""),
                    "status": attempt.get("status", ""),
                    "query": attempt.get("query", ""),
                    "candidate_count": attempt.get("candidate_count", 0),
                    "candidates": attempt.get("candidates", []),
                    "error": attempt.get("error", ""),
                }
            )
    return summary


def _candidate_count(attempts: list[dict]) -> int:
    total = 0
    for attempt in attempts:
        if "candidate_count" in attempt and str(attempt.get("stage") or "").endswith("_search"):
            try:
                total += int(attempt.get("candidate_count") or 0)
            except Exception:
                continue
    return total


def _rejected_samples(attempts: list[dict]) -> list[dict]:
    samples = []
    for attempt in attempts:
        if isinstance(attempt.get("rejected_samples"), list):
            samples.extend(attempt["rejected_samples"])
        if attempt.get("status") == "rejected":
            samples.append(
                {
                    "reason": attempt.get("reason", ""),
                    "source": attempt.get("source", ""),
                    "stage": attempt.get("stage", ""),
                    "url": attempt.get("url", ""),
                    "path": attempt.get("path", ""),
                    "media_type": attempt.get("media_type", ""),
                    "score": attempt.get("score", 0),
                }
            )
    return samples[:20]


def _write_asset_trace(run_dir: Path, trace: list[dict]) -> str:
    path = run_dir / "logs" / "asset_agent" / "asset_selection_trace.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(trace, indent=2, ensure_ascii=True), encoding="utf-8")
    return str(path)


def _safe_asset_name(text: str) -> str:
    import hashlib

    return hashlib.md5(text.encode("utf-8")).hexdigest()[:12]


def _existing_timed_visual_cues_path(run_dir: Path) -> str:
    path = run_dir / "logs" / "timed_visual_agent" / "timed_visual_cues.json"
    return str(path) if path.exists() else ""


def _selected_attempt_url(attempts: list[dict], stage: str) -> str:
    for attempt in attempts:
        if attempt.get("stage") == stage and attempt.get("status") == "selected":
            return str(attempt.get("url") or "")
    return ""


def _video_frame_path(image_dir: Path, cue: ImageCue) -> Path:
    import hashlib

    image_dir.mkdir(parents=True, exist_ok=True)
    safe_name = hashlib.md5(f"video:{cue.keyword}".encode("utf-8")).hexdigest()[:12]
    return image_dir / f"{safe_name}.jpg"


def _extract_video_frame(video_path: str, target: Path) -> str:
    if target.exists():
        return str(target)
    ffmpeg = shutil.which("ffmpeg")
    source = Path(video_path)
    if not ffmpeg or not source.exists():
        return ""
    target.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        [
            ffmpeg,
            "-y",
            "-ss",
            "00:00:01",
            "-i",
            str(source),
            "-frames:v",
            "1",
            "-q:v",
            "2",
            str(target),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if proc.returncode != 0 or not target.exists() or target.stat().st_size <= 0:
        return ""
    return str(target)


def _pick_music_track() -> str | None:
    music_dir = DATA_DIR / "assets" / "music"
    if not music_dir.exists():
        return None
    tracks: list[Path] = []
    for pattern in ("*.mp3", "*.MP3", "*.wav", "*.WAV", "*.m4a", "*.M4A"):
        tracks.extend(music_dir.glob(pattern))
    if not tracks:
        return None
    return str(random.choice(sorted(tracks)))
