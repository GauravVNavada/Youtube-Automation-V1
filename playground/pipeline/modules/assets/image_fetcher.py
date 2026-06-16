from __future__ import annotations

import hashlib
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from app.schemas import GenreConfig, ImageCue
from modules.assets.asset_index import record_image_asset, restore_cached_image
from modules.assets.intent import (
    build_asset_intent,
    expand_query_for_intent,
    reject_for_intent,
    rewrite_query_for_intent,
    score_intent_alignment,
    specific_rewrite_for_intent,
)
from modules.assets.image_scoring import score_image
from modules.assets.image_services import (
    download_image,
    search_bing_images,
    search_openverse,
    search_pexels,
    search_pixabay,
    search_wikimedia,
)
from modules.visuals.style_router import (
    coerce_visual_style_plan,
    sanitize_text,
    should_skip_stock_video,
    stylized_query_variants,
)


def fetch_image_for_cue(
    cue: ImageCue,
    image_dir: Path,
    genre: GenreConfig,
    pexels_key: str = "",
    pixabay_key: str = "",
    visual_style: dict | None = None,
    asset_intent_profile: dict | None = None,
) -> tuple[str, str]:
    """Resolve one cue into an image path from online sources."""
    style_plan = coerce_visual_style_plan(visual_style)
    cache_key = f"{style_plan.render_style}:{cue.keyword}" if style_plan.mode == "illustration" else cue.keyword
    image_dir.mkdir(parents=True, exist_ok=True)
    safe_name = hashlib.md5(cache_key.encode("utf-8")).hexdigest()[:12]
    target = image_dir / f"{safe_name}.jpg"
    if target.exists():
        return str(target), "cache"
    cached = restore_cached_image(cache_key, target)
    if cached:
        return cached

    query_variants = _query_variants(cue.keyword, genre, style_plan, asset_intent_profile)
    intent = build_asset_intent(cue, genre, asset_intent_profile)
    candidates: list[tuple[str, object]] = []
    search_errors: list[str] = []
    jobs = _search_jobs(query_variants, pexels_key, pixabay_key, style_plan)
    with ThreadPoolExecutor(max_workers=min(8, max(1, len(jobs)))) as executor:
        future_map = {
            executor.submit(search_fn, *args): (source_name, query)
            for source_name, query, search_fn, args in jobs
        }
        for future in as_completed(future_map):
            source_name, query = future_map[future]
            try:
                candidates.extend((query, result) for result in future.result())
            except Exception as exc:
                search_errors.append(f"{source_name}({query}): {exc}")

    deduped = _dedupe_candidates(candidates)
    scored = [
        (score_image(result, query) + score_intent_alignment(result, query, intent), result)
        for query, result in deduped
        if result.url and not reject_for_intent(result, query, intent)
    ]
    scored = [(score, result) for score, result in scored if score > 0]
    scored.sort(key=lambda item: item[0], reverse=True)
    if not scored:
        details = f" Search errors: {'; '.join(search_errors)}" if search_errors else ""
        raise RuntimeError(f"No online image candidates found for cue: {cue.keyword}.{details}")

    download_errors: list[str] = []
    for _, result in scored[:8]:
        try:
            path = download_image(result.url, target)
            record_image_asset(cache_key, result.source, result.url, path)
            return path, result.source
        except Exception as exc:
            download_errors.append(f"{result.source}: {exc}")
            continue

    details_parts = download_errors + [f"search {error}" for error in search_errors]
    details = "; ".join(details_parts) if details_parts else "no download attempts"
    raise RuntimeError(f"Could not download an online image for cue '{cue.keyword}': {details}")


def _query_variants(
    keyword: str,
    genre: GenreConfig,
    visual_style: dict | object | None = None,
    asset_intent_profile: dict | None = None,
) -> list[str]:
    style_plan = coerce_visual_style_plan(visual_style)
    if style_plan.mode == "illustration":
        return stylized_query_variants(keyword, style_plan, fallback_topic=style_plan.sanitized_topic)
    visual_keyword = rewrite_query_for_intent(
        _visual_search_query(keyword, genre, asset_intent_profile),
        genre,
        asset_intent_profile=asset_intent_profile,
    )
    visual_keyword = sanitize_text(visual_keyword)
    intent = build_asset_intent(ImageCue(keyword=visual_keyword, timestamp_hint="word_0"), genre, asset_intent_profile)
    words = _important_words(visual_keyword)
    compact = " ".join(words[:5])
    subject = " ".join(words[:3])
    genre_hint = genre.display_name.replace("Stories", "").replace("Facts", "").strip().lower()
    variants = expand_query_for_intent(visual_keyword, intent) + [
        visual_keyword,
        compact,
        subject,
        f"{subject} vertical photo",
        f"{subject} stock photo",
        f"{genre_hint} {subject}".strip(),
        _generic_visual_query(words, genre),
    ]
    cleaned: list[str] = []
    seen: set[str] = set()
    for query in variants:
        normalized = re.sub(r"\s+", " ", query).strip()
        if normalized and normalized.lower() not in seen:
            cleaned.append(normalized)
            seen.add(normalized.lower())
    return cleaned


