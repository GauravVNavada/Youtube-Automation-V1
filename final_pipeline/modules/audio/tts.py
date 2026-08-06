from __future__ import annotations


def estimate_duration_ms(word_count: int, target_duration: int, voice_rate: float) -> int:
    """Estimate duration, respecting requested target and genre voice rate."""
    by_words = int((word_count / max(1.4, 2.25 * voice_rate)) * 1000)
    requested = target_duration * 1000
    return max(11000, min(max(by_words, requested), requested + 8000))
