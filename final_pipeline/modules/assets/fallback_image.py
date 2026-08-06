from __future__ import annotations

import hashlib
from pathlib import Path

from PIL import Image, ImageDraw


def create_fallback_image(
    query: str,
    output_path: Path,
    color: tuple[int, int, int] = (22, 24, 28),
    width: int = 1080,
    height: int = 1920,
) -> str:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    seed = int(hashlib.md5(query.encode("utf-8")).hexdigest()[:6], 16)
    accent = (
        min(255, color[0] + seed % 80),
        min(255, color[1] + seed // 11 % 80),
        min(255, color[2] + seed // 23 % 80),
    )
    image = Image.new("RGB", (width, height), color)
    draw = ImageDraw.Draw(image)
    for y in range(height):
        blend = y / height
        line = tuple(int(color[i] * (1 - blend) + accent[i] * blend) for i in range(3))
        draw.line([(0, y), (width, y)], fill=line)
    for index, line in enumerate(_wrap(query.upper(), 18)[:4]):
        draw.text((80, 760 + index * 90), line, fill=(245, 245, 245))
    image.save(output_path, quality=92)
    return str(output_path)


def _wrap(text: str, max_chars: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current: list[str] = []
    for word in words:
        trial = " ".join(current + [word])
        if len(trial) <= max_chars:
            current.append(word)
        else:
            if current:
                lines.append(" ".join(current))
            current = [word[:max_chars]]
    if current:
        lines.append(" ".join(current))
    return lines or ["VISUAL"]
