from __future__ import annotations

import asyncio
from pathlib import Path


DEFAULT_EDGE_VOICE = "en-US-GuyNeural"


def synthesize_edge_tts(
    text: str,
    output_path: Path,
    voice_name: str = DEFAULT_EDGE_VOICE,
    speaking_rate: float | None = None,
) -> str:
    try:
        import edge_tts
    except ModuleNotFoundError as exc:
        raise RuntimeError("edge-tts is not installed") from exc
    output_path.parent.mkdir(parents=True, exist_ok=True)
    asyncio.run(_synthesize(edge_tts, text, output_path, voice_name, speaking_rate))
    return str(output_path)


async def _synthesize(edge_tts, text: str, output_path: Path, voice_name: str, speaking_rate: float | None) -> None:
    kwargs = {"text": text, "voice": voice_name}
    if speaking_rate is not None:
        kwargs["rate"] = _edge_rate(speaking_rate)
    communicate = edge_tts.Communicate(**kwargs)
    await communicate.save(str(output_path))


def _edge_rate(speaking_rate: float) -> str:
    percent = int(round((max(0.65, min(1.4, speaking_rate)) - 1) * 100))
    return "+0%" if percent == 0 else f"{percent:+d}%"
