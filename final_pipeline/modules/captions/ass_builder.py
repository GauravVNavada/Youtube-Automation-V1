from __future__ import annotations

from pathlib import Path

from app.schemas import WordTimestamp
from modules.captions.segmenter import segment_words


PRESETS = {
    "classic_white": {
        "font": "Montserrat Black",
        "primary": "&H00FFFFFF",
        "secondary": "&H0000E6FF",
        "outline": "&H00000000",
        "shadow": "&H99000000",
    },
    "bold_pop": {
        "font": "Montserrat Black",
        "primary": "&H00FFFFFF",
        "secondary": "&H0000E6FF",
        "outline": "&H00000000",
        "shadow": "&H99000000",
    },
    "horror_red": {
        "font": "Creepster",
        "primary": "&H00FFFFFF",
        "secondary": "&H002424D8",
        "outline": "&H00000000",
        "shadow": "&H99000000",
    },
    "neon_glow": {
        "font": "Montserrat Black",
        "primary": "&H00FFFFFF",
        "secondary": "&H0000FFFF",
        "outline": "&H00A000FF",
        "shadow": "&H99000000",
    },
    "minimal": {
        "font": "Roboto Bold",
        "primary": "&H00FFFFFF",
        "secondary": "&H00E6E6E6",
        "outline": "&H00000000",
        "shadow": "&HB0000000",
    },
    "tiktok_style": {
        "font": "Montserrat Black",
        "primary": "&H00000000",
        "secondary": "&H0000E6FF",
        "outline": "&H00FFFFFF",
        "shadow": "&H99000000",
    },
    "karaoke_fill": {
        "font": "Montserrat Black",
        "primary": "&H00FFFFFF",
        "secondary": "&H0000E6FF",
        "outline": "&H00000000",
        "shadow": "&H99000000",
    },
    "typewriter": {
        "font": "Roboto Bold",
        "primary": "&H00FFFFFF",
        "secondary": "&H0000E6FF",
        "outline": "&H00000000",
        "shadow": "&H99000000",
    },
    "comic": {
        "font": "Bangers",
        "primary": "&H00FFFFFF",
        "secondary": "&H0000E6FF",
        "outline": "&H00000000",
        "shadow": "&H99000000",
    },
    "clean_pro": {
        "font": "Roboto Bold",
        "primary": "&H00FFFFFF",
        "secondary": "&H0000E6FF",
        "outline": "&H00000000",
        "shadow": "&H99000000",
    },
    "fire": {
        "font": "Anton",
        "primary": "&H00FFFFFF",
        "secondary": "&H000047FF",
        "outline": "&H00000000",
        "shadow": "&H99000000",
    },
    "ice": {
        "font": "Montserrat Black",
        "primary": "&H00FFFFFF",
        "secondary": "&H00FFE6B0",
        "outline": "&H006E4320",
        "shadow": "&H99000000",
    },
}

MIN_FONT_SIZE = 48
MAX_FONT_SIZE = 84
MAX_LINE_CHARS = 25
CAPTION_X = 540
CAPTION_Y = 1450
SIDE_MARGIN = 60
BOTTOM_MARGIN = 250


