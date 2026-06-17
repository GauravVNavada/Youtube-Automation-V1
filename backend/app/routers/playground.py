from __future__ import annotations

import base64
from datetime import datetime, timezone
import importlib
import json
import mimetypes
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel

from app.core.config import get_settings


router = APIRouter(prefix="/playground", tags=["playground"])

RUN_SCHEMA_VERSION = 3
TERMINAL_STATUSES = {"succeeded", "failed", "skipped"}
VALID_STAGE_STATUSES = {"queued", "running", "succeeded", "failed", "skipped"}
_RUN_LOCK = threading.RLock()
_ACTIVE_THREADS: dict[str, threading.Thread] = {}


class PlaygroundRunCreate(BaseModel):
    message: str
    genre_id: str = "scary_stories"
    duration: int = 30
    notes: str = ""
    llm_provider: str = "env"
    llm_model: str = ""
    llm_api_key: str = ""


VISIBLE_STAGES: list[dict[str, str]] = [
    {
        "id": "master_agent",
        "agent_name": "master_agent",
        "execution_mode": "deterministic",
        "prompt_text": "Prepare the playground run, validate inputs, and start the shared pipeline.",
    },
    {
        "id": "topic_discovery_agent",
        "agent_name": "topic_discovery_agent",
        "execution_mode": "hybrid",
        "prompt_text": "Find a grounded, specific topic angle from the user message and genre profile.",
    },
    {
        "id": "research_agent",
        "agent_name": "research_agent",
        "execution_mode": "hybrid",
        "prompt_text": "Build a research brief with concrete facts and source snippets the script must use.",
    },
    {
        "id": "script_agent",
        "agent_name": "script_agent",
        "execution_mode": "ai",
        "prompt_text": "Write a clear, grounded short script with simple words, alert beats, and a complete ending.",
    },
    {
        "id": "audio_agent",
        "agent_name": "audio_agent",
        "execution_mode": "hybrid",
        "prompt_text": "Create narration audio and word timings, using fallbacks when external TTS/alignment fails.",
    },
    {
        "id": "caption_agent",
        "agent_name": "caption_agent",
        "execution_mode": "deterministic",
        "prompt_text": "Build readable timed captions from word timestamps.",
    },
    {
        "id": "timed_visual_agent",
        "agent_name": "timed_visual_agent",
        "execution_mode": "hybrid",
        "prompt_text": "Merge caption timing into visual windows and rewrite them into concrete asset searches.",
    },
    {
        "id": "asset_agent",
        "agent_name": "asset_agent",
        "execution_mode": "hybrid",
        "prompt_text": "Fetch videos and images for each timed visual cue, then select the best non-repeating asset.",
    },
    {
        "id": "render_agent",
        "agent_name": "render_agent",
        "execution_mode": "deterministic",
        "prompt_text": "Render a vertical MP4 from visuals, narration, captions, and optional music.",
    },
    {
        "id": "thumbnail_agent",
        "agent_name": "thumbnail_agent",
        "execution_mode": "deterministic",
        "prompt_text": "Create reusable cover/thumbnail images from the final video and selected visuals.",
    },
    {
        "id": "final_output",
        "agent_name": "final_output",
        "execution_mode": "deterministic",
        "prompt_text": "Collect final video, thumbnails, transcript, logs, and run metadata.",
    },
]

STAGE_INDEX = {stage["id"]: index for index, stage in enumerate(VISIBLE_STAGES)}
PIPELINE_STAGE_TO_VISIBLE = {
    "bootstrap": "master_agent",
    "load_references": "master_agent",
    "llm_provider": "master_agent",
    "topic_discovery_agent": "topic_discovery_agent",
    "research_agent": "research_agent",
    "script_agent": "script_agent",
    "validate_script": "script_agent",
    "validate_script_result": "script_agent",
    "audio_agent": "audio_agent",
    "validate_audio": "audio_agent",
    "validate_audio_result": "audio_agent",
    "caption_agent": "caption_agent",
    "validate_captions": "caption_agent",
    "validate_captions_result": "caption_agent",
    "timed_visual_agent": "timed_visual_agent",
    "asset_agent": "asset_agent",
    "validate_assets": "asset_agent",
    "validate_assets_result": "asset_agent",
    "render_agent": "render_agent",
    "validate_render": "render_agent",
    "validate_render_result": "render_agent",
    "thumbnail_agent": "thumbnail_agent",
}

STDOUT_STAGE_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"Discovering grounded angle", re.I), "topic_discovery_agent"),
    (re.compile(r"Building research brief", re.I), "research_agent"),
    (re.compile(r"Generating script", re.I), "script_agent"),
    (re.compile(r"Generating audio", re.I), "audio_agent"),
    (re.compile(r"Building captions", re.I), "caption_agent"),
    (re.compile(r"Building timed visual cues", re.I), "timed_visual_agent"),
    (re.compile(r"Fetching assets", re.I), "asset_agent"),
    (re.compile(r"Rendering video", re.I), "render_agent"),
    (re.compile(r"Generating thumbnails", re.I), "thumbnail_agent"),
)


