from __future__ import annotations

import json
from pathlib import Path

from app.logger import to_jsonable
from app.schemas import AssetBundle, AudioBundle, CaptionBundle


def write_render_plan(
    *,
    assets: AssetBundle,
    audio: AudioBundle,
    captions: CaptionBundle,
    output_path: Path,
    plan_path: Path,
    music_volume: float,
    width: int = 1080,
    height: int = 1920,
    fps: int = 30,
    render_style: str = "natural",
) -> str:
    plan = build_render_plan(
        assets=assets,
        audio=audio,
        captions=captions,
        output_path=output_path,
        music_volume=music_volume,
        width=width,
        height=height,
        fps=fps,
        render_style=render_style,
    )
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    plan_path.write_text(json.dumps(to_jsonable(plan), indent=2, ensure_ascii=True), encoding="utf-8")
    return str(plan_path)


def build_render_plan(
    *,
    assets: AssetBundle,
    audio: AudioBundle,
    captions: CaptionBundle,
    output_path: Path,
    music_volume: float,
    width: int = 1080,
    height: int = 1920,
    fps: int = 30,
    render_style: str = "natural",
) -> dict:
    media = _ordered_visual_media(assets.image_paths, assets.video_paths)
    return {
        "renderer": "ffmpeg",
        "render_style": render_style,
        "asset_strategy": assets.asset_strategy,
        "output_path": str(output_path),
        "dimensions": {"width": width, "height": height, "fps": fps},
        "duration_ms": audio.duration_ms,
        "visual_media": [
            {
                "index": index,
                "kind": kind,
                "path": path,
                "image_source": assets.sources[index] if index < len(assets.sources) else "",
                "video_source": assets.video_sources[index] if index < len(assets.video_sources) else "",
                "visual_style": assets.visual_style,
            }
            for index, (kind, path) in enumerate(media)
        ],
        "audio": {
            "provider": audio.provider,
            "path": audio.final_audio_path,
            "alignment_source": audio.alignment_source,
            "word_count": len(audio.word_timestamps),
        },
        "captions": {
            "srt_path": captions.srt_path,
            "ass_path": captions.ass_path,
            "phrase_count": captions.phrase_count,
        },
        "music": {
            "path": assets.music_path,
            "volume": music_volume,
        },
    }


def _ordered_visual_media(image_paths: list[str], video_paths: list[str]) -> list[tuple[str, str]]:
    media: list[tuple[str, str]] = []
    total = max(len(image_paths), len(video_paths))
    seen_videos: set[str] = set()
    for index in range(total):
        video = video_paths[index] if index < len(video_paths) else ""
        image = image_paths[index] if index < len(image_paths) else ""
        if video and Path(video).exists():
            key = _media_identity(video)
            if key not in seen_videos:
                seen_videos.add(key)
                media.append(("video", video))
                continue
        if image and Path(image).exists():
            media.append(("image", image))
    return media


def _media_identity(path: str) -> str:
    media_path = Path(path)
    try:
        return f"{media_path.resolve()}:{media_path.stat().st_size}"
    except OSError:
        return str(media_path)
