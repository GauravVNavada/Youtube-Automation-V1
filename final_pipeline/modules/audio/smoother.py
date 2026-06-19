from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


SMOOTH_SPEECH_FILTER = (
    "silenceremove=stop_periods=-1:stop_duration=0.25:stop_threshold=-38dB:"
    "stop_silence=0.08,speechnorm=e=1.8:c=1.6:r=0.0008:f=0.0008:p=0.94"
)


def smooth_narration_audio(input_path: Path, output_path: Path) -> str:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg is required for narration smoothing")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        [ffmpeg, "-y", "-i", str(input_path), "-af", SMOOTH_SPEECH_FILTER, str(output_path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"Narration smoothing failed: {proc.stderr[-1000:]}")
    return str(output_path)