def build_ass(
    words: list[WordTimestamp],
    output_path: Path,
    preset: str = "clean_pro",
    emphasis_words: list[str] | None = None,
    words_per_caption: int = 4,
) -> tuple[str, int]:
    """Build safe-margin ASS captions for 1080x1920 vertical video."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    colors = PRESETS.get(preset, PRESETS["clean_pro"])
    emphasis = {_normalize(w) for w in (emphasis_words or [])}
    events = []
    phrases = 0
    for raw_chunk in segment_words(
        words,
        max_words_per_phrase=max(1, min(words_per_caption, 8)),
        max_phrase_chars=(MAX_LINE_CHARS * 2) - 8,
        max_phrase_duration_ms=1800,
    ):
        for chunk in _split_for_caption_safety(raw_chunk):
            if not chunk:
                continue
            phrases += 1
            font_size = _font_size_for_chunk(chunk)
            for index, item in enumerate(chunk):
                start_ms = max(chunk[0].start_ms, item.start_ms - 20)
                end_ms = chunk[index + 1].start_ms if index + 1 < len(chunk) else chunk[-1].end_ms
                if end_ms <= start_ms:
                    end_ms = max(item.end_ms, start_ms + 80)
                text = _caption_text(chunk, active_index=index, emphasis=emphasis, colors=colors)
                override = (
                    r"{\an2"
                    rf"\pos({CAPTION_X},{CAPTION_Y})"
                    rf"\fs{font_size}"
                    r"}"
                )
                events.append(
                    "Dialogue: 0,"
                    f"{_ass_time(start_ms)},{_ass_time(end_ms)},"
                    f"Default,,0,0,0,,{override}{text}"
                )

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{colors["font"]},72,{colors["primary"]},{colors["secondary"]},{colors["outline"]},{colors["shadow"]},-1,0,0,0,100,100,0,0,1,6,2,2,{SIDE_MARGIN},{SIDE_MARGIN},{BOTTOM_MARGIN},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    output_path.write_text(header + "\n".join(events) + "\n", encoding="utf-8")
    return str(output_path), phrases


def _split_for_caption_safety(chunk: list[WordTimestamp]) -> list[list[WordTimestamp]]:
    safe_chunks: list[list[WordTimestamp]] = []
    current: list[WordTimestamp] = []
    for item in chunk:
        candidate = current + [item]
        if current and not _fits_caption_safety(candidate):
            safe_chunks.append(current)
            current = [item]
        else:
            current = candidate
    if current:
        safe_chunks.append(current)
    return safe_chunks


def _fits_caption_safety(words: list[WordTimestamp]) -> bool:
    if len(words) > 8:
        return False
    lines: list[list[str]] = [[]]
    for item in words:
        word = item.word
        current_len = sum(len(part) for part in lines[-1]) + max(0, len(lines[-1]) - 1)
        next_len = len(word) if not lines[-1] else current_len + 1 + len(word)
        if lines[-1] and next_len > MAX_LINE_CHARS:
            if len(lines) >= 2:
                return False
            lines.append([word])
        else:
            lines[-1].append(word)
    return True


def _ass_time(ms: int) -> str:
    cs = ms // 10
    seconds, centis = divmod(cs, 100)
    minutes, sec = divmod(seconds, 60)
    hours, minute = divmod(minutes, 60)
    return f"{hours}:{minute:02}:{sec:02}.{centis:02}"


def _caption_text(
    chunk: list[WordTimestamp],
    active_index: int,
    emphasis: set[str],
    colors: dict[str, str],
) -> str:
    lines = _wrap_caption_words([item.word for item in chunk])
    active_word = chunk[active_index].word
    consumed = 0
    rendered_lines = []
    for line in lines:
        parts = []
        for word in line:
            clean = _normalize(word)
            escaped = _escape(word).upper()
            is_active = consumed == active_index
            is_emphasis = clean in emphasis
            if is_active:
                parts.append(
                    r"{\c"
                    + colors["secondary"]
                    + "}"
                    + escaped
                    + r"{\c"
                    + colors["primary"]
                    + "}"
                )
            elif is_emphasis or _normalize(active_word) == clean and len(chunk) == 1:
                parts.append(r"{\c" + colors["secondary"] + "}" + escaped + r"{\c" + colors["primary"] + "}")
            else:
                parts.append(escaped)
            consumed += 1
        rendered_lines.append(" ".join(parts))
    return r"\N".join(rendered_lines[:2])


def _wrap_caption_words(words: list[str]) -> list[list[str]]:
    lines: list[list[str]] = [[]]
    for word in words[:8]:
        next_len = len(word) if not lines[-1] else sum(len(part) for part in lines[-1]) + len(lines[-1]) + len(word)
        if lines[-1] and next_len > MAX_LINE_CHARS and len(lines) < 2:
            lines.append([word])
        else:
            lines[-1].append(word)
    return [line for line in lines if line]


def _font_size_for_chunk(chunk: list[WordTimestamp]) -> int:
    longest_line = max((sum(len(word) for word in line) + max(0, len(line) - 1) for line in _wrap_caption_words([item.word for item in chunk])), default=0)
    if longest_line <= 16:
        return MAX_FONT_SIZE
    if longest_line <= 22:
        return 76
    if longest_line <= MAX_LINE_CHARS:
        return 68
    return MIN_FONT_SIZE


def _normalize(text: str) -> str:
    return text.strip(".,!?;:\"'()[]{}").lower()


def _escape(text: str) -> str:
    return text.replace("{", "").replace("}", "").replace("\n", " ")
