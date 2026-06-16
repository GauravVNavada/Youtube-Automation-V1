from __future__ import annotations

from pathlib import Path


def build_image_slideshow_command(
    ffmpeg: str,
    image_paths: list[str],
    audio_path: str,
    ass_caption_path: str,
    output_path: str,
    duration_seconds: float,
    video_paths: list[str] | None = None,
    music_path: str | None = None,
    music_volume: float = 0.12,
    width: int = 1080,
    height: int = 1920,
    fps: int = 30,
    render_style: str = "natural",
) -> list[str]:
    """Build an FFmpeg command for hybrid video/image rendering with captions and audio."""
    media = _ordered_visual_media(image_paths, video_paths or [])
    if not media:
        raise ValueError("At least one visual media file is required for rendering")

    cmd = [ffmpeg, "-y"]
    n = len(media)
    xfade_duration = 0.5 if n > 1 else 0.0
    media_duration = max(1.0, (duration_seconds + xfade_duration * (n - 1)) / n)
    for kind, path in media:
        if kind == "video":
            cmd.extend(["-stream_loop", "-1", "-i", path])
        else:
            cmd.extend(["-loop", "1", "-t", f"{media_duration:.2f}", "-i", path])
    cmd.extend(["-i", audio_path])
    use_music = bool(music_path and Path(music_path).exists())
    if use_music:
        cmd.extend(["-i", str(music_path)])

    video_filters = []
    audio_filters = []
    for idx, (kind, _) in enumerate(media):
        if kind == "video":
            video_filters.append(
                f"[{idx}:v]scale={width}:{height}:force_original_aspect_ratio=increase,"
                f"crop={width}:{height},trim=duration={media_duration:.2f},"
                f"setpts=PTS-STARTPTS,fps={fps},settb=AVTB,setsar=1,format=yuv420p[v{idx}]"
            )
        else:
            zoom_expr = (
                "'min(zoom+0.003,1.25)'"
                if idx % 2 == 0
                else "'if(eq(on,1),1.25,max(zoom-0.003,1.0))'"
            )
            frame_count = max(1, int(media_duration * fps))
            video_filters.append(
                f"[{idx}:v]scale={width}:{height}:force_original_aspect_ratio=decrease,"
                f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,"
                f"zoompan=z={zoom_expr}:d={frame_count}:s={width}x{height}:fps={fps},"
                f"trim=duration={media_duration:.2f},setpts=PTS-STARTPTS,"
                f"fps={fps},settb=AVTB,setsar=1,{_image_style_filter(render_style, idx)}format=yuv420p[v{idx}]"
            )
    if n == 1:
        video_filters.append(f"[v0]trim=duration={duration_seconds:.2f},setpts=PTS-STARTPTS[vbase]")
    else:
        previous = "v0"
        for idx in range(1, n):
            offset = max(0.0, idx * (media_duration - xfade_duration))
            out_label = f"xf{idx}" if idx < n - 1 else "vbase"
            video_filters.append(
                f"[{previous}][v{idx}]xfade=transition=fade:"
                f"duration={xfade_duration:.2f}:offset={offset:.2f}[{out_label}]"
            )
            previous = out_label
    cap = _escape_ass_path(Path(ass_caption_path))
    video_filters.append(f"[vbase]ass='{cap}',format=yuv420p[vout]")

    narration_idx = n
    if use_music:
        music_idx = n + 1
        audio_filters.append(
            f"[{music_idx}:a]atrim=0:{duration_seconds:.2f},asetpts=PTS-STARTPTS,"
            f"volume={music_volume},afade=t=in:d=1.0,"
            f"afade=t=out:st={max(0.0, duration_seconds - 2.0):.2f}:d=2.0[bgm]"
        )
        audio_filters.append(
            f"[{narration_idx}:a][bgm]amix=inputs=2:duration=first:dropout_transition=2[aout]"
        )
        audio_map = "[aout]"
    else:
        audio_map = f"{narration_idx}:a"

    cmd.extend(["-filter_complex", ";".join(video_filters + audio_filters)])
    cmd.extend([
        "-map",
        "[vout]",
        "-map",
        audio_map,
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-profile:v",
        "baseline",
        "-level",
        "4.0",
        "-crf",
        "25",
        "-pix_fmt",
        "yuv420p",
        "-tag:v",
        "avc1",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-t",
        f"{duration_seconds:.3f}",
        "-movflags",
        "+faststart",
        output_path,
    ])
    return cmd


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


def _image_style_filter(render_style: str, index: int) -> str:
    style = (render_style or "natural").lower()
    if style in {"comic_book", "anime", "fantasy_concept", "sci_fi_concept", "illustration"}:
        contrast = "1.22" if style == "comic_book" else "1.14"
        saturation = "1.45" if style in {"comic_book", "anime"} else "1.25"
        border_alpha = "0.18" if index % 2 == 0 else "0.12"
        return (
            f"eq=contrast={contrast}:saturation={saturation}:brightness=0.02,"
            "unsharp=5:5:0.75:3:3:0.35,"
            f"drawbox=x=24:y=24:w=iw-48:h=ih-48:color=white@{border_alpha}:t=5,"
        )
    return ""


def _escape_ass_path(path: Path) -> str:
    return str(path.resolve()).replace("\\", "/").replace(":", "\\:")
