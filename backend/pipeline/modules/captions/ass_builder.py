from __future__ import annotations

from pathlib import Path

from app.schemas import WordTimestamp
from modules.captions.segmenter import segment_words


PRESETS = {
    "horror_red": {
        "primary": "&H00FFFFFF",
        "secondary": "&H002424D8",
        "outline": "&H00000000",
    },
    "clean_pro": {
        "primary": "&H00FFFFFF",
        "secondary": "&H0000E6FF",
        "outline": "&H00000000",
    },
}


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
    emphasis = {w.lower() for w in (emphasis_words or [])}
    events = []
    phrases = 0
    for chunk in segment_words(words, max_words_per_phrase=words_per_caption):
        if not chunk:
            continue
        phrases += 1
        text_parts = []
        for item in chunk:
            clean = item.word.strip(".,!?;:\"'").lower()
            if clean in emphasis:
                text_parts.append(r"{\c" + colors["secondary"] + "}" + _escape(item.word) + r"{\c" + colors["primary"] + "}")
            else:
                text_parts.append(_escape(item.word))
        events.append(
            "Dialogue: 0,"
            f"{_ass_time(chunk[0].start_ms)},{_ass_time(chunk[-1].end_ms)},"
            f"Default,,0,0,0,,{' '.join(text_parts)}"
        )

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,DejaVu Sans,74,{colors["primary"]},{colors["secondary"]},{colors["outline"]},&H80000000,-1,0,0,0,100,100,0,0,1,5,1,2,72,72,260,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    output_path.write_text(header + "\n".join(events) + "\n", encoding="utf-8")
    return str(output_path), phrases


def _ass_time(ms: int) -> str:
    cs = ms // 10
    seconds, centis = divmod(cs, 100)
    minutes, sec = divmod(seconds, 60)
    hours, minute = divmod(minutes, 60)
    return f"{hours}:{minute:02}:{sec:02}.{centis:02}"


def _escape(text: str) -> str:
    return text.replace("{", "").replace("}", "").replace("\n", " ")
