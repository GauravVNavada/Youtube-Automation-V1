from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from app.schemas import WordTimestamp

_WHISPER_MODEL = None
PAUSE_ENDINGS = (".", "!", "?", ",", ";", ":")


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
    timestamps = _snap_sentence_starts_to_audio(timestamps, audio_path)
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


def _snap_sentence_starts_to_audio(
    timestamps: list[WordTimestamp],
    audio_path: str | Path,
    phrase_gap_ms: int = 600,
    min_word_ms: int = 40,
) -> list[WordTimestamp]:
    """Move post-pause first-word starts to the audible edge of real audio."""
    silence_intervals = _detect_silence_intervals(audio_path)
    if not silence_intervals:
        return timestamps

    adjusted: list[WordTimestamp] = []
    for index, word in enumerate(timestamps):
        start_ms = word.start_ms
        if _is_phrase_start(timestamps, index, phrase_gap_ms):
            silence_end = _overlapping_silence_end(start_ms, word.end_ms, silence_intervals)
            if silence_end is not None and silence_end > start_ms:
                start_ms = silence_end
        adjusted.append(
            WordTimestamp(
                word=word.word,
                start_ms=start_ms,
                end_ms=max(word.end_ms, start_ms + min_word_ms),
            )
        )
    return adjusted


def _is_phrase_start(words: list[WordTimestamp], index: int, phrase_gap_ms: int) -> bool:
    if index == 0:
        return True
    previous = words[index - 1]
    current = words[index]
    return previous.word.rstrip().endswith(PAUSE_ENDINGS) or current.start_ms - previous.end_ms > phrase_gap_ms


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


def _overlapping_silence_end(
    start_ms: int,
    end_ms: int,
    silence_intervals: list[tuple[int, int]],
) -> int | None:
    for silence_start, silence_end in silence_intervals:
        if silence_start <= start_ms < silence_end:
            return silence_end
    return None


def _detect_silence_intervals(audio_path: str | Path) -> list[tuple[int, int]]:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return []
    proc = subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-i",
            str(audio_path),
            "-af",
            "silencedetect=noise=-30dB:d=0.05",
            "-f",
            "null",
            "-",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if proc.returncode != 0:
        return []

    starts: list[float] = []
    intervals: list[tuple[int, int]] = []
    for line in proc.stderr.splitlines():
        start_match = re.search(r"silence_start:\s*(\d+(?:\.\d+)?)", line)
        if start_match:
            starts.append(float(start_match.group(1)))
            continue
        end_match = re.search(r"silence_end:\s*(\d+(?:\.\d+)?)", line)
        if end_match and starts:
            start = starts.pop(0)
            end = float(end_match.group(1))
            intervals.append((int(start * 1000), int(end * 1000)))
    return intervals