def _project_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "final_pipeline" / "main.py").exists():
            return parent
    return Path(__file__).resolve().parents[3]


def _pipeline_root() -> Path:
    configured = os.getenv("PLAYGROUND_PIPELINE_ROOT", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return _project_root() / "final_pipeline"


def _pipeline_data_dir() -> Path:
    configured = os.getenv("PLAYGROUND_PIPELINE_DATA_DIR", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return _project_root() / "playground" / "data" / "pipeline"


def _runs_dir() -> Path:
    configured = os.getenv("PLAYGROUND_RUNS_DIR", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return _project_root() / "playground" / "data" / "runs"


def _pipeline_output_runs_dir() -> Path:
    configured = os.getenv("PLAYGROUND_PIPELINE_RUNS_DIR", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return _runs_dir() / "_pipeline_outputs"


def _ensure_pipeline_import_path() -> None:
    pipeline_root = str(_pipeline_root())
    if pipeline_root not in sys.path:
        sys.path.append(pipeline_root)


def _render_prompt_module(module_name: str, fallback: str) -> str:
    try:
        _ensure_pipeline_import_path()
        module = importlib.import_module(module_name)
        module = importlib.reload(module)
        from agents.prompts.message_base import render_messages_for_single_prompt

        if hasattr(module, "messages_base"):
            return render_messages_for_single_prompt(module.messages_base())
    except Exception as exc:
        return f"{fallback}\n\nPrompt module could not be loaded: {type(exc).__name__}: {exc}"
    return fallback


def _prompt_text_for_stage(stage_id: str, fallback: str = "") -> str:
    if stage_id == "script_agent":
        return _render_prompt_module("agents.prompts.script_prompts", fallback)
    if stage_id == "asset_agent":
        return _render_prompt_module("agents.prompts.asset_prompts", fallback)
    if stage_id == "master_agent":
        master_prompt = _render_prompt_module("agents.prompts.master_prompts", "")
        desktop_prompt = _desktop_agent_prompt_text()
        if master_prompt:
            return (
                "Playground bootstrap is deterministic, so no LLM prompt is sent for this stage.\n\n"
                "Prompt-based master planning module available:\n\n"
                f"{master_prompt}"
                f"{desktop_prompt}"
            )
        if desktop_prompt:
            return f"{fallback}{desktop_prompt}"
    if stage_id in {"audio_agent", "caption_agent", "render_agent", "thumbnail_agent", "final_output"}:
        return f"{fallback}\n\nThis stage is deterministic or provider-specific and does not send an agent prompt."
    if stage_id == "timed_visual_agent":
        return f"{fallback}\n\nThis stage uses deterministic caption timing plus one best-effort batch LLM rewrite."
    if stage_id in {"topic_discovery_agent", "research_agent"}:
        return f"{fallback}\n\nThis stage uses deterministic grounding/research helpers plus source lookups, not an agents/prompts LLM prompt."
    return fallback


def _desktop_agent_prompt_text() -> str:
    sections = []
    try:
        from desktop_pipeline.message_base import render_messages_for_single_prompt
        from desktop_pipeline import master_agent, parameter_agent, style_sampler_agent

        for title, module in (
            ("Desktop Master Agent", master_agent),
            ("Desktop Style Sampler Agent", style_sampler_agent),
            ("Desktop Parameter Agent", parameter_agent),
        ):
            if hasattr(module, "messages_base"):
                sections.append(f"\n\n--- {title} Examples ---\n\n{render_messages_for_single_prompt(module.messages_base())}")
    except Exception as exc:
        sections.append(f"\n\nDesktop agent examples could not be loaded: {type(exc).__name__}: {exc}")
    return "".join(sections)


def _run_path(run_id: str) -> Path:
    return _runs_dir() / f"{run_id}.json"


def _run_workspace(run_id: str) -> Path:
    return _runs_dir() / run_id


@router.get("/genres")
def list_genres() -> list[dict[str, Any]]:
    genres_dir = _pipeline_data_dir() / "genres"
    if not genres_dir.exists():
        return []
    genres: list[dict[str, Any]] = []
    for path in sorted(genres_dir.glob("*.yaml")):
        data = _parse_simple_yaml(path.read_text(encoding="utf-8"))
        genres.append(
            {
                "genre_id": str(data.get("genre_id") or path.stem),
                "display_name": str(data.get("display_name") or path.stem.replace("_", " ").title()),
            }
        )
    return genres


@router.get("/llm-options")
def list_llm_options() -> list[dict[str, Any]]:
    settings = get_settings()
    return [
        {"provider": "env", "label": "Docker / .env", "models": [], "default_model": ""},
        {"provider": "gemini", "label": "Google Gemini", "models": [settings.gemini_model], "default_model": settings.gemini_model},
    ]


@router.get("/runs")
def list_runs() -> list[dict[str, Any]]:
    _runs_dir().mkdir(parents=True, exist_ok=True)
    runs: list[dict[str, Any]] = []
    paths = sorted(_runs_dir().glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True)
    for path in paths:
        try:
            runs.append(_read_run(path))
        except Exception as exc:
            runs.append(_broken_run_summary(path, exc))
    return [
        {
            "id": run["id"],
            "user_message": run.get("user_message", ""),
            "status": run.get("status", "failed"),
            "created_at": run.get("created_at", ""),
            "updated_at": run.get("updated_at", ""),
        }
        for run in runs[:50]
    ]


@router.post("/runs")
def create_run(payload: PlaygroundRunCreate) -> dict[str, Any]:
    message = " ".join(payload.message.split())
    if not message:
        raise HTTPException(status_code=400, detail="Test message is required")

    payload = payload.model_copy(update={"message": message, "duration": _safe_duration(payload.duration)})
    run = _build_initial_run(payload)
    _runs_dir().mkdir(parents=True, exist_ok=True)
    _run_workspace(run["id"]).mkdir(parents=True, exist_ok=True)
    _save_run(run)
    _start_run_thread(run["id"], payload)
    return _read_run(_run_path(run["id"]))


@router.get("/runs/{run_id}")
def get_run(run_id: str) -> dict[str, Any]:
    path = _run_path(run_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Playground run not found")
    return _read_run(path)


@router.get("/runs/{run_id}/stages/{stage_id}")
def get_stage(run_id: str, stage_id: str) -> dict[str, Any]:
    run = get_run(run_id)
    for stage in run["stages"]:
        if stage["id"] == stage_id:
            return stage
    raise HTTPException(status_code=404, detail="Playground stage not found")


@router.get("/artifacts/{artifact_id}")
def get_artifact(artifact_id: str):
    decoded = _decode_artifact_id(artifact_id)
    if decoded is None or not decoded.exists() or not decoded.is_file():
        raise HTTPException(status_code=404, detail="Artifact not found")
    if decoded.suffix.lower() in {".txt", ".log", ".json", ".yaml", ".yml", ".srt", ".ass"}:
        return PlainTextResponse(decoded.read_text(encoding="utf-8", errors="replace"))
    return FileResponse(decoded)


def _build_initial_run(payload: PlaygroundRunCreate) -> dict[str, Any]:
    now = _now()
    run_id = str(uuid4())
    genre = _genre_for(payload.genre_id)
    effective_message = _effective_message(payload)
    effective_duration = _effective_duration(payload)
    route_summary = f"{genre['display_name']} pipeline run for: {effective_message}"
    stages = [_initial_stage(stage, now) for stage in VISIBLE_STAGES]
    stages[0] = _mark_stage_dict(
        stages[0],
        "running",
        now,
        input_json=_safe_payload(payload),
        output_json={
            "route_summary": route_summary,
            "genre_id": genre["genre_id"],
            "duration": effective_duration,
            "raw_message": payload.message,
            "cleaned_message": effective_message,
            "selected_provider": payload.llm_provider,
            "selected_model": payload.llm_model or "environment default",
        },
        message="Playground run accepted",
    )
    return {
        "schema_version": RUN_SCHEMA_VERSION,
        "id": run_id,
        "user_message": effective_message,
        "raw_user_message": payload.message,
        "genre_id": genre["genre_id"],
        "duration": effective_duration,
        "notes": payload.notes,
        "llm_provider": payload.llm_provider,
        "llm_model": payload.llm_model,
        "status": "running",
        "route_summary": route_summary,
        "created_at": now,
        "updated_at": now,
        "pipeline_run_dir": "",
        "stdout_path": "",
        "returncode": None,
        "stages": stages,
    }


def _initial_stage(spec: dict[str, str], timestamp: str) -> dict[str, Any]:
    fallback_prompt = spec.get("prompt_text", "")
    return {
        "id": spec["id"],
        "agent_name": spec["agent_name"],
        "execution_mode": spec["execution_mode"],
        "status": "queued",
        "started_at": "",
        "completed_at": "",
        "updated_at": timestamp,
        "input_json": {},
        "prompt_text": _prompt_text_for_stage(spec["id"], fallback_prompt),
        "output_json": {},
        "events": [],
        "artifacts": [],
        "error_text": "",
    }


def _start_run_thread(run_id: str, payload: PlaygroundRunCreate) -> None:
    thread = threading.Thread(target=_execute_run, args=(run_id, payload), daemon=True, name=f"playground-{run_id[:8]}")
    _ACTIVE_THREADS[run_id] = thread
    thread.start()


def _execute_run(run_id: str, payload: PlaygroundRunCreate) -> None:
    transcript = _run_workspace(run_id) / "stdout.log"
    try:
        transcript.parent.mkdir(parents=True, exist_ok=True)
        _update_run(run_id, lambda run: _mark_stage(run, "master_agent", "succeeded", "Shared pipeline process is starting"))
        env = _pipeline_env(payload)
        cmd = [
            sys.executable,
            "main.py",
            "--topic",
            _effective_message(payload),
            "--genre",
            payload.genre_id,
            "--duration",
            str(_effective_duration(payload)),
        ]
        if payload.notes:
            cmd.extend(["--notes", payload.notes])

        pipeline_root = _pipeline_root()
        if not (pipeline_root / "main.py").exists():
            raise RuntimeError(f"Shared pipeline entrypoint not found: {pipeline_root / 'main.py'}")

        with transcript.open("a", encoding="utf-8") as log:
            log.write(f"$ {' '.join(cmd)}\n")
            process = subprocess.Popen(
                cmd,
                cwd=str(pipeline_root),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            _update_run(
                run_id,
                lambda run: run.update(
                    {
                        "process_id": process.pid,
                        "stdout_path": str(transcript),
                        "updated_at": _now(),
                    }
                ),
            )
            assert process.stdout is not None
            for raw_line in process.stdout:
                line = raw_line.rstrip()
                log.write(raw_line)
                log.flush()
                _handle_pipeline_line(run_id, line)
            returncode = process.wait()

        def finish(run: dict[str, Any]) -> None:
            run["returncode"] = returncode
            run["stdout_path"] = str(transcript)
            _refresh_run_from_pipeline_files(run)
            if returncode == 0:
                _complete_successful_run(run)
            else:
                _fail_run_from_pipeline_error(run, f"Pipeline exited with code {returncode}")

        _update_run(run_id, finish)
    except Exception as exc:
        _update_run(run_id, lambda run: _fail_run(run, "master_agent", str(exc)))
    finally:
        _ACTIVE_THREADS.pop(run_id, None)


def _pipeline_env(payload: PlaygroundRunCreate) -> dict[str, str]:
    env = os.environ.copy()
    env["MODULARSHORTS_DATA_DIR"] = str(_pipeline_data_dir())
    env["MODULARSHORTS_RUNS_DIR"] = str(_pipeline_output_runs_dir())
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONPATH"] = f"{_pipeline_root()}{os.pathsep}{env.get('PYTHONPATH', '')}".rstrip(os.pathsep)

    provider = (payload.llm_provider or "env").strip().lower()
    if provider and provider != "env":
        if provider not in {"gemini", "google"}:
            raise ValueError("Only Gemini is supported for playground generation.")
        env["LLM_PROVIDER"] = provider
    else:
        env["LLM_PROVIDER"] = "gemini"

    if payload.llm_model:
        if provider == "gemini":
            env["GEMINI_MODEL"] = payload.llm_model
        else:
            env["GEMINI_MODEL"] = payload.llm_model

    api_key = payload.llm_api_key.strip()
    if api_key:
        env["LLM_PROVIDER"] = "gemini"
        env["GEMINI_API_KEY"] = api_key
    return env


def _has_any_llm_key(env: dict[str, str]) -> bool:
    return any(env.get(name, "").strip() for name in ("LLM_API_KEY", "GEMINI_API_KEY"))


def _handle_pipeline_line(run_id: str, line: str) -> None:
    if not line:
        return

    def apply(run: dict[str, Any]) -> None:
        run["updated_at"] = _now()
        run_match = re.match(r"\[run\]\s*(.+)", line)
        if run_match:
            run["pipeline_run_dir"] = run_match.group(1).strip()
            _mark_stage(run, "master_agent", "succeeded", "Pipeline run directory created")
            return
        if line.startswith("Final video:"):
            final_path = line.split(":", 1)[1].strip()
            final = _stage_by_id(run, "final_output")
            final.setdefault("output_json", {})["video_path"] = final_path
            final.setdefault("events", []).append(_event("Final video ready", {"video_path": final_path}))
            return
        if line.startswith("[error]"):
            _append_event_to_current(run, line, level="error")
            return
        stage_id = _stage_from_stdout(line)
        if stage_id:
            _complete_stages_before(run, stage_id)
            _mark_stage(run, stage_id, "running", line)
            return
        _append_event_to_current(run, line)

    _update_run(run_id, apply)


def _stage_from_stdout(line: str) -> str:
    for pattern, stage_id in STDOUT_STAGE_PATTERNS:
        if pattern.search(line):
            return stage_id
    if re.search(r"\bComplete\b", line, re.I):
        return "final_output"
    return ""


def _complete_stages_before(run: dict[str, Any], stage_id: str) -> None:
    target_index = STAGE_INDEX[stage_id]
    timestamp = _now()
    for stage in run["stages"][:target_index]:
        if stage["status"] == "running":
            stage["status"] = "succeeded"
            stage["completed_at"] = timestamp
            stage["updated_at"] = timestamp


def _complete_successful_run(run: dict[str, Any]) -> None:
    _refresh_run_from_pipeline_files(run)
    timestamp = _now()
    for stage in run["stages"]:
        if stage["status"] in {"queued", "running"}:
            stage["status"] = "succeeded"
            stage["started_at"] = stage["started_at"] or timestamp
            stage["completed_at"] = stage["completed_at"] or timestamp
            stage["updated_at"] = timestamp
    final = _stage_by_id(run, "final_output")
    final["output_json"].update(_final_output_json(run))
    final["artifacts"] = _collect_final_artifacts(run)
    run["status"] = "succeeded"
    run["updated_at"] = timestamp


def _fail_run_from_pipeline_error(run: dict[str, Any], fallback_message: str) -> None:
    _refresh_run_from_pipeline_files(run)
    error = _pipeline_error(run)
    visible_stage = PIPELINE_STAGE_TO_VISIBLE.get(str(error.get("stage") or ""), "")
    message = str(error.get("message") or fallback_message)
    if not visible_stage:
        visible_stage = _current_or_first_unfinished_stage(run)
    _fail_run(run, visible_stage, message, error)


def _fail_run(run: dict[str, Any], stage_id: str, message: str, details: dict[str, Any] | None = None) -> None:
    timestamp = _now()
    failed_index = STAGE_INDEX.get(stage_id, 0)
    for index, stage in enumerate(run["stages"]):
        if index < failed_index and stage["status"] in {"queued", "running"}:
            stage["status"] = "succeeded"
            stage["started_at"] = stage["started_at"] or timestamp
            stage["completed_at"] = stage["completed_at"] or timestamp
        elif index == failed_index:
            stage["status"] = "failed"
            stage["started_at"] = stage["started_at"] or timestamp
            stage["completed_at"] = timestamp
            stage["error_text"] = message
            stage["events"].append(_event(message, details or {}, level="error"))
        elif stage["status"] == "queued":
            stage["status"] = "skipped"
            stage["updated_at"] = timestamp
    final = _stage_by_id(run, "final_output")
    if final["status"] not in {"failed", "skipped"}:
        final["status"] = "failed"
        final["started_at"] = final["started_at"] or timestamp
        final["completed_at"] = timestamp
        final["error_text"] = message
        final["events"].append(_event("Run failed before final output", {"failed_stage": stage_id}, level="error"))
    run["status"] = "failed"
    run["updated_at"] = timestamp


def _refresh_run_from_pipeline_files(run: dict[str, Any]) -> None:
    run_dir_text = str(run.get("pipeline_run_dir") or "")
    if not run_dir_text:
        return
    run_dir = Path(run_dir_text)
    if not run_dir.exists():
        return
    for stage in run.get("stages", []):
        stage_id = stage.get("id")
        if stage_id in {"master_agent", "final_output"}:
            continue
        log_dir = run_dir / "logs" / str(stage_id)
        if not log_dir.exists():
            continue
        input_json = _read_json(log_dir / "input.json")
        output_json = _read_json(log_dir / "output.json")
        events = _read_events(log_dir / "events.log")
        if input_json is not None:
            stage["input_json"] = input_json
            if stage["status"] == "queued":
                stage["status"] = "running"
                stage["started_at"] = stage["started_at"] or _mtime(log_dir / "input.json")
        if output_json is not None:
            stage["output_json"] = _merge_validation_summary(stage_id, output_json, run_dir)
            if stage["status"] != "failed":
                stage["status"] = "succeeded"
                stage["completed_at"] = stage["completed_at"] or _mtime(log_dir / "output.json")
        if events:
            stage["events"] = events
        stage["artifacts"] = _collect_stage_artifacts(stage_id, run_dir, log_dir, stage.get("output_json", {}))
        stage["updated_at"] = _now()


def _merge_validation_summary(stage_id: str, output_json: dict[str, Any], run_dir: Path) -> dict[str, Any]:
    validation_map = {
        "script_agent": "validate_script",
        "asset_agent": "validate_assets",
        "audio_agent": "validate_audio",
        "caption_agent": "validate_captions",
        "render_agent": "validate_render",
    }
    validation_stage = validation_map.get(stage_id)
    if not validation_stage:
        return output_json
    error = _read_json(run_dir / "errors" / "error.json")
    if isinstance(error, dict) and str(error.get("stage")) in {validation_stage, f"{validation_stage}_result"}:
        output_json = dict(output_json)
        output_json["validation"] = {"passed": False, "error": error.get("message", "")}
        return output_json
    output_json = dict(output_json)
    output_json.setdefault("validation", {"passed": True, "issues": []})
    return output_json


def _collect_stage_artifacts(stage_id: str, run_dir: Path, log_dir: Path, output_json: dict[str, Any]) -> list[dict[str, Any]]:
    paths: list[Path] = [
        log_dir / "input.json",
        log_dir / "output.json",
        log_dir / "events.log",
    ]
    if stage_id == "asset_agent":
        paths.append(log_dir / "asset_selection_trace.json")
        if output_json.get("asset_trace_path"):
            paths.append(Path(str(output_json.get("asset_trace_path"))))
        if output_json.get("timed_visual_cues_path"):
            paths.append(Path(str(output_json.get("timed_visual_cues_path"))))
        paths.extend(Path(path) for path in output_json.get("image_paths", []) if path)
        paths.extend(Path(path) for path in output_json.get("video_paths", []) if path)
        paths.extend(Path(path) for path in output_json.get("media_paths", []) if path)
    elif stage_id == "audio_agent":
        paths.extend(Path(path) for path in (output_json.get("narration_path"), output_json.get("final_audio_path")) if path)
    elif stage_id == "caption_agent":
        paths.extend(Path(path) for path in (output_json.get("srt_path"), output_json.get("ass_path")) if path)
    elif stage_id == "timed_visual_agent":
        paths.append(log_dir / "timed_visual_cues.json")
        if isinstance(output_json, dict) and output_json.get("timed_visual_cues_path"):
            paths.append(Path(str(output_json.get("timed_visual_cues_path"))))
    elif stage_id == "render_agent":
        paths.extend(Path(path) for path in (output_json.get("video_path"), str(run_dir / "output" / "final_audio_check.wav")) if path)
    elif stage_id == "thumbnail_agent":
        paths.extend(Path(path) for path in (output_json.get("shorts_cover_path"), output_json.get("youtube_thumbnail_path")) if path)
    return _artifact_list(paths)


def _collect_final_artifacts(run: dict[str, Any]) -> list[dict[str, Any]]:
    paths: list[Path] = []
    stdout = str(run.get("stdout_path") or "")
    if stdout:
        paths.append(Path(stdout))
    run_dir_text = str(run.get("pipeline_run_dir") or "")
    if run_dir_text:
        run_dir = Path(run_dir_text)
        paths.extend(
            [
                run_dir / "output" / "final.mp4",
                run_dir / "output" / "final_audio_check.wav",
                run_dir / "output" / "thumbnails" / "shorts_cover.jpg",
                run_dir / "output" / "thumbnails" / "youtube_thumbnail.jpg",
                run_dir / "logs" / "timed_visual_agent" / "timed_visual_cues.json",
                run_dir / "logs" / "asset_agent" / "asset_selection_trace.json",
                run_dir / "errors" / "error.json",
            ]
        )
    return _artifact_list(paths)


def _final_output_json(run: dict[str, Any]) -> dict[str, Any]:
    run_dir_text = str(run.get("pipeline_run_dir") or "")
    run_dir = Path(run_dir_text) if run_dir_text else None
    final_video = run_dir / "output" / "final.mp4" if run_dir else None
    return {
        "status": run.get("status", "running"),
        "pipeline_run_dir": run_dir_text,
        "video_path": str(final_video) if final_video and final_video.exists() else "",
        "stdout_path": run.get("stdout_path", ""),
        "returncode": run.get("returncode"),
    }


def _artifact_list(paths: list[Path]) -> list[dict[str, Any]]:
    artifacts: list[dict[str, Any]] = []
    seen: set[str] = set()
    for path in paths:
        try:
            resolved = path.expanduser().resolve()
        except OSError:
            continue
        if str(resolved) in seen or not resolved.exists() or not resolved.is_file():
            continue
        seen.add(str(resolved))
        artifacts.append(
            {
                "id": _encode_artifact_id(resolved),
                "path": str(resolved),
                "kind": _artifact_kind(resolved),
                "size_bytes": resolved.stat().st_size,
                "previewable": True,
            }
        )
    return artifacts


def _artifact_kind(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".jpg", ".jpeg", ".png", ".webp"}:
        return "image"
    if suffix in {".mp4", ".mov", ".webm"}:
        return "video"
    if suffix in {".wav", ".mp3", ".m4a", ".aac"}:
        return "audio"
    if suffix == ".json":
        return "json"
    if suffix in {".txt", ".log", ".yaml", ".yml", ".srt", ".ass"}:
        return "text"
    guessed = mimetypes.guess_type(path.name)[0] or ""
    if guessed.startswith("image/"):
        return "image"
    if guessed.startswith("video/"):
        return "video"
    if guessed.startswith("audio/"):
        return "audio"
    return "file"


def _read_run(path: Path) -> dict[str, Any]:
    with _RUN_LOCK:
        run = _read_run_raw(path)
        changed = _sanitize_run(run)
        if _needs_normalization(run):
            run = _normalize_legacy_run(run, path)
            changed = True
        _refresh_run_from_pipeline_files(run)
        changed = _ensure_prompt_texts(run) or changed
        if run.get("status") in TERMINAL_STATUSES:
            final = _stage_by_id(run, "final_output")
            final["output_json"].update(_final_output_json(run))
            final["artifacts"] = _collect_final_artifacts(run)
        if changed:
            _save_run(run)
        return run


def _read_run_raw(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _save_run(run: dict[str, Any]) -> None:
    path = _run_path(str(run["id"]))
    path.parent.mkdir(parents=True, exist_ok=True)
    _sanitize_run(run)
    tmp = path.with_suffix(".json.tmp")
    try:
        tmp.write_text(json.dumps(run, indent=2, ensure_ascii=True), encoding="utf-8")
        tmp.replace(path)
    except OSError:
        try:
            path.write_text(json.dumps(run, indent=2, ensure_ascii=True), encoding="utf-8")
        except OSError:
            pass


def _update_run(run_id: str, updater) -> None:
    with _RUN_LOCK:
        path = _run_path(run_id)
        run = _read_run_raw(path)
        _sanitize_run(run)
        updater(run)
        _save_run(run)


def _sanitize_run(run: dict[str, Any]) -> bool:
    changed = False
    if "llm_api_key" in run:
        run.pop("llm_api_key", None)
        changed = True
    for stage in run.get("stages", []):
        input_json = stage.get("input_json")
        if isinstance(input_json, dict) and input_json.get("llm_api_key") not in {None, "", "provided"}:
            input_json["llm_api_key"] = "provided"
            changed = True
    return changed


def _ensure_prompt_texts(run: dict[str, Any]) -> bool:
    changed = False
    specs = {stage["id"]: stage for stage in VISIBLE_STAGES}
    for stage in run.get("stages", []):
        if not isinstance(stage, dict):
            continue
        stage_id = str(stage.get("id") or "")
        spec = specs.get(stage_id)
        if not spec:
            continue
        prompt_text = _prompt_text_for_stage(stage_id, spec.get("prompt_text", ""))
        if stage.get("prompt_text") != prompt_text:
            stage["prompt_text"] = prompt_text
            changed = True
    return changed


def _needs_normalization(run: dict[str, Any]) -> bool:
    if int(run.get("schema_version") or 0) < RUN_SCHEMA_VERSION:
        return True
    stages = run.get("stages")
    if not isinstance(stages, list) or [stage.get("id") for stage in stages] != [stage["id"] for stage in VISIBLE_STAGES]:
        return True
    return any(str(stage.get("status") or "") not in VALID_STAGE_STATUSES for stage in stages if isinstance(stage, dict))


def _normalize_legacy_run(run: dict[str, Any], path: Path) -> dict[str, Any]:
    payload = PlaygroundRunCreate(
        message=str(run.get("user_message") or run.get("message") or "Legacy playground run"),
        genre_id=str(run.get("genre_id") or "scary_stories"),
        duration=_safe_duration(int(run.get("duration") or 30)),
        notes=str(run.get("notes") or ""),
        llm_provider=str(run.get("llm_provider") or "env"),
        llm_model=str(run.get("llm_model") or ""),
    )
    normalized = _build_initial_run(payload)
    normalized["id"] = str(run.get("id") or path.stem)
    normalized["created_at"] = str(run.get("created_at") or normalized["created_at"])
    normalized["updated_at"] = _now()
    normalized["pipeline_run_dir"] = str(run.get("pipeline_run_dir") or "")
    normalized["stdout_path"] = str(run.get("stdout_path") or "")
    normalized["returncode"] = run.get("returncode")
    if normalized["pipeline_run_dir"]:
        _refresh_run_from_pipeline_files(normalized)
        if normalized.get("returncode") == 0:
            _complete_successful_run(normalized)
        elif normalized.get("returncode") is not None:
            _fail_run_from_pipeline_error(normalized, "Legacy run failed")
    else:
        _fail_run(
            normalized,
            "master_agent",
            "This was an old mock playground run. Start a new run to execute the real shared pipeline.",
        )
    return normalized


def _broken_run_summary(path: Path, exc: Exception) -> dict[str, Any]:
    now = _now()
    return {
        "id": path.stem,
        "user_message": f"Unreadable run file: {path.name}",
        "status": "failed",
        "created_at": now,
        "updated_at": now,
        "error_text": str(exc),
    }


def _safe_payload(payload: PlaygroundRunCreate) -> dict[str, Any]:
    data = payload.model_dump()
    data["llm_api_key"] = "provided" if payload.llm_api_key.strip() else ""
    data["effective_message"] = _effective_message(payload)
    data["effective_duration"] = _effective_duration(payload)
    return data


def _effective_duration(payload: PlaygroundRunCreate) -> int:
    return _duration_from_text(payload.message) or _safe_duration(payload.duration)


def _effective_message(payload: PlaygroundRunCreate) -> str:
    return _strip_duration_instruction(payload.message)


def _safe_duration(duration: int) -> int:
    if duration in {30, 45, 60}:
        return duration
    return 30


def _duration_from_text(text: str) -> int | None:
    patterns = (
        r"\bduration\s*(?:of|for|is|:|=|,|-)?\s*(30|45|60)\s*(?:seconds?|secs?|secons?|secnds?|s)?\b",
        r"\b(30|45|60)\s*(?:seconds?|secs?|secons?|secnds?|s)\b",
    )
    for pattern in patterns:
        match = re.search(pattern, str(text or ""), flags=re.I)
        if match:
            return int(match.group(1))
    return None


def _strip_duration_instruction(text: str) -> str:
    cleaned = str(text or "")
    cleaned = re.sub(r"\b(?:keep|set|use|with)?\s*(?:the\s+)?duration\s*(?:of|for|to|is|:|=|,|-)?\s*(?:30|45|60)\s*(?:seconds?|secs?|secons?|secnds?|s)?\b", " ", cleaned, flags=re.I)
    cleaned = re.sub(r"\b(?:keep|set|use)\s+(?:it\s+)?(?:for|to)?\s*(?:30|45|60)\s*(?:seconds?|secs?|secons?|secnds?|s)\b", " ", cleaned, flags=re.I)
    cleaned = re.sub(r"\b(?:30|45|60)\s*(?:seconds?|secs?|secons?|secnds?|s)\b", " ", cleaned, flags=re.I)
    cleaned = re.sub(r"\s+([,.;!?])", r"\1", cleaned)
    cleaned = re.sub(r"(?:,\s*)?\b(?:keep|set|use)\b\s*$", " ", cleaned, flags=re.I)
    return " ".join(cleaned.split()).strip(" ,.;")


def _genre_for(genre_id: str) -> dict[str, Any]:
    path = _pipeline_data_dir() / "genres" / f"{genre_id}.yaml"
    if not path.exists():
        genres = list_genres()
        if not genres:
            return {"genre_id": genre_id, "display_name": genre_id.replace("_", " ").title()}
        path = _pipeline_data_dir() / "genres" / f"{genres[0]['genre_id']}.yaml"
    data = _parse_simple_yaml(path.read_text(encoding="utf-8"))
    return {
        "genre_id": str(data.get("genre_id") or path.stem),
        "display_name": str(data.get("display_name") or path.stem.replace("_", " ").title()),
        "tone": str(data.get("tone") or ""),
        "word_count_min": data.get("word_count_min"),
        "word_count_max": data.get("word_count_max"),
    }


def _stage_by_id(run: dict[str, Any], stage_id: str) -> dict[str, Any]:
    for stage in run.get("stages", []):
        if stage.get("id") == stage_id:
            return stage
    raise KeyError(stage_id)


def _current_or_first_unfinished_stage(run: dict[str, Any]) -> str:
    for stage in run.get("stages", []):
        if stage.get("status") == "running":
            return str(stage.get("id"))
    for stage in run.get("stages", []):
        if stage.get("status") == "queued":
            return str(stage.get("id"))
    return "final_output"


def _mark_stage(run: dict[str, Any], stage_id: str, status: str, message: str = "", details: dict[str, Any] | None = None) -> None:
    stage = _stage_by_id(run, stage_id)
    _mark_stage_dict(stage, status, _now(), message=message, output_json=None, input_json=None, details=details)
    if status == "running":
        run["status"] = "running"
    run["updated_at"] = _now()


def _mark_stage_dict(
    stage: dict[str, Any],
    status: str,
    timestamp: str,
    *,
    input_json: dict[str, Any] | None = None,
    output_json: dict[str, Any] | None = None,
    message: str = "",
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    stage["status"] = status
    if status == "running":
        stage["started_at"] = stage["started_at"] or timestamp
    if status in TERMINAL_STATUSES:
        stage["started_at"] = stage["started_at"] or timestamp
        stage["completed_at"] = stage["completed_at"] or timestamp
    if input_json is not None:
        stage["input_json"] = input_json
    if output_json is not None:
        stage["output_json"] = output_json
    if message:
        stage.setdefault("events", []).append(_event(message, details or {}, level="error" if status == "failed" else "info"))
    stage["updated_at"] = timestamp
    return stage


def _append_event_to_current(run: dict[str, Any], message: str, level: str = "info") -> None:
    stage_id = _current_or_first_unfinished_stage(run)
    stage = _stage_by_id(run, stage_id)
    stage.setdefault("events", []).append(_event(message, {"source": "pipeline_stdout"}, level=level))


def _event(message: str, payload: dict[str, Any] | None = None, level: str = "info") -> dict[str, Any]:
    return {
        "id": str(uuid4()),
        "timestamp": _now(),
        "level": level,
        "message": message,
        "payload_json": payload or {},
    }


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _read_events(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    events: list[dict[str, Any]] = []
    for index, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines()):
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        payload = {key: value for key, value in record.items() if key not in {"ts", "module", "message"}}
        events.append(
            {
                "id": f"{path.parent.name}-{index}",
                "timestamp": str(record.get("ts") or _now()),
                "level": "info",
                "message": str(record.get("message") or ""),
                "payload_json": payload,
            }
        )
    return events


def _pipeline_error(run: dict[str, Any]) -> dict[str, Any]:
    run_dir_text = str(run.get("pipeline_run_dir") or "")
    if run_dir_text:
        error = _read_json(Path(run_dir_text) / "errors" / "error.json")
        if error:
            return error
    return {}


def _mtime(path: Path) -> str:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()
    except OSError:
        return _now()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_simple_yaml(text: str) -> dict[str, Any]:
    result: dict[str, Any] = {}
    current_key: str | None = None
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line.startswith("  - ") and current_key:
            result.setdefault(current_key, []).append(_parse_scalar(line[4:]))
            continue
        if ":" in line and not line.startswith(" "):
            key, value = line.split(":", 1)
            key = key.strip()
            value = value.strip()
            current_key = key
            result[key] = [] if value == "" else _parse_scalar(value)
    return result


def _parse_scalar(value: str) -> Any:
    value = value.strip().strip('"').strip("'")
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        if not inner:
            return []
        return [_parse_scalar(item.strip()) for item in inner.split(",")]
    return value


def _encode_artifact_id(path: Path) -> str:
    return base64.urlsafe_b64encode(str(path.resolve()).encode("utf-8")).decode("ascii")


def _decode_artifact_id(artifact_id: str) -> Path | None:
    if not re.fullmatch(r"[A-Za-z0-9_.=-]+", artifact_id):
        return None
    try:
        raw = base64.urlsafe_b64decode(artifact_id.encode("ascii")).decode("utf-8")
    except Exception:
        return None
    path = Path(raw).expanduser().resolve()
    allowed = [_runs_dir(), _pipeline_data_dir(), _pipeline_output_runs_dir()]
    if any(_is_relative_to(path, root.resolve()) for root in allowed):
        return path
    return None


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False
