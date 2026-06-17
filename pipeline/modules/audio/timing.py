from __future__ import annotations

from app.schemas import WordTimestamp


INITIAL_WORD_DELAY_MS = 220
SENTENCE_GAP_MS = 240
MINOR_GAP_MS = 110
MIN_WORD_MS = 90


def evenly_spaced_word_timestamps(words: list[str], duration_ms: int) -> list[WordTimestamp]:
    if not words:
        return []
    pause_after = [_pause_after(word) if index + 1 < len(words) else 0 for index, word in enumerate(words)]
    total_pause = min(sum(pause_after) + INITIAL_WORD_DELAY_MS, max(0, duration_ms // 5))
    available_ms = max(len(words) * MIN_WORD_MS, duration_ms - total_pause)
    step = max(MIN_WORD_MS, available_ms // len(words))
    timestamps: list[WordTimestamp] = []
    cursor = min(INITIAL_WORD_DELAY_MS, max(0, duration_ms // 20))
    for index, word in enumerate(words):
        start_ms = min(duration_ms, cursor)
        end_ms = min(duration_ms, start_ms + step)
        timestamps.append(WordTimestamp(word=word, start_ms=start_ms, end_ms=max(start_ms + 1, end_ms)))
        cursor = end_ms + pause_after[index]
    if timestamps and timestamps[-1].end_ms > duration_ms:
        timestamps[-1] = WordTimestamp(timestamps[-1].word, timestamps[-1].start_ms, duration_ms)
    return timestamps


def _pause_after(word: str) -> int:
    stripped = str(word or "").rstrip()
    if stripped.endswith((".", "!", "?")):
        return SENTENCE_GAP_MS
    if stripped.endswith((",", ";", ":")):
        return MINOR_GAP_MS
    return 0
