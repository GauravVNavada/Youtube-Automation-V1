from __future__ import annotations

from app.schemas import WordTimestamp


SENTENCE_ENDINGS = (".", "!", "?")
PHRASE_GAP_MS = 300
MAX_PHRASE_DURATION_MS = 1200
MAX_PHRASE_CHARS = 32


def segment_words(
    words: list[WordTimestamp],
    max_words_per_phrase: int = 4,
    phrase_gap_ms: int = PHRASE_GAP_MS,
    max_phrase_duration_ms: int = MAX_PHRASE_DURATION_MS,
    max_phrase_chars: int = MAX_PHRASE_CHARS,
) -> list[list[WordTimestamp]]:
    """Split word timestamps into short caption phrases that follow speech pauses."""
    phrases: list[list[WordTimestamp]] = []
    current: list[WordTimestamp] = []

    for index, word in enumerate(words):
        current.append(word)
        should_split = len(current) >= max_words_per_phrase

        if _ends_sentence(word.word):
            should_split = True

        if current and word.end_ms - current[0].start_ms >= max_phrase_duration_ms:
            should_split = True

        if _phrase_chars(current) > max_phrase_chars:
            should_split = True

        if index + 1 < len(words):
            gap_ms = words[index + 1].start_ms - word.end_ms
            if gap_ms >= phrase_gap_ms:
                should_split = True

        if should_split:
            phrases.append(current)
            current = []

    if current:
        phrases.append(current)

    return phrases


def _ends_sentence(word: str) -> bool:
    return word.rstrip().endswith(SENTENCE_ENDINGS)


def _phrase_chars(words: list[WordTimestamp]) -> int:
    return sum(len(word.word) for word in words) + max(0, len(words) - 1)
