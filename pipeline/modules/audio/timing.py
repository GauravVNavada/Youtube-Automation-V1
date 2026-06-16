from __future__ import annotations

from app.schemas import WordTimestamp


def evenly_spaced_word_timestamps(words: list[str], duration_ms: int) -> list[WordTimestamp]:
    if not words:
        return []
    step = max(1, duration_ms // len(words))
    return [WordTimestamp(word=word, start_ms=index * step, end_ms=min(duration_ms, (index + 1) * step)) for index, word in enumerate(words)]