def _search_jobs(
    query_variants: list[str],
    pexels_key: str,
    pixabay_key: str,
    visual_style: dict | object | None = None,
) -> list[tuple[str, str, object, tuple]]:
    """Create a bounded parallel search plan without overloading fallback APIs."""
    style_plan = coerce_visual_style_plan(visual_style)
    jobs: list[tuple[str, str, object, tuple]] = []
    primary_queries = query_variants[:4]
    fallback_queries = query_variants[:3] if style_plan.mode == "illustration" else query_variants[:2]
    if pexels_key and not should_skip_stock_video(style_plan):
        jobs.extend(("pexels", query, search_pexels, (query, pexels_key)) for query in primary_queries)
    if pixabay_key:
        image_type = "illustration" if style_plan.mode == "illustration" else "photo"
        jobs.extend(("pixabay", query, search_pixabay, (query, pixabay_key, 5, image_type)) for query in primary_queries)
    jobs.extend(("openverse", query, search_openverse, (query,)) for query in primary_queries[:4])
    jobs.extend(("bing", query, search_bing_images, (query,)) for query in fallback_queries[:3])
    jobs.extend(("wikimedia", query, search_wikimedia, (query,)) for query in fallback_queries[:2])
    return jobs


def _dedupe_candidates(candidates: list[tuple[str, object]]) -> list[tuple[str, object]]:
    deduped: list[tuple[str, object]] = []
    seen: set[str] = set()
    for query, result in candidates:
        url = getattr(result, "url", "")
        key = url.split("?")[0].strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append((query, result))
    return deduped


def _visual_search_query(keyword: str, genre: GenreConfig, asset_intent_profile: dict | None = None) -> str:
    """Convert abstract/emotional cues into concrete stock-photo searches."""
    original_text = re.sub(r"\s+", " ", sanitize_text(keyword).lower()).strip()
    text = _remove_abstract_phrases(original_text)

    intent_query = specific_rewrite_for_intent(original_text, genre, asset_intent_profile)
    if intent_query:
        return intent_query

    if any(word in original_text for word in ("exam", "neet", "paper", "student", "classroom", "study")):
        if any(word in original_text for word in ("leak", "scam", "paper")):
            return "student holding exam paper classroom"
        if any(word in original_text for word in ("overwhelm", "stress", "pressure", "anxious", "anxiety")):
            return "stressed student exam papers classroom"
        return "students writing exam classroom"
    if any(word in original_text for word in ("phone", "message", "voicemail", "screen")):
        return "person holding phone message screen"
    if any(word in original_text for word in ("laptop", "computer", "folder", "screen")):
        return "laptop screen desk folder"
    if any(word in original_text for word in ("doctor", "hospital", "medical")):
        return "doctor hospital corridor clipboard"
    if any(word in original_text for word in ("money", "debt", "bank", "bill")):
        return "bank papers kitchen table"
    if any(word in original_text for word in ("family", "father", "mother", "daughter", "boyfriend")):
        return "tense family conversation living room"

    words = _important_words(text)
    if len(words) < 2:
        return _generic_visual_query(words, genre)
    return " ".join(words[:5])


def _remove_abstract_phrases(text: str) -> str:
    blocked_phrases = (
        "feeling",
        "feelings",
        "emotion",
        "emotional",
        "overwhelmed",
        "overwhelming",
        "pressure",
        "stress",
        "anxiety",
        "fear",
        "hopeless",
        "dramatic",
        "cinematic",
        "mysterious",
        "scary",
        "sad",
        "angry",
    )
    cleaned = text
    for phrase in blocked_phrases:
        cleaned = re.sub(rf"\b{re.escape(phrase)}\b", " ", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def _important_words(text: str) -> list[str]:
    blocked = {
        "glowing", "mysterious", "cinematic", "professional", "vertical",
        "photo", "image", "dark", "eerie", "dramatic", "old", "feeling",
        "overwhelmed", "overwhelming", "emotion", "emotional", "pressure",
        "stress", "anxiety", "fear", "moment", "thing", "something",
    }
    words = []
    for raw in text.split():
        word = re.sub(r"[^A-Za-z0-9]", "", raw).lower()
        if len(word) < 3 or word in blocked:
            continue
        words.append(word)
    return words or ["person", "room"]


def _generic_visual_query(words: list[str], genre: GenreConfig) -> str:
    joined = " ".join(words)
    if "laptop" in words or "screen" in words or "folder" in words:
        return "computer screen desk"
    if genre.genre_id == "scary_stories":
        return f"dark room {joined}".strip()
    if genre.genre_id == "reddit_stories":
        return f"person conversation {joined}".strip()
    if genre.genre_id == "history_facts":
        return f"historic documentary {joined}".strip()
    return f"stock photo {joined}".strip()
