from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any


@dataclass
class PipelineRunResult:
    returncode: int
    stdout: str
    stderr: str
    video_path: str = ""
    run_dir: str = ""


class PipelineRunner:
    def __init__(self, backend_dir: Path | None = None) -> None:
        self.backend_dir = backend_dir or Path(__file__).resolve().parents[2]
        self.project_dir = self.backend_dir.parent
        self.pipeline_dir = self.project_dir / "final_pipeline"

    def run(
        self,
        *,
        topic: str,
        genre: str,
        duration: int,
        notes: str = "",
        settings: dict[str, Any] | None = None,
        env_overrides: dict[str, str] | None = None,
    ) -> PipelineRunResult:
        env = os.environ.copy()
        env.update(env_overrides or {})
        env.setdefault("MODULARSHORTS_DATA_DIR", str(self.backend_dir / "data" / "pipeline"))
        env.setdefault("MODULARSHORTS_RUNS_DIR", str(self.backend_dir / "data" / "pipeline" / "runs"))
        cmd = [
            sys.executable,
            "main.py",
            "--topic",
            topic,
            "--genre",
            genre,
            "--duration",
            str(duration),
        ]
        if notes:
            cmd.extend(["--notes", notes])
        settings = settings or {}
        if settings.get("source_prompt"):
            cmd.extend(["--source-prompt", str(settings["source_prompt"])])
        if "voice_speed" in settings:
            cmd.extend(["--voice-speed", str(settings["voice_speed"])])
        if "caption_words" in settings:
            cmd.extend(["--caption-words", str(settings["caption_words"])])
        if "image_count" in settings:
            cmd.extend(["--image-count", str(settings["image_count"])])
        if "music_volume" in settings:
            cmd.extend(["--music-volume", str(settings["music_volume"])])
        if settings.get("style_profile"):
            cmd.extend(["--style-profile-json", json.dumps(settings["style_profile"], ensure_ascii=True)])
        if settings.get("agent_instructions"):
            cmd.extend(["--agent-instructions-json", json.dumps(settings["agent_instructions"], ensure_ascii=True)])
        completed = subprocess.run(
            cmd,
            cwd=str(self.pipeline_dir),
            env=env,
            capture_output=True,
            text=True,
            timeout=900,
            check=False,
        )
        video_path = _extract_line(completed.stdout, "Final video:")
        run_dir = _extract_line(completed.stdout, "[run]")
        return PipelineRunResult(
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
            video_path=video_path,
            run_dir=run_dir,
        )


def _extract_line(text: str, prefix: str) -> str:
    for line in text.splitlines():
        if line.startswith(prefix):
            return line[len(prefix) :].strip()
    return ""
