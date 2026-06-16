from __future__ import annotations

from pathlib import Path
import shutil

from app.schemas import ThumbnailOutput


def create_thumbnail_set(
    video_path: str,
    image_paths: list[str],
    output_dir: Path,
    title: str,
    hook_line: str,
    profile=None,
    selected_angle: str = "",
    facts: list[str] | None = None,
) -> ThumbnailOutput:
    output_dir.mkdir(parents=True, exist_ok=True)
    source = _first_existing(image_paths) or ""
    shorts = output_dir / "shorts_cover.jpg"
    youtube = output_dir / "youtube_thumbnail.jpg"
    if source:
        shutil.copyfile(source, shorts)
        shutil.copyfile(source, youtube)
    else:
        shorts.write_bytes(_minimal_jpeg())
        youtube.write_bytes(_minimal_jpeg())
    lines = _thumbnail_lines(title, hook_line, selected_angle)
    return ThumbnailOutput(str(shorts), str(youtube), source, lines)


def _first_existing(paths: list[str]) -> str:
    for path in paths:
        if Path(path).exists():
            return path
    return ""


def _thumbnail_lines(title: str, hook_line: str, selected_angle: str) -> list[str]:
    text = selected_angle or title or hook_line
    words = [word.strip(".,!?") for word in text.split() if word.strip(".,!?")]
    return [" ".join(words[:3]).upper() or "REAL STORY"]


def _minimal_jpeg() -> bytes:
    return bytes.fromhex("ffd8ffe000104a46494600010101006000600000ffdb004300080606070605080707070909080a0c140d0c0b0b0c1912130f141d1a1f1e1d1a1c1c20242e2720222c231c1c2837292c30313434341f27393d38323c2e333432ffc0000b080001000101011100ffc4001400010000000000000000000000000000000000000008ffc40014100100000000000000000000000000000000000000ffda0008010100003f00d2cf20ffd9")
