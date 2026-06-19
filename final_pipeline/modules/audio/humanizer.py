from __future__ import annotations

import wave
from dataclasses import dataclass
from pathlib import Path

from app.schemas import WordTimestamp


SENTENCE_PAUSE_MS = 650
MINOR_PAUSE_MS = 300
WORD_PAUSE_MS = 180
TRAILING_PAUSE_MS = 450
MIN_CUT_MS = 60
PAUSE_ENDINGS = (".", "!", "?", ",", ";", ":")


@dataclass(frozen=True)
class HumanizedAudio:
    path: str
    duration_ms: int
    word_timestamps: list[WordTimestamp]
    removed_ms: int


def humanize_narration_pauses(
    input_path: str | Path,
    output_path: str | Path,
    word_timestamps: list[WordTimestamp],
    source_duration_ms: int,
) -> HumanizedAudio:
    """Trim only excess dead air while preserving human punctuation pauses.

    The function uses aligned word gaps to cap abnormal TTS pauses without
    removing normal sentence and comma breaths from the waveform.
    """
    input_path = Path(input_path)
    output_path = Path(output_path)
    if not word_timestamps:
        raise RuntimeError("Word timestamps are required to humanize narration pauses")

    cuts = _build_excess_pause_cuts(word_timestamps, source_duration_ms)
    if not cuts:
        output_path.write_bytes(input_path.read_bytes())
        return HumanizedAudio(
            path=str(output_path),
            duration_ms=source_duration_ms,
            word_timestamps=word_timestamps,
            removed_ms=0,
        )

    _write_cut_wav(input_path, output_path, cuts, source_duration_ms)
    removed_ms = sum(end_ms - start_ms for start_ms, end_ms in cuts)
    return HumanizedAudio(
        path=str(output_path),
        duration_ms=max(0, source_duration_ms - removed_ms),
        word_timestamps=_shift_timestamps(word_timestamps, cuts),
        removed_ms=removed_ms,
    )


def _build_excess_pause_cuts(
    words: list[WordTimestamp],
    source_duration_ms: int,
) -> list[tuple[int, int]]:
    cuts: list[tuple[int, int]] = []

    for index, current in enumerate(words[:-1]):
        next_word = words[index + 1]
        if not _has_punctuation_pause(current.word):
            continue
        gap_start = current.end_ms
        gap_end = next_word.start_ms
        gap_ms = gap_end - gap_start
        if gap_ms <= 0:
            continue

        keep_ms = _target_pause_after(current.word)
        cut_ms = gap_ms - keep_ms
        if cut_ms >= MIN_CUT_MS:
            cuts.append((gap_start + keep_ms, gap_end))

    trailing_gap_ms = source_duration_ms - words[-1].end_ms
    trailing_cut_ms = trailing_gap_ms - TRAILING_PAUSE_MS
    if trailing_cut_ms >= MIN_CUT_MS:
        cuts.append((words[-1].end_ms + TRAILING_PAUSE_MS, source_duration_ms))

    return _merge_cuts(cuts)


def _target_pause_after(word: str) -> int:
    stripped = word.rstrip()
    if stripped.endswith((".", "!", "?")):
        return SENTENCE_PAUSE_MS
    if stripped.endswith((",", ";", ":")):
        return MINOR_PAUSE_MS
    return WORD_PAUSE_MS


def _has_punctuation_pause(word: str) -> bool:
    return str(word or "").rstrip().endswith(PAUSE_ENDINGS)


def _merge_cuts(cuts: list[tuple[int, int]]) -> list[tuple[int, int]]:
    merged: list[tuple[int, int]] = []
    for start_ms, end_ms in sorted(cuts):
        if end_ms <= start_ms:
            continue
        if not merged or start_ms > merged[-1][1]:
            merged.append((start_ms, end_ms))
            continue
        previous_start, previous_end = merged[-1]
        merged[-1] = (previous_start, max(previous_end, end_ms))
    return merged


def _shift_timestamps(words: list[WordTimestamp], cuts: list[tuple[int, int]]) -> list[WordTimestamp]:
    shifted: list[WordTimestamp] = []
    for word in words:
        removed_before_start = _removed_before(word.start_ms, cuts)
        removed_before_end = _removed_before(word.end_ms, cuts)
        shifted.append(
            WordTimestamp(
                word=word.word,
                start_ms=max(0, word.start_ms - removed_before_start),
                end_ms=max(0, word.end_ms - removed_before_end),
            )
        )
    return shifted


def _removed_before(ms: int, cuts: list[tuple[int, int]]) -> int:
    removed = 0
    for start_ms, end_ms in cuts:
        if ms <= start_ms:
            break
        removed += min(ms, end_ms) - start_ms
    return removed


def _write_cut_wav(
    input_path: Path,
    output_path: Path,
    cuts: list[tuple[int, int]],
    source_duration_ms: int,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(input_path), "rb") as reader:
        params = reader.getparams()
        frame_rate = reader.getframerate()
        frames = reader.readframes(reader.getnframes())

    bytes_per_frame = params.nchannels * params.sampwidth
    segments = _kept_segments(cuts, source_duration_ms)
    output = bytearray()
    for start_ms, end_ms in segments:
        start_frame = _ms_to_frame(start_ms, frame_rate)
        end_frame = _ms_to_frame(end_ms, frame_rate)
        output.extend(frames[start_frame * bytes_per_frame : end_frame * bytes_per_frame])

    with wave.open(str(output_path), "wb") as writer:
        writer.setparams(params)
        writer.writeframes(bytes(output))


def _kept_segments(cuts: list[tuple[int, int]], duration_ms: int) -> list[tuple[int, int]]:
    segments: list[tuple[int, int]] = []
    cursor = 0
    for cut_start, cut_end in cuts:
        if cut_start > cursor:
            segments.append((cursor, cut_start))
        cursor = max(cursor, cut_end)
    if cursor < duration_ms:
        segments.append((cursor, duration_ms))
    return segments


def _ms_to_frame(ms: int, frame_rate: int) -> int:
    return max(0, round(ms * frame_rate / 1000))
