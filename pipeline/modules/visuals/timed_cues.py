from __future__ import annotations

import json
import re
from typing import Any

from app.schemas import GenreConfig, ScriptOutput, TimedVisualCue, WordTimestamp
from modules.assets.subject_lock import FallbackLevel, SubjectLock, infer_subject_lock
from modules.llm.json_utils import parse_llm_json


MIN_VISUAL_SEGMENT_MS = 3500
MAX_VISUAL_SEGMENT_MS = 5200
NATURAL_PAUSE_MS = 650
MIN_NATURAL_SEGMENT_MS = 1400
VISUAL_REWRITE_MAX_OUTPUT_TOKENS = 4096

VISUAL_REWRITE_SYSTEM_PROMPT = """Rewrite timed narration chunks into visual asset search queries.
Return only JSON with this shape:
{"cues":[{"index":0,"query":"concrete visual search query","mood":"neutral","role":"timed_segment"}]}

Rules:
- Keep one entry per provided index when possible.
- Query must describe visible things only: people, places, objects, actions, setting.
- Do not mention duration, timestamps, narration, captions, script, voiceover, or camera instructions.
- If a required subject is present, the query must include that exact subject or a listed alias.
- Use short search-friendly phrases, not sentences.
"""


STOPWORDS = {
    "a",
    "about",
    "after",
    "all",
    "also",
    "am",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "because",
    "but",
    "by",
    "can",
    "could",
    "did",
    "do",
    "does",
    "duration",
    "for",
    "from",
    "had",
    "has",
    "have",
    "he",
    "her",
    "him",
    "his",
    "how",
    "i",
    "if",
    "in",
    "into",
    "is",
    "it",
    "its",
    "just",
    "make",
    "me",
    "my",
    "not",
    "of",
    "on",
    "or",
    "our",
    "over",
    "seconds",
    "she",
    "short",
    "so",
    "that",
    "the",
    "their",
    "them",
    "then",
    "there",
    "they",
    "this",
    "to",
    "u",
    "up",
    "us",
    "video",
    "was",
    "we",
    "were",
    "what",
    "when",
    "where",
    "who",
    "why",
    "will",
    "with",
    "would",
    "you",
    "your",
}

MOOD_WORDS = {
    "angry": "tense",
    "battle": "action",
    "dark": "dark",
    "fight": "action",
    "fighting": "action",
    "horrified": "fear",
    "night": "dark",
    "scared": "fear",
    "screaming": "fear",
    "strange": "eerie",
    "terrified": "fear",
}


def generate_timed_visual_cues(
    *,
    script: ScriptOutput,
    words: list[WordTimestamp],
    genre: GenreConfig,
    duration_ms: int,
    topic: str = "",
    provider=None,
    min_segment_ms: int = MIN_VISUAL_SEGMENT_MS,
) -> tuple[list[TimedVisualCue], dict[str, Any]]:
    clean_words = _clean_words(words)
    if not clean_words:
        return [], {"error": "word timestamps missing"}

    chunks = merge_caption_phrases_for_visuals(
        clean_words,
        duration_ms=duration_ms,
        min_segment_ms=min_segment_ms,
    )
    subject_lock = _subject_lock_from_context(topic, script)
    fallback_queries = [
        deterministic_visual_query(_query_text_for_chunk(chunk), genre=genre, subject_lock=subject_lock)
        for chunk in chunks
    ]
    rewrite_data = rewrite_visual_queries_batch(
        chunks=chunks,
        fallback_queries=fallback_queries,
        genre=genre,
        subject_lock=subject_lock,
        provider=provider,
    )
    rewrites = rewrite_data.get("queries", {})

    cues: list[TimedVisualCue] = []
    for index, chunk in enumerate(chunks):
        rewritten = rewrites.get(index, {})
        query = str(rewritten.get("query") or fallback_queries[index]).strip()
        if not _usable_query(query, subject_lock):
            query = fallback_queries[index]
        query = _ensure_subject_in_query(query, subject_lock)
        cues.append(
            TimedVisualCue(
                start_ms=int(chunk["start_ms"]),
                end_ms=int(chunk["end_ms"]),
                text=str(chunk["text"]),
                search_query=query,
                subject_lock=subject_lock.enabled,
                required_subjects=[subject_lock.subject] if subject_lock.enabled and subject_lock.subject else [],
                aliases=list(subject_lock.aliases) if subject_lock.enabled else [],
                role=str(rewritten.get("role") or _role_for_query(query)),
                mood=str(rewritten.get("mood") or _mood_for_text(chunk["text"])),
                allowed_fallback_level=FallbackLevel.SUBJECT_ALIAS if subject_lock.enabled else FallbackLevel.GENERIC_SCENE,
            )
        )

    return cues, {
        "chunk_count": len(chunks),
        "min_segment_ms": min_segment_ms,
        "rewrite_provider": getattr(provider, "name", "none") if provider else "none",
        "rewrite_error": rewrite_data.get("error", ""),
        "rewrite_partial": rewrite_data.get("partial", False),
        "subject_lock": {
            "enabled": subject_lock.enabled,
            "subject": subject_lock.subject,
            "aliases": list(subject_lock.aliases),
        },
    }


