from __future__ import annotations

import os
import subprocess
import sys
import json
from dataclasses import dataclass
from pathlib import Path

from app.core.config import get_settings


@dataclass(frozen=True)
class PipelineRunResult:
    returncode: int
    stdout: str
    stderr: str
    run_dir: str
    video_path: str
    logs_path: str
    error_message: str


class PipelineRunner:
    """Run the local video generation pipeline as an isolated subprocess."""

    def run(
        self,
        topic: str,
        genre: str,
        duration: int,
        notes: str = "",
        settings_payload: dict | None = None,
        env_overrides: dict[str, str] | None = None,
        run_dir_override: str | None = None,
    ) -> PipelineRunResult:
        settings = get_settings()
        root = Path(settings.pipeline_root)
        if not (root / "main.py").exists():
            raise RuntimeError(f"Generator pipeline main.py not found at {root}")

        env = os.environ.copy()
        if env_overrides:
            env.update({key: value for key, value in env_overrides.items() if value})
        env["PIPELINE_RUNS_DIR"] = settings.pipeline_runs_dir
        if run_dir_override:
            env["PIPELINE_RUN_DIR"] = run_dir_override
        command = [
            sys.executable,
            "main.py",
            "--topic",
            topic,
            "--genre",
            genre,
            "--duration",
            str(duration),
        ]
        if notes.strip():
            command.extend(["--notes", notes.strip()])
        if settings_payload:
            command.extend(["--settings-json", json.dumps(settings_payload, ensure_ascii=True)])

        proc = subprocess.run(
            command,
            cwd=root,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=900,
        )
        combined = f"{proc.stdout}\n{proc.stderr}"
        run_dir = _extract_after_prefix(combined, "[run] ") or run_dir_override or ""
        video_path = _extract_after_prefix(combined, "Final video: ")
        logs_path = str(Path(run_dir) / "logs") if run_dir else ""
        error_message = _extract_after_prefix(combined, "[error] ") if proc.returncode else ""
        return PipelineRunResult(
            returncode=proc.returncode,
            stdout=proc.stdout,
            stderr=proc.stderr,
            run_dir=run_dir,
            video_path=video_path,
            logs_path=logs_path,
            error_message=error_message,
        )


def _extract_after_prefix(text: str, prefix: str) -> str:
    for line in text.splitlines():
        if line.startswith(prefix):
            return line[len(prefix) :].strip()
    return ""
