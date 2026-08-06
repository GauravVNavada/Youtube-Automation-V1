from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AudioQuality:
    mean_volume_db: float | None = None
    max_volume_db: float | None = None
    longest_silence_seconds: float = 0.0


def probe_audio_duration_ms(audio_path: str | Path) -> int | None:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return None
    proc = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "json",
            str(audio_path),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if proc.returncode != 0:
        return None
    duration = json.loads(proc.stdout or "{}").get("format", {}).get("duration")
    if not duration:
        return None
    return max(0, int(float(duration) * 1000))


def analyze_audio_quality(audio_path: str | Path) -> AudioQuality:
    mean_volume, max_volume = _detect_volume(audio_path)
    longest_silence = _detect_longest_silence(audio_path)
    return AudioQuality(
        mean_volume_db=mean_volume,
        max_volume_db=max_volume,
        longest_silence_seconds=longest_silence,
    )


def _detect_volume(audio_path: str | Path) -> tuple[float | None, float | None]:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return None, None
    proc = subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-i",
            str(audio_path),
            "-af",
            "volumedetect",
            "-f",
            "null",
            "/dev/null",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if proc.returncode != 0:
        return None, None
    mean_match = re.search(r"mean_volume:\s*(-?\d+(?:\.\d+)?) dB", proc.stderr)
    max_match = re.search(r"max_volume:\s*(-?\d+(?:\.\d+)?) dB", proc.stderr)
    return (
        float(mean_match.group(1)) if mean_match else None,
        float(max_match.group(1)) if max_match else None,
    )


def _detect_longest_silence(audio_path: str | Path) -> float:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return 0.0
    proc = subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-i",
            str(audio_path),
            "-af",
            "silencedetect=noise=-35dB:d=0.35",
            "-f",
            "null",
            "/dev/null",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if proc.returncode != 0:
        return 0.0
    durations = [
        float(match)
        for match in re.findall(r"silence_duration:\s*(\d+(?:\.\d+)?)", proc.stderr)
    ]
    return max(durations, default=0.0)
