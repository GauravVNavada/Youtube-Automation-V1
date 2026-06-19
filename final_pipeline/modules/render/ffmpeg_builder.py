from __future__ import annotations

from pathlib import Path


IMAGE_FADE_SECONDS = 0.22


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
        video_filters.extend(
            _image_segment_filters(
                input_label=f"{idx}:v",
                output_label=f"v{idx}",
                segment_duration=image_duration,
                width=width,
                height=height,
                fps=fps,
                zoom_expr=zoom_expr,
                index=idx,
                total=n,
            )
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


def build_media_timeline_command(
    ffmpeg: str,
    media_paths: list[str],
    media_types: list[str],
    audio_path: str,
    ass_caption_path: str,
    output_path: str,
    duration_seconds: float,
    music_path: str | None = None,
    music_volume: float = 0.12,
    width: int = 1080,
    height: int = 1920,
    fps: int = 30,
    media_durations_ms: list[int] | None = None,
) -> list[str]:
    """Build an FFmpeg command for a mixed image/video vertical timeline."""
    if not media_paths:
        raise ValueError("At least one media asset is required for rendering")
    if len(media_types) != len(media_paths):
        raise ValueError("media_types must match media_paths")

    normalized_types = [item if item in {"image", "video"} else "image" for item in media_types]
    cmd = [ffmpeg, "-y"]
    n = len(media_paths)
    explicit_durations = bool(media_durations_ms and len(media_durations_ms) == n)
    segment_durations = _segment_durations(
        n=n,
        duration_seconds=duration_seconds,
        media_durations_ms=media_durations_ms if explicit_durations else None,
    )
    xfade_duration = 0.0 if explicit_durations else (0.35 if n > 1 else 0.0)
    for path, media_type, segment_duration in zip(media_paths, normalized_types, segment_durations):
        if media_type == "video":
            cmd.extend(["-stream_loop", "-1", "-t", f"{segment_duration:.2f}", "-i", path])
        else:
            cmd.extend(["-loop", "1", "-t", f"{segment_duration:.2f}", "-i", path])
    cmd.extend(["-i", audio_path])
    use_music = bool(music_path and Path(music_path).exists())
    if use_music:
        cmd.extend(["-i", str(music_path)])

    video_filters = []
    audio_filters = []
    for idx, media_type in enumerate(normalized_types):
        segment_duration = segment_durations[idx]
        if media_type == "video":
            video_filters.append(
                f"[{idx}:v]scale={width}:{height}:force_original_aspect_ratio=increase,"
                f"crop={width}:{height},setsar=1,"
                f"trim=duration={segment_duration:.2f},setpts=PTS-STARTPTS,"
                f"fps={fps},settb=AVTB,"
                f"format=yuv420p[v{idx}]"
            )
        else:
            zoom_expr = (
                "'min(zoom+0.003,1.22)'"
                if idx % 2 == 0
                else "'if(eq(on,1),1.18,max(zoom-0.003,1.0))'"
            )
            video_filters.extend(
                _image_segment_filters(
                    input_label=f"{idx}:v",
                    output_label=f"v{idx}",
                    segment_duration=segment_duration,
                    width=width,
                    height=height,
                    fps=fps,
                    zoom_expr=zoom_expr,
                    index=idx,
                    total=n,
                    timeline=True,
                )
            )

    if n == 1:
        video_filters.append(f"[v0]trim=duration={duration_seconds:.2f},setpts=PTS-STARTPTS[vbase]")
    elif explicit_durations:
        video_filters.append(
            "".join(f"[v{idx}]" for idx in range(n))
            + f"concat=n={n}:v=1:a=0,trim=duration={duration_seconds:.2f},setpts=PTS-STARTPTS[vbase]"
        )
    else:
        previous = "v0"
        for idx in range(1, n):
            segment_duration = segment_durations[idx]
            offset = max(0.0, idx * (segment_duration - xfade_duration))
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


def _segment_durations(
    *,
    n: int,
    duration_seconds: float,
    media_durations_ms: list[int] | None,
) -> list[float]:
    if media_durations_ms and len(media_durations_ms) == n:
        durations = [max(0.1, int(duration_ms) / 1000.0) for duration_ms in media_durations_ms]
        delta = duration_seconds - sum(durations)
        if durations and abs(delta) > 0.01:
            durations[-1] = max(0.1, durations[-1] + delta)
        return durations
    xfade_duration = 0.35 if n > 1 else 0.0
    duration = max(1.2, (duration_seconds + xfade_duration * (n - 1)) / n)
    return [duration for _ in range(n)]


def _image_segment_filters(
    *,
    input_label: str,
    output_label: str,
    segment_duration: float,
    width: int,
    height: int,
    fps: int,
    zoom_expr: str,
    index: int,
    total: int,
    timeline: bool = False,
) -> list[str]:
    frame_count = max(1, int(segment_duration * fps))
    bg = f"bg{index}"
    fg = f"fg{index}"
    bg_src = f"bgsrc{index}"
    fg_src = f"fgsrc{index}"
    fade = _fade_filters(segment_duration, index=index, total=total)
    timing = f"fps={fps},settb=AVTB," if timeline else ""
    return [
        f"[{input_label}]split=2[{bg_src}][{fg_src}]",
        f"[{bg_src}]scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height},gblur=sigma=28,eq=brightness=-0.06:saturation=1.18,"
        f"setsar=1[{bg}]",
        f"[{fg_src}]scale={width}:{height}:force_original_aspect_ratio=decrease,setsar=1[{fg}]",
        f"[{bg}][{fg}]overlay=(W-w)/2:(H-h)/2,"
        f"zoompan=z={zoom_expr}:d={frame_count}:s={width}x{height}:fps={fps},"
        f"trim=duration={segment_duration:.2f},setpts=PTS-STARTPTS,{timing}"
        f"{fade}format=yuv420p[{output_label}]",
    ]


def _fade_filters(segment_duration: float, *, index: int, total: int) -> str:
    if total <= 1:
        return ""
    fade_duration = min(IMAGE_FADE_SECONDS, max(0.0, segment_duration / 4.0))
    if fade_duration <= 0.01:
        return ""
    filters = []
    if index > 0:
        filters.append(f"fade=t=in:st=0:d={fade_duration:.2f}")
    if index + 1 < total:
        start = max(0.0, segment_duration - fade_duration)
        filters.append(f"fade=t=out:st={start:.2f}:d={fade_duration:.2f}")
    return "".join(f"{item}," for item in filters)


def _escape_ass_path(path: Path) -> str:
    return str(path.resolve()).replace("\\", "/").replace(":", "\\:")
