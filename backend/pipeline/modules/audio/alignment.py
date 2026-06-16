from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from app.schemas import WordTimestamp

_WHISPER_MODEL = None


@dataclass(frozen=True)
class AlignmentResult:
    timestamps: list[WordTimestamp]
    source: str


def align_word_timestamps(
    audio_path: str | Path,
    text: str,
    duration_ms: int,
) -> AlignmentResult:
    """Generate word-level timestamps from narration audio using Whisper."""
    timestamps = _whisper_align(audio_path, duration_ms)
    if not timestamps:
        raise RuntimeError("Whisper returned no word-level timestamp data")
    timestamps = _restore_script_words(timestamps, text)
    return AlignmentResult(timestamps=timestamps, source="whisper")


def _whisper_align(audio_path: str | Path, duration_ms: int) -> list[WordTimestamp]:
    global _WHISPER_MODEL
    try:
        import whisper
    except ModuleNotFoundError as exc:
        raise RuntimeError("openai-whisper is required for caption alignment") from exc

    if _WHISPER_MODEL is None:
        _WHISPER_MODEL = whisper.load_model("base")

    result = _WHISPER_MODEL.transcribe(
        str(audio_path),
        language="en",
        word_timestamps=True,
        fp16=False,
    )
    timestamps: list[WordTimestamp] = []
    for segment in result.get("segments", []):
        for word_info in segment.get("words", []):
            word = str(word_info.get("word", "")).strip()
            if not word:
                continue
            start_ms = max(0, int(float(word_info["start"]) * 1000))
            end_ms = min(duration_ms, int(float(word_info["end"]) * 1000))
            if end_ms - start_ms < 80:
                end_ms = min(start_ms + 120, duration_ms)
            timestamps.append(WordTimestamp(word=word, start_ms=start_ms, end_ms=end_ms))
    return timestamps


def _restore_script_words(timestamps: list[WordTimestamp], text: str) -> list[WordTimestamp]:
    script_words = [_clean_script_word(word) for word in text.split() if _clean_script_word(word)]
    if len(script_words) != len(timestamps):
        return timestamps
    return [
        WordTimestamp(word=script_word, start_ms=timestamp.start_ms, end_ms=timestamp.end_ms)
        for script_word, timestamp in zip(script_words, timestamps)
    ]


def _clean_script_word(word: str) -> str:
    return re.sub(r"[*_`]+", "", word.strip())