def merge_caption_phrases_for_visuals(
    words: list[WordTimestamp],
    *,
    duration_ms: int,
    min_segment_ms: int = MIN_VISUAL_SEGMENT_MS,
    max_segment_ms: int = MAX_VISUAL_SEGMENT_MS,
) -> list[dict[str, Any]]:
    if not words:
        return []

    groups: list[list[WordTimestamp]] = []
    current: list[WordTimestamp] = []
    for index, word in enumerate(words):
        current.append(word)
        duration = current[-1].end_ms - current[0].start_ms
        next_gap = words[index + 1].start_ms - word.end_ms if index + 1 < len(words) else 0
        natural_boundary = _ends_sentence(word.word) or next_gap >= NATURAL_PAUSE_MS
        long_enough = duration >= MIN_NATURAL_SEGMENT_MS
        too_long_without_boundary = duration >= max(min_segment_ms, max_segment_ms)
        if natural_boundary and long_enough:
            groups.append(current)
            current = []
        elif too_long_without_boundary:
            groups.append(current)
            current = []
    if current:
        if groups and current[-1].end_ms - current[0].start_ms < MIN_NATURAL_SEGMENT_MS:
            groups[-1].extend(current)
        else:
            groups.append(current)

    if not groups:
        groups = [words]

    cue_windows: list[dict[str, Any]] = []
    final_end = max(duration_ms, groups[-1][-1].end_ms)
    for index, group in enumerate(groups):
        start_ms = 0 if index == 0 else max(0, group[0].start_ms)
        if index + 1 < len(groups):
            end_ms = max(start_ms + 1, groups[index + 1][0].start_ms)
        else:
            end_ms = max(start_ms + 1, final_end)
        cue_windows.append(
            {
                "index": index,
                "start_ms": start_ms,
                "end_ms": end_ms,
                "text": _words_to_text(group),
            }
        )
    return _split_long_windows(cue_windows, max_segment_ms=max_segment_ms)


def rewrite_visual_queries_batch(
    *,
    chunks: list[dict[str, Any]],
    fallback_queries: list[str],
    genre: GenreConfig,
    subject_lock: SubjectLock,
    provider=None,
) -> dict[str, Any]:
    if not provider:
        return {"queries": {}, "error": ""}
    try:
        raw = provider.generate_json(
            VISUAL_REWRITE_SYSTEM_PROMPT,
            _rewrite_prompt(chunks, fallback_queries, genre, subject_lock),
            VISUAL_REWRITE_MAX_OUTPUT_TOKENS,
        )
        data = raw if isinstance(raw, dict) else parse_llm_json(str(raw))
        cues = data.get("cues", [])
        if not isinstance(cues, list):
            raise ValueError("visual rewrite JSON must include a cues list")
        parsed: dict[int, dict[str, str]] = {}
        for item in cues:
            if not isinstance(item, dict):
                continue
            try:
                index = int(item.get("index"))
            except Exception:
                continue
            if index < 0 or index >= len(chunks):
                continue
            query = _sanitize_query(str(item.get("query") or ""))
            if not query:
                continue
            parsed[index] = {
                "query": _ensure_subject_in_query(query, subject_lock),
                "mood": _clean_label(item.get("mood"), "neutral"),
                "role": _clean_label(item.get("role"), "timed_segment"),
            }
        return {"queries": parsed, "partial": len(parsed) < len(chunks)}
    except Exception as exc:
        return {"queries": {}, "error": f"{type(exc).__name__}: {exc}", "partial": True}


