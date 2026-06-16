from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps

from app.schemas import NicheProfile, ThumbnailOutput


SHORTS_SIZE = (1080, 1920)
YOUTUBE_SIZE = (1280, 720)


def create_thumbnail_set(
    *,
    video_path: str,
    image_paths: list[str],
    output_dir: Path,
    title: str,
    hook_line: str,
    profile: NicheProfile,
    selected_angle: str = "",
    facts: list[str] | None = None,
) -> ThumbnailOutput:
    output_dir.mkdir(parents=True, exist_ok=True)
    frame_path = output_dir / "source_frame.jpg"
    source_path = _extract_video_frame(video_path, frame_path) or _first_existing_image(image_paths)
    text_lines = _thumbnail_text(title, hook_line, selected_angle, profile, facts or [])

    shorts_path = output_dir / "shorts_cover.jpg"
    youtube_path = output_dir / "youtube_thumb.jpg"
    source_image = _load_source_image(source_path)
    _render_thumbnail(source_image, SHORTS_SIZE, text_lines, shorts_path, profile, vertical=True)
    _render_thumbnail(source_image, YOUTUBE_SIZE, text_lines, youtube_path, profile, vertical=False)
    return ThumbnailOutput(
        shorts_cover_path=str(shorts_path),
        youtube_thumbnail_path=str(youtube_path),
        source_image_path=str(source_path or ""),
        text_lines=text_lines,
    )


def _extract_video_frame(video_path: str, output_path: Path) -> str:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg or not video_path or not Path(video_path).exists():
        return ""
    proc = subprocess.run(
        [
            ffmpeg,
            "-y",
            "-ss",
            "00:00:01",
            "-i",
            video_path,
            "-frames:v",
            "1",
            str(output_path),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if proc.returncode != 0 or not output_path.exists() or output_path.stat().st_size < 1024:
        return ""
    return str(output_path)


def _first_existing_image(image_paths: list[str]) -> str:
    for path in image_paths:
        if path and Path(path).exists():
            return path
    return ""


def _load_source_image(source_path: str) -> Image.Image:
    if source_path:
        try:
            return Image.open(source_path).convert("RGB")
        except Exception:
            pass
    return _fallback_image()


def _fallback_image() -> Image.Image:
    width, height = SHORTS_SIZE
    image = Image.new("RGB", SHORTS_SIZE, "#17202a")
    draw = ImageDraw.Draw(image)
    for y in range(height):
        shade = int(28 + 70 * (y / height))
        draw.line([(0, y), (width, y)], fill=(shade, 42, 58))
    return image


def _render_thumbnail(
    source: Image.Image,
    size: tuple[int, int],
    text_lines: list[str],
    output_path: Path,
    profile: NicheProfile,
    vertical: bool,
) -> None:
    canvas = ImageOps.fit(source, size, method=Image.Resampling.LANCZOS, centering=(0.5, 0.45))
    canvas = ImageEnhance.Contrast(canvas).enhance(1.1)
    canvas = ImageEnhance.Color(canvas).enhance(0.9)
    overlay = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    _draw_shadow_panel(draw, size, vertical)
    canvas = Image.alpha_composite(canvas.convert("RGBA"), overlay)
    draw = ImageDraw.Draw(canvas)

    max_width = int(size[0] * (0.82 if vertical else 0.58))
    base_size = int(size[0] * (0.118 if vertical else 0.083))
    font = _font(base_size)
    small_font = _font(max(34, int(base_size * 0.48)))
    wrapped = _wrap_lines(text_lines, draw, font, max_width, max_lines=3)
    total_height = len(wrapped) * int(base_size * 1.15)
    x = int(size[0] * 0.08)
    y = int(size[1] * (0.59 if vertical else 0.50)) - total_height // 2
    accent = _accent_color(profile.genre_id)
    for line in wrapped:
        draw.text((x, y), line.upper(), font=font, fill="white", stroke_width=max(2, base_size // 18), stroke_fill="black")
        y += int(base_size * 1.05)

    tag = _tagline(profile)
    if tag:
        draw.rounded_rectangle(
            [x, y + 18, x + int(size[0] * 0.42), y + 18 + int(base_size * 0.45)],
            radius=10,
            fill=accent,
        )
        draw.text((x + 18, y + 21), tag.upper(), font=small_font, fill="black")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.convert("RGB").save(output_path, "JPEG", quality=92, optimize=True)


def _draw_shadow_panel(draw: ImageDraw.ImageDraw, size: tuple[int, int], vertical: bool) -> None:
    width, height = size
    if vertical:
        draw.rectangle([0, int(height * 0.46), width, height], fill=(0, 0, 0, 138))
        draw.rectangle([0, 0, width, int(height * 0.18)], fill=(0, 0, 0, 70))
    else:
        draw.rectangle([0, 0, int(width * 0.68), height], fill=(0, 0, 0, 128))


def _thumbnail_text(
    title: str,
    hook_line: str,
    selected_angle: str,
    profile: NicheProfile,
    facts: list[str],
) -> list[str]:
    candidates = [
        _short_phrase(selected_angle),
        _short_phrase(title),
        _short_phrase(hook_line),
        _short_phrase(facts[0] if facts else ""),
    ]
    for candidate in candidates:
        if candidate:
            words = candidate.split()[:5]
            if len(words) >= 2:
                return [" ".join(words)]
    fallback = profile.title_words[:3] or [profile.display_name]
    return [" ".join(fallback[:4])]


def _short_phrase(text: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9\s']", " ", text or "")
    cleaned = " ".join(word for word in cleaned.split() if len(word) > 1)
    blocked = {"youtube", "shorts", "story", "stories", "video"}
    words = [word for word in cleaned.split() if word.lower() not in blocked]
    return " ".join(words[:6])


def _wrap_lines(
    lines: list[str],
    draw: ImageDraw.ImageDraw,
    font: ImageFont.ImageFont,
    max_width: int,
    max_lines: int,
) -> list[str]:
    words = " ".join(lines).split()
    wrapped: list[str] = []
    current: list[str] = []
    for word in words:
        candidate = " ".join([*current, word])
        if _text_width(draw, candidate, font) <= max_width or not current:
            current.append(word)
        else:
            wrapped.append(" ".join(current))
            current = [word]
        if len(wrapped) >= max_lines:
            break
    if current and len(wrapped) < max_lines:
        wrapped.append(" ".join(current))
    return wrapped or ["NEW SHORT"]


def _text_width(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> int:
    bbox = draw.textbbox((0, 0), text, font=font, stroke_width=2)
    return bbox[2] - bbox[0]


def _font(size: int) -> ImageFont.ImageFont:
    for path in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
    ):
        if Path(path).exists():
            return ImageFont.truetype(path, size=size)
    return ImageFont.load_default()


def _accent_color(genre_id: str) -> tuple[int, int, int, int]:
    colors = {
        "scary_stories": (255, 61, 61, 238),
        "reddit_stories": (255, 192, 46, 238),
        "history_facts": (239, 201, 117, 238),
        "science_facts": (96, 214, 190, 238),
        "mystery_stories": (161, 215, 255, 238),
        "motivational_stories": (255, 226, 94, 238),
        "relationship_stories": (255, 132, 160, 238),
    }
    return colors.get(genre_id, (255, 215, 94, 238))


def _tagline(profile: NicheProfile) -> str:
    if profile.hashtag_hints:
        return profile.hashtag_hints[0].replace("#", "")
    return profile.display_name

