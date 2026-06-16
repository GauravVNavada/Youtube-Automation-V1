from __future__ import annotations

from pathlib import Path


def build_image_slideshow_command(
    ffmpeg: str,
    image_paths: list[str],
    audio_path: str,
    ass_caption_path: str,
    output_path: str,
    duration_seconds: float,
    music_path: str | None = None,
    music_volume: float = 0.12,
    width: int = 1080,
    height: int = 1920,
    fps: int = 30,
) -> list[str]:
    """Build an FFmpeg command for image slideshow rendering with captions and audio."""
    if not image_paths:
        raise ValueError("At least one image is required for rendering")

    cmd = [ffmpeg, "-y"]
    n = len(image_paths)
    xfade_duration = 0.5 if n > 1 else 0.0
    image_duration = max(1.0, (duration_seconds + xfade_duration * (n - 1)) / n)
    for image in image_paths:
        cmd.extend(["-loop", "1", "-t", f"{image_duration:.2f}", "-i", image])
    cmd.extend(["-i", audio_path])
    use_music = bool(music_path and Path(music_path).exists())
    if use_music:
        cmd.extend(["-i", str(music_path)])

    video_filters = []
    audio_filters = []
    for idx, _ in enumerate(image_paths):
        zoom_expr = (
            "'min(zoom+0.003,1.25)'"
            if idx % 2 == 0
            else "'if(eq(on,1),1.25,max(zoom-0.003,1.0))'"
        )
        frame_count = max(1, int(image_duration * fps))
        video_filters.append(
            f"[{idx}:v]scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,"
            f"zoompan=z={zoom_expr}:d={frame_count}:s={width}x{height}:fps={fps},"
            f"format=yuv420p[v{idx}]"
        )
    if n == 1:
        video_filters.append(f"[v0]trim=duration={duration_seconds:.2f},setpts=PTS-STARTPTS[vbase]")
    else:
        previous = "v0"
        for idx in range(1, n):
            offset = max(0.0, idx * (image_duration - xfade_duration))
            out_label = f"xf{idx}" if idx < n - 1 else "vbase"
            video_filters.append(
                f"[{previous}][v{idx}]xfade=transition=fade:"
                f"duration={xfade_duration:.2f}:offset={offset:.2f}[{out_label}]"
            )
            previous = out_label
    cap = _escape_ass_path(Path(ass_caption_path))
    video_filters.append(f"[vbase]ass='{cap}'[vout]")

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
        "-crf",
        "25",
        "-pix_fmt",
        "yuv420p",
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


def _escape_ass_path(path: Path) -> str:
    return str(path.resolve()).replace("\\", "/").replace(":", "\\:")