def deterministic_visual_query(text: str, *, genre: GenreConfig, subject_lock: SubjectLock) -> str:
    words = _keywords_from_text(text)
    if not words:
        words = _genre_default_words(genre)
    query = " ".join(words[:8])
    if genre.genre_id == "scary_stories" and "dark" not in query.lower():
        query = f"dark {query}".strip()
    if genre.genre_id == "reddit_stories" and not any(term in query.lower() for term in ("person", "people", "conversation")):
        query = f"person conversation {query}".strip()
    return _ensure_subject_in_query(_sanitize_query(query), subject_lock)


def timed_cue_to_image_cue(cue: TimedVisualCue):
    from app.schemas import ImageCue

    return ImageCue(
        keyword=cue.search_query,
        timestamp_hint=f"{cue.start_ms}-{cue.end_ms}ms",
        mood=cue.mood,
        role=cue.role,
        subject_lock=cue.subject_lock,
        required_subjects=list(cue.required_subjects),
        aliases=list(cue.aliases),
        allowed_fallback_level=cue.allowed_fallback_level,
    )


def _rewrite_prompt(
    chunks: list[dict[str, Any]],
    fallback_queries: list[str],
    genre: GenreConfig,
    subject_lock: SubjectLock,
) -> str:
    payload = {
        "genre_id": genre.genre_id,
        "required_subject": subject_lock.subject if subject_lock.enabled else "",
        "aliases": list(subject_lock.aliases) if subject_lock.enabled else [],
        "chunks": [
            {
                "index": chunk["index"],
                "start_ms": chunk["start_ms"],
                "end_ms": chunk["end_ms"],
                "text": chunk["text"],
                "visual_variant": chunk.get("visual_variant", ""),
                "fallback_query": fallback_queries[index],
            }
            for index, chunk in enumerate(chunks)
        ],
    }
    return json.dumps(payload, ensure_ascii=True)


def _subject_lock_from_context(topic: str, script: ScriptOutput) -> SubjectLock:
    topic_lock = infer_subject_lock(topic)
    if topic_lock.enabled:
        return topic_lock
    for cue in script.image_cues:
        for subject in cue.required_subjects:
            if _looks_like_real_subject(subject):
                lock = infer_subject_lock(subject)
                if lock.enabled:
                    return lock
    return SubjectLock(enabled=False)


def _clean_words(words: list[WordTimestamp]) -> list[WordTimestamp]:
    cleaned = [
        word
        for word in words
        if str(word.word or "").strip() and int(word.end_ms) > int(word.start_ms)
    ]
    return sorted(cleaned, key=lambda item: (item.start_ms, item.end_ms))


def _words_to_text(words: list[WordTimestamp]) -> str:
    text = " ".join(str(word.word).strip() for word in words if str(word.word).strip())
    return re.sub(r"\s+([,.;!?])", r"\1", text)


def _ends_sentence(word: str) -> bool:
    return str(word or "").rstrip().endswith((".", "!", "?"))


