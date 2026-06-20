from __future__ import annotations

from pathlib import Path


STILL_IMAGE_SUPERSAMPLE = 2
STABLE_ZOOMPAN_X = "'trunc((iw-iw/zoom)/4)*2'"
STABLE_ZOOMPAN_Y = "'trunc((ih-ih/zoom)/4)*2'"


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
    visual_motion: bool = True,
    transition_style: str = "slide",
    transition_seconds: float | None = None,
    zoom_variant: str = "mixed",
) -> list[str]:
    """Build an FFmpeg command for image slideshow rendering with captions and audio."""
    if not image_paths:
        raise ValueError("At least one image is required for rendering")

    cmd = [ffmpeg, "-y"]
    n = len(image_paths)
    image_duration = max(0.25, duration_seconds / n)
    segment_durations = [image_duration for _ in image_paths]
    transition_style = _normalize_transition_style(transition_style)
    transition_duration = _transition_duration(segment_durations, fps, transition_seconds, transition_style)
    render_durations = _render_durations_for_transitions(segment_durations, transition_duration)
    for image, render_duration in zip(image_paths, render_durations):
        cmd.extend(["-f", "image2", "-loop", "1", "-t", f"{render_duration:.2f}", "-i", image])
    cmd.extend(["-i", audio_path])
    use_music = bool(music_path and Path(music_path).exists())
    if use_music:
        cmd.extend(["-i", str(music_path)])

    video_filters = []
    audio_filters = []
    for idx, _ in enumerate(image_paths):
        frame_count = _frame_count(render_durations[idx], fps)
        zoom_expr = _image_motion_expr(
            idx,
            visual_motion,
            zoom_variant,
            max_zoom=1.25,
            frame_count=frame_count,
        )
        video_filters.extend(
            _image_segment_filters(
                input_label=f"{idx}:v",
                output_label=f"v{idx}",
                segment_duration=render_durations[idx],
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
        video_filters.extend(_join_segment_filters(n, segment_durations, duration_seconds, transition_duration, transition_style))
    cap = _escape_ass_path(Path(ass_caption_path))
    video_filters.append(f"[vbase]ass='{cap}'[vout]")

    narration_idx = n
    if use_music:
        music_idx = n + 1
        audio_filters.extend(_mixed_audio_filters(narration_idx, music_idx, duration_seconds, music_volume))
        audio_map = "[aout]"
    else:
        audio_filters.append(_narration_audio_filter(narration_idx))
        audio_map = "[aout]"

    cmd.extend(["-filter_complex", ";".join(video_filters + audio_filters)])
    cmd.extend([
        "-map",
        "[vout]",
        "-map",
        audio_map,
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "21",
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
    visual_motion: bool = True,
    transition_style: str = "slide",
    transition_seconds: float | None = None,
    zoom_variant: str = "mixed",
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
    transition_style = _normalize_transition_style(transition_style)
    transition_duration = _transition_duration(segment_durations, fps, transition_seconds, transition_style)
    render_durations = _render_durations_for_transitions(segment_durations, transition_duration)
    for path, media_type, render_duration in zip(media_paths, normalized_types, render_durations):
        if media_type == "video":
            cmd.extend(["-stream_loop", "-1", "-t", f"{render_duration:.2f}", "-i", path])
        else:
            cmd.extend(["-f", "image2", "-loop", "1", "-t", f"{render_duration:.2f}", "-i", path])
    cmd.extend(["-i", audio_path])
    use_music = bool(music_path and Path(music_path).exists())
    if use_music:
        cmd.extend(["-i", str(music_path)])

    video_filters = []
    audio_filters = []
    for idx, media_type in enumerate(normalized_types):
        segment_duration = segment_durations[idx]
        render_duration = render_durations[idx]
        if media_type == "video":
            video_filters.append(
                f"[{idx}:v]scale={width}:{height}:force_original_aspect_ratio=increase,"
                f"crop={width}:{height},setsar=1,"
                f"trim=duration={render_duration:.2f},setpts=PTS-STARTPTS,"
                f"fps={fps},settb=AVTB,"
                f"format=yuv420p[v{idx}]"
            )
        else:
            frame_count = _frame_count(render_duration, fps)
            zoom_expr = _image_motion_expr(
                idx,
                visual_motion,
                zoom_variant,
                max_zoom=1.22,
                alt_max_zoom=1.18,
                frame_count=frame_count,
            )
            video_filters.extend(
                _image_segment_filters(
                    input_label=f"{idx}:v",
                    output_label=f"v{idx}",
                    segment_duration=render_duration,
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
    else:
        video_filters.extend(_join_segment_filters(n, segment_durations, duration_seconds, transition_duration, transition_style))

    cap = _escape_ass_path(Path(ass_caption_path))
    video_filters.append(f"[vbase]ass='{cap}'[vout]")

    narration_idx = n
    if use_music:
        music_idx = n + 1
        audio_filters.extend(_mixed_audio_filters(narration_idx, music_idx, duration_seconds, music_volume))
        audio_map = "[aout]"
    else:
        audio_filters.append(_narration_audio_filter(narration_idx))
        audio_map = "[aout]"

    cmd.extend(["-filter_complex", ";".join(video_filters + audio_filters)])
    cmd.extend([
        "-map",
        "[vout]",
        "-map",
        audio_map,
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "21",
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
    duration = max(0.25, duration_seconds / n)
    return [duration for _ in range(n)]


def _transition_duration(
    segment_durations: list[float],
    fps: int,
    transition_seconds: float | None,
    transition_style: str,
) -> float:
    if len(segment_durations) < 2 or transition_style == "cut":
        return 0.0
    shortest = min(segment_durations)
    if transition_seconds is None:
        duration = min(0.45, shortest * 0.4)
    else:
        duration = max(0.0, float(transition_seconds))
        duration = min(duration, shortest * 0.45)
    minimum = max(2.0 / max(1, fps), 0.08)
    return duration if duration >= minimum else 0.0


def _render_durations_for_transitions(segment_durations: list[float], transition_duration: float) -> list[float]:
    if transition_duration <= 0:
        return list(segment_durations)
    return [
        duration + transition_duration if index < len(segment_durations) - 1 else duration
        for index, duration in enumerate(segment_durations)
    ]


def _join_segment_filters(
    n: int,
    segment_durations: list[float],
    duration_seconds: float,
    transition_duration: float,
    transition_style: str = "slide",
) -> list[str]:
    if transition_duration <= 0:
        return [
            "".join(f"[v{idx}]" for idx in range(n))
            + f"concat=n={n}:v=1:a=0,trim=duration={duration_seconds:.2f},setpts=PTS-STARTPTS[vbase]"
        ]

    filters: list[str] = []
    current = "v0"
    elapsed = segment_durations[0]
    for idx in range(1, n):
        out = f"vx{idx}"
        transition = _xfade_transition(idx, transition_style)
        filters.append(
            f"[{current}][v{idx}]xfade=transition={transition}:duration={transition_duration:.2f}:"
            f"offset={elapsed:.2f}[{out}]"
        )
        current = out
        elapsed += segment_durations[idx]
    filters.append(f"[{current}]trim=duration={duration_seconds:.2f},setpts=PTS-STARTPTS[vbase]")
    return filters


def _image_motion_expr(
    index: int,
    visual_motion: bool,
    zoom_variant: str,
    *,
    max_zoom: float,
    frame_count: int,
    alt_max_zoom: float | None = None,
) -> str:
    variant = _normalize_zoom_variant(zoom_variant)
    if not visual_motion or variant == "still":
        return "'1'"
    denominator = max(1, frame_count - 1)
    if variant == "center_in" or (variant == "mixed" and index % 2 == 0):
        return f"'min({max_zoom:.4f},1+({max_zoom:.4f}-1)*on/{denominator})'"
    start_zoom = alt_max_zoom if alt_max_zoom is not None else max_zoom
    return f"'max(1,{start_zoom:.4f}-({start_zoom:.4f}-1)*on/{denominator})'"


def _normalize_zoom_variant(value: str) -> str:
    variant = str(value or "mixed").strip().lower()
    aliases = {
        "mixed": "mixed",
        "alternate": "mixed",
        "center": "mixed",
        "center_in": "center_in",
        "in": "center_in",
        "zoom_in": "center_in",
        "center_out": "center_out",
        "out": "center_out",
        "zoom_out": "center_out",
        "still": "still",
        "none": "still",
        "off": "still",
    }
    return aliases.get(variant, "mixed")


def _normalize_transition_style(value: str) -> str:
    style = str(value or "slide").strip().lower()
    aliases = {
        "slides": "slide",
        "slide": "slide",
        "fade": "fade",
        "wipe": "wipe",
        "cut": "cut",
        "none": "cut",
        "off": "cut",
    }
    return aliases.get(style, "slide")


def _xfade_transition(index: int, transition_style: str) -> str:
    if transition_style == "fade":
        return "fade"
    if transition_style == "wipe":
        transitions = ("wipeleft", "wiperight", "wipeup", "wipedown")
        return transitions[(index - 1) % len(transitions)]
    transitions = ("slideleft", "slideright", "slideup", "slidedown")
    return transitions[(index - 1) % len(transitions)]


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
    frame_count = _frame_count(segment_duration, fps)
    render_width = width * STILL_IMAGE_SUPERSAMPLE
    render_height = height * STILL_IMAGE_SUPERSAMPLE
    bg = f"bg{index}"
    fg = f"fg{index}"
    bg_src = f"bgsrc{index}"
    fg_src = f"fgsrc{index}"
    comp = f"comp{index}"
    timing = f"fps={fps},settb=AVTB," if timeline else ""
    return [
        f"[{input_label}]split=2[{bg_src}][{fg_src}]",
        f"[{bg_src}]scale={render_width}:{render_height}:force_original_aspect_ratio=increase:flags=lanczos,"
        f"crop={render_width}:{render_height},gblur=sigma=24,eq=brightness=-0.04:saturation=1.08,"
        f"setsar=1[{bg}]",
        f"[{fg_src}]scale={render_width}:{render_height}:force_original_aspect_ratio=decrease:flags=lanczos,"
        f"setsar=1[{fg}]",
        f"[{bg}][{fg}]overlay=(W-w)/2:(H-h)/2,"
        f"trim=end_frame=1,setpts=PTS-STARTPTS[{comp}]",
        f"[{comp}]zoompan=z={zoom_expr}:x={STABLE_ZOOMPAN_X}:y={STABLE_ZOOMPAN_Y}:"
        f"d={frame_count}:s={render_width}x{render_height}:fps={fps},"
        f"trim=duration={segment_duration:.2f},setpts=PTS-STARTPTS,{timing}"
        f"scale={width}:{height}:flags=lanczos,setsar=1,"
        f"format=yuv420p[{output_label}]",
    ]


def _frame_count(segment_duration: float, fps: int) -> int:
    return max(1, int(segment_duration * fps))


def _narration_audio_filter(narration_idx: int) -> str:
    return f"[{narration_idx}:a]aresample=44100,alimiter=limit=0.89:level=disabled[aout]"


def _mixed_audio_filters(
    narration_idx: int,
    music_idx: int,
    duration_seconds: float,
    music_volume: float,
) -> list[str]:
    music_gain = max(0.0, min(0.8, music_volume))
    return [
        f"[{music_idx}:a]atrim=0:{duration_seconds:.2f},asetpts=PTS-STARTPTS,"
        f"volume={music_gain},afade=t=in:d=1.0,"
        f"afade=t=out:st={max(0.0, duration_seconds - 2.0):.2f}:d=2.0[bgm]",
        f"[{narration_idx}:a][bgm]amix=inputs=2:duration=first:dropout_transition=0:"
        "normalize=0:weights='1 1',alimiter=limit=0.89:level=disabled[aout]",
    ]


def _escape_ass_path(path: Path) -> str:
    return str(path.resolve()).replace("\\", "/").replace(":", "\\:")
