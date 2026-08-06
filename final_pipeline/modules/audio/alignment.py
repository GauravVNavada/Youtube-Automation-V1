from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass
from difflib import SequenceMatcher
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
    timestamps = _map_whisper_timestamps_to_script(timestamps, text, duration_ms)
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


def _map_whisper_timestamps_to_script(
    timestamps: list[WordTimestamp],
    text: str,
    duration_ms: int,
) -> list[WordTimestamp]:
    """Return original script words with timings borrowed from fuzzy Whisper alignment."""
    script_words = [_clean_script_word(word) for word in text.split() if _clean_script_word(word)]
    if not script_words:
        return timestamps

    script_norm = [_normalize_word(word) or f"__script_word_{index}__" for index, word in enumerate(script_words)]
    whisper_norm = [_normalize_word(timestamp.word) for timestamp in timestamps]
    script_pairs = list(zip(script_words, script_norm))
    whisper_pairs = [
        (timestamp, norm)
        for timestamp, norm in zip(timestamps, whisper_norm)
        if norm and timestamp.end_ms > timestamp.start_ms
    ]
    if not script_pairs or not whisper_pairs:
        return _evenly_distribute_script_words(script_words, 0, duration_ms)

    aligned: list[WordTimestamp] = []
    matcher = SequenceMatcher(
        None,
        [norm for _word, norm in script_pairs],
        [norm for _timestamp, norm in whisper_pairs],
        autojunk=False,
    )
    for tag, script_start, script_end, whisper_start, whisper_end in matcher.get_opcodes():
        script_span = [word for word, _norm in script_pairs[script_start:script_end]]
        whisper_span = [timestamp for timestamp, _norm in whisper_pairs[whisper_start:whisper_end]]
        if tag == "insert" or not script_span:
            continue
        if tag == "equal" and len(script_span) == len(whisper_span):
            aligned.extend(
                WordTimestamp(word=word, start_ms=timestamp.start_ms, end_ms=timestamp.end_ms)
                for word, timestamp in zip(script_span, whisper_span)
            )
            continue
        aligned.extend(
            _time_script_span(
                script_span,
                whisper_span,
                aligned[-1].end_ms if aligned else 0,
                _next_whisper_start(whisper_pairs, whisper_end, duration_ms),
            )
        )

    if len(aligned) == len(script_words):
        return aligned
    return _evenly_distribute_script_words(script_words, 0, duration_ms)


def _time_script_span(
    script_words: list[str],
    whisper_words: list[WordTimestamp],
    previous_end_ms: int,
    next_start_ms: int,
) -> list[WordTimestamp]:
    if whisper_words:
        start_ms = min(word.start_ms for word in whisper_words)
        end_ms = max(word.end_ms for word in whisper_words)
    else:
        start_ms = previous_end_ms
        end_ms = next_start_ms
    return _evenly_distribute_script_words(script_words, start_ms, max(start_ms + len(script_words), end_ms))


def _evenly_distribute_script_words(
    words: list[str],
    start_ms: int,
    end_ms: int,
    min_word_ms: int = 40,
) -> list[WordTimestamp]:
    if not words:
        return []
    span_ms = max(len(words) * min_word_ms, end_ms - start_ms)
    step_ms = max(min_word_ms, span_ms // len(words))
    output: list[WordTimestamp] = []
    cursor = start_ms
    for index, word in enumerate(words):
        word_start = cursor
        word_end = end_ms if index == len(words) - 1 else min(end_ms, word_start + step_ms)
        if word_end <= word_start:
            word_end = word_start + min_word_ms
        output.append(WordTimestamp(word=word, start_ms=word_start, end_ms=word_end))
        cursor = word_end
    return output


def _next_whisper_start(
    whisper_pairs: list[tuple[WordTimestamp, str]],
    index: int,
    duration_ms: int,
) -> int:
    if index < len(whisper_pairs):
        return whisper_pairs[index][0].start_ms
    return duration_ms


def _normalize_word(word: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", word.lower())


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
