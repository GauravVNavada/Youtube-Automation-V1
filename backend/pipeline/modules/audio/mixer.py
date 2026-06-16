from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


def mix_audio_simple(narration_path: str, output_path: Path) -> str:
    """Prepare the final narrator track with compact, continuous pacing."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    _compact_silences(Path(narration_path), output_path)
    return str(output_path)


def _compact_silences(input_path: Path, output_path: Path) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg is required to compact narration silences")

    # Google TTS often inserts 700ms+ punctuation pauses. Keep a natural
    # spoken breath, but collapse dead air before Whisper alignment/rendering.
    audio_filter = (
        "silenceremove="
        "start_periods=1:"
        "start_duration=0.05:"
        "start_threshold=-35dB:"
        "start_silence=0.02:"
        "stop_periods=-1:"
        "stop_duration=0.22:"
        "stop_threshold=-35dB:"
        "stop_silence=0.16:"
        "detection=rms,"
        "aresample=24000"
    )
    proc = subprocess.run(
        [
            ffmpeg,
            "-y",
            "-hide_banner",
            "-i",
            str(input_path),
            "-af",
            audio_filter,
            "-ac",
            "1",
            str(output_path),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg silence compaction failed: {proc.stderr.strip()}")
    if not output_path.exists() or output_path.stat().st_size < 1024:
        raise RuntimeError("ffmpeg silence compaction produced an unusable audio file")
