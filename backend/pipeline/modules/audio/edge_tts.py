from __future__ import annotations

import asyncio
import shutil
import subprocess
from pathlib import Path


DEFAULT_EDGE_VOICE = "en-US-GuyNeural"


def synthesize_edge_tts(
    text: str,
    output_path: Path,
    voice_name: str = DEFAULT_EDGE_VOICE,
    speaking_rate: float = 1.0,
) -> str:
    """Generate free EdgeTTS narration and normalize it to WAV for Whisper."""
    try:
        import edge_tts
    except ModuleNotFoundError as exc:
        raise RuntimeError("edge-tts is not installed; install playground pipeline requirements") from exc

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg is required to convert EdgeTTS audio to WAV")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_mp3 = output_path.with_suffix(".edge.mp3")
    if tmp_mp3.exists():
        tmp_mp3.unlink()
    if output_path.exists():
        output_path.unlink()

    rate = _edge_rate(speaking_rate)

    async def _write_audio() -> None:
        communicate = edge_tts.Communicate(text, voice_name, rate=rate)
        await communicate.save(str(tmp_mp3))

    asyncio.run(_write_audio())
    if not tmp_mp3.exists() or tmp_mp3.stat().st_size < 1024:
        raise RuntimeError("EdgeTTS returned an unusably small audio file")

    proc = subprocess.run(
        [
            ffmpeg,
            "-y",
            "-hide_banner",
            "-i",
            str(tmp_mp3),
            "-ac",
            "1",
            "-ar",
            "24000",
            "-acodec",
            "pcm_s16le",
            str(output_path),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg could not convert EdgeTTS audio: {proc.stderr[-1000:]}")
    if not output_path.exists() or output_path.stat().st_size < 1024:
        raise RuntimeError("EdgeTTS WAV conversion produced an unusable file")
    return str(output_path)


def _edge_rate(speaking_rate: float) -> str:
    percent = int(round((max(0.65, min(1.4, speaking_rate)) - 1.0) * 100))
    if percent == 0:
        return "+0%"
    return f"{percent:+d}%"

