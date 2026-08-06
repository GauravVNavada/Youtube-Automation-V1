from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any, Callable


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
        self.project_dir = self._project_dir()
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
        on_stdout_line: Callable[[str], None] | None = None,
    ) -> PipelineRunResult:
        if not (self.pipeline_dir / "main.py").exists():
            return PipelineRunResult(
                returncode=1,
                stdout="",
                stderr=f"Pipeline directory not found: {self.pipeline_dir}",
            )
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
        if settings.get("prepared_genre_config"):
            cmd.extend(["--genre-config-json", json.dumps(settings["prepared_genre_config"], ensure_ascii=True)])
        if settings.get("prepared_reference_scripts"):
            cmd.extend(["--reference-scripts-json", json.dumps(settings["prepared_reference_scripts"], ensure_ascii=True)])
        if settings.get("resume_from_run_dir"):
            cmd.extend(["--resume-from-run-dir", str(settings["resume_from_run_dir"])])
        if settings.get("rerun_stage"):
            cmd.extend(["--rerun-stage", str(settings["rerun_stage"])])

        if on_stdout_line is None:
            completed = subprocess.run(
                cmd,
                cwd=str(self.pipeline_dir),
                env=env,
                capture_output=True,
                text=True,
                timeout=900,
                check=False,
            )
            return PipelineRunResult(
                returncode=completed.returncode,
                stdout=completed.stdout,
                stderr=completed.stderr,
                video_path=_extract_line(completed.stdout, "Final video:"),
                run_dir=_extract_line(completed.stdout, "[run]"),
            )

        process = subprocess.Popen(
            cmd,
            cwd=str(self.pipeline_dir),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        stdout_lines: list[str] = []
        try:
            assert process.stdout is not None
            for line in process.stdout:
                stdout_lines.append(line)
                if on_stdout_line:
                    on_stdout_line(line.rstrip("\n"))
            stderr = process.communicate(timeout=900)[1] or ""
        except subprocess.TimeoutExpired:
            process.kill()
            stderr = (process.communicate()[1] or "") + "\nPipeline timed out after 900 seconds"
            return PipelineRunResult(
                returncode=124,
                stdout="".join(stdout_lines),
                stderr=stderr.strip(),
                video_path="",
                run_dir=_extract_line("".join(stdout_lines), "[run]"),
            )
        stdout = "".join(stdout_lines)
        return PipelineRunResult(
            returncode=process.returncode or 0,
            stdout=stdout,
            stderr=stderr,
            video_path=_extract_line(stdout, "Final video:"),
            run_dir=_extract_line(stdout, "[run]"),
        )

    def _project_dir(self) -> Path:
        for parent in [self.backend_dir, *self.backend_dir.parents]:
            if (parent / "final_pipeline" / "main.py").exists():
                return parent
        return self.backend_dir.parent


def _extract_line(text: str, prefix: str) -> str:
    for line in text.splitlines():
        if line.startswith(prefix):
            return line[len(prefix) :].strip()
    return ""
