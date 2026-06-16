from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from modules.render.ffmpeg_builder import build_image_slideshow_command


def render_video(
    image_paths: list[str],
    audio_path: str,
    ass_caption_path: str,
    output_path: Path,
    duration_ms: int,
    video_paths: list[str] | None = None,
    music_path: str | None = None,
    width: int = 1080,
    height: int = 1920,
    fps: int = 30,
    music_volume: float = 0.12,
    render_style: str = "natural",
) -> dict:
    """Render final MP4 via FFmpeg and validate it with ffprobe."""
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if not ffmpeg:
        raise RuntimeError("ffmpeg is not installed or not in PATH")
    if not ffprobe:
        raise RuntimeError("ffprobe is not installed or not in PATH")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = output_path.with_suffix(".tmp.mp4")
    if tmp_path.exists():
        tmp_path.unlink()

    duration_seconds = max(1.0, duration_ms / 1000.0)
    cmd = build_image_slideshow_command(
        ffmpeg=ffmpeg,
        image_paths=image_paths,
        video_paths=video_paths or [],
        audio_path=audio_path,
        ass_caption_path=ass_caption_path,
        output_path=str(tmp_path),
        duration_seconds=duration_seconds,
        music_path=music_path,
        music_volume=music_volume,
        width=width,
        height=height,
        fps=fps,
        render_style=render_style,
    )
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"FFmpeg failed: {proc.stderr[-2000:]}")

    meta = probe_video(str(tmp_path), ffprobe)
    if int(meta["width"]) != width or int(meta["height"]) != height:
        raise RuntimeError(f"Unexpected video dimensions: {meta}")
    if output_path.exists():
        output_path.unlink()
    tmp_path.replace(output_path)
    extracted_audio = output_path.with_name("final_audio_check.wav")
    extract_audio_check(str(output_path), extracted_audio, ffmpeg)
    meta["video_path"] = str(output_path)
    meta["extracted_audio_path"] = str(extracted_audio)
    return meta


def probe_video(video_path: str, ffprobe: str | None = None) -> dict:
    ffprobe = ffprobe or shutil.which("ffprobe")
    if not ffprobe:
        raise RuntimeError("ffprobe is not installed or not in PATH")
    video_cmd = [
        ffprobe,
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=width,height,duration",
        "-of",
        "json",
        video_path,
    ]
    proc = subprocess.run(video_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {proc.stderr}")
    data = json.loads(proc.stdout)
    stream = data.get("streams", [{}])[0]
    audio = probe_audio(video_path, ffprobe)
    return {
        "width": int(stream.get("width", 0)),
        "height": int(stream.get("height", 0)),
        "duration_seconds": float(stream.get("duration", 0.0) or 0.0),
        **audio,
    }


def probe_audio(video_path: str, ffprobe: str) -> dict:
    cmd = [
        ffprobe,
        "-v",
        "error",
        "-select_streams",
        "a:0",
        "-show_entries",
        "stream=codec_name,sample_rate,channels,duration",
        "-of",
        "json",
        video_path,
    ]
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"audio ffprobe failed: {proc.stderr}")
    streams = json.loads(proc.stdout).get("streams", [])
    if not streams:
        raise RuntimeError("Rendered video is missing an audio stream")
    stream = streams[0]
    return {
        "audio_codec": str(stream.get("codec_name", "")),
        "audio_sample_rate": int(stream.get("sample_rate", 0) or 0),
        "audio_channels": int(stream.get("channels", 0) or 0),
        "audio_duration_seconds": float(stream.get("duration", 0.0) or 0.0),
    }


def extract_audio_check(video_path: str, output_path: Path, ffmpeg: str) -> None:
    proc = subprocess.run(
        [
            ffmpeg,
            "-y",
            "-i",
            video_path,
            "-vn",
            "-acodec",
            "pcm_s16le",
            "-ar",
            "44100",
            "-ac",
            "2",
            str(output_path),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"Could not extract rendered audio check: {proc.stderr[-1000:]}")