def _split_long_windows(cue_windows: list[dict[str, Any]], *, max_segment_ms: int) -> list[dict[str, Any]]:
    if max_segment_ms <= 0:
        return cue_windows
    variants = ("wide shot", "close up", "action angle", "reaction shot")
    output: list[dict[str, Any]] = []
    for cue in cue_windows:
        start_ms = int(cue["start_ms"])
        end_ms = int(cue["end_ms"])
        duration_ms = end_ms - start_ms
        if duration_ms <= max_segment_ms:
            cue = dict(cue)
            cue["index"] = len(output)
            output.append(cue)
            continue
        parts = max(2, (duration_ms + max_segment_ms - 1) // max_segment_ms)
        part_duration = max(1, duration_ms // parts)
        for part in range(parts):
            part_start = start_ms + part * part_duration
            part_end = end_ms if part == parts - 1 else min(end_ms, part_start + part_duration)
            split_cue = dict(cue)
            split_cue["index"] = len(output)
            split_cue["start_ms"] = part_start
            split_cue["end_ms"] = max(part_start + 1, part_end)
            split_cue["visual_variant"] = variants[part % len(variants)]
            output.append(split_cue)
    return output


def _query_text_for_chunk(chunk: dict[str, Any]) -> str:
    variant = str(chunk.get("visual_variant") or "").strip()
    if not variant:
        return str(chunk.get("text") or "")
    return f"{chunk.get('text', '')} {variant}"


def _keywords_from_text(text: str) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for raw in re.findall(r"[A-Za-z0-9][A-Za-z0-9'-]*", text):
        word = raw.strip("'").lower()
        if len(word) < 3 or word in STOPWORDS or re.fullmatch(r"\d+", word):
            continue
        if word not in seen:
            output.append(word)
            seen.add(word)
    return output


def _genre_default_words(genre: GenreConfig) -> list[str]:
    if genre.genre_id == "scary_stories":
        return ["dark", "room", "night"]
    if genre.genre_id == "reddit_stories":
        return ["person", "phone", "conversation"]
    if genre.genre_id == "history_facts":
        return ["historic", "place", "archive"]
    return ["person", "scene"]


def _ensure_subject_in_query(query: str, subject_lock: SubjectLock) -> str:
    query = _sanitize_query(query)
    if not subject_lock.enabled or not subject_lock.subject:
        return query
    phrases = [subject_lock.subject, *subject_lock.aliases]
    if any(_contains_phrase(query, phrase) for phrase in phrases):
        return query
    return _sanitize_query(f"{subject_lock.subject} {query}")


def _usable_query(query: str, subject_lock: SubjectLock) -> bool:
    query = _sanitize_query(query)
    if len(query) < 3:
        return False
    blocked = {"caption", "narration", "timestamp", "duration", "voiceover", "script"}
    if any(word in query.lower().split() for word in blocked):
        return False
    if subject_lock.enabled and not any(_contains_phrase(query, phrase) for phrase in [subject_lock.subject, *subject_lock.aliases]):
        return False
    return True


def _sanitize_query(value: str) -> str:
    value = re.sub(r"\b(?:duration|timestamp|caption|narration|voiceover)\b", " ", str(value), flags=re.I)
    value = re.sub(r"\b\d+\s*(?:seconds?|secs?|s|ms)\b", " ", value, flags=re.I)
    value = re.sub(r"\b(?:[1-9]|[1-9][0-9]|1[01][0-9]|120)\b", " ", value)
    value = re.sub(r"[^A-Za-z0-9' -]+", " ", value)
    return " ".join(value.split())[:140]


def _clean_label(value: Any, fallback: str) -> str:
    text = re.sub(r"[^A-Za-z0-9_-]+", "_", str(value or "").strip().lower())
    return text[:40] or fallback


def _mood_for_text(text: str) -> str:
    lower = str(text).lower()
    for word, mood in MOOD_WORDS.items():
        if word in lower:
            return mood
    return "neutral"


def _role_for_query(query: str) -> str:
    lower = query.lower()
    if any(term in lower for term in ("face", "person", "man", "woman", "character", "iron man", "avengers")):
        return "primary_subject"
    if any(term in lower for term in ("room", "street", "city", "hallway", "lab")):
        return "setting"
    return "timed_segment"


def _contains_phrase(text: str, phrase: str) -> bool:
    return str(phrase or "").lower().strip() in str(text or "").lower()


def _looks_like_real_subject(value: str) -> bool:
    lower = str(value or "").lower().strip()
    if not lower:
        return False
    if re.fullmatch(r"duration\s+\d+", lower) or re.fullmatch(r"\d+", lower):
        return False
    return lower not in {"duration", "seconds", "video", "short"}
