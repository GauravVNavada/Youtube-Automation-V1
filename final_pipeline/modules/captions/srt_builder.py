from __future__ import annotations

from pathlib import Path

from app.schemas import WordTimestamp
from modules.captions.segmenter import segment_words


def build_srt(words: list[WordTimestamp], output_path: Path, words_per_caption: int = 4) -> tuple[str, int]:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    blocks = []
    for chunk in segment_words(words, max_words_per_phrase=words_per_caption):
        if not chunk:
            continue
        text = " ".join(w.word for w in chunk)
        blocks.append((chunk[0].start_ms, chunk[-1].end_ms, text))

    lines = []
    for idx, (start, end, text) in enumerate(blocks, start=1):
        lines.extend([
            str(idx),
            f"{_srt_time(start)} --> {_srt_time(end)}",
            text,
            "",
        ])
    output_path.write_text("\n".join(lines), encoding="utf-8")
    return str(output_path), len(blocks)


def _srt_time(ms: int) -> str:
    seconds, milli = divmod(ms, 1000)
    minutes, sec = divmod(seconds, 60)
    hours, minute = divmod(minutes, 60)
    return f"{hours:02}:{minute:02}:{sec:02},{milli:03}"
