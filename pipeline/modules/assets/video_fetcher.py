from __future__ import annotations

import hashlib
import re
from pathlib import Path

from app.schemas import GenreConfig, ImageCue
from modules.assets.intent import (
    build_asset_intent,
    expand_query_for_intent,
    reject_for_intent,
    rewrite_query_for_intent,
    score_intent_alignment,
)
from modules.assets.video_services import download_video, score_video, search_pexels_videos


def fetch_video_for_cue(
    cue: ImageCue,
    video_dir: Path,
    genre: GenreConfig,
    pexels_key: str = "",
    asset_intent_profile: dict | None = None,
) -> tuple[str, str]:
    if not pexels_key:
        return "", ""
    video_dir.mkdir(parents=True, exist_ok=True)
    safe_name = hashlib.md5(cue.keyword.encode("utf-8")).hexdigest()[:12]
    target = video_dir / f"{safe_name}.mp4"
    if target.exists():
        return str(target), "cache"
    intent = build_asset_intent(cue, genre, asset_intent_profile)
    candidates = []
    search_errors = []
    for query in _query_variants(cue.keyword, genre, asset_intent_profile):
        try:
            for result in search_pexels_videos(query, pexels_key):
                if not reject_for_intent(result, intent):
                    candidates.append((query, result))
        except Exception as exc:
            search_errors.append(f"{query}: {exc}")
    scored = [
        (score_video(result, query) + score_intent_alignment(result, intent), result)
        for query, result in _dedupe_candidates(candidates)
    ]
    scored.sort(key=lambda item: item[0], reverse=True)
    for _, result in scored[:5]:
        try:
            return download_video(result.url, target), result.source
        except Exception as exc:
            search_errors.append(f"download: {exc}")
    return "", "; ".join(search_errors)


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
    return cleaned


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
