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

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel, Field

try:
    from app.core.config import get_settings
except ModuleNotFoundError:
    from backend.app.core.config import get_settings


router = APIRouter(prefix="/playground", tags=["playground"])

RUN_SCHEMA_VERSION = 7
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
    parent_run_id: str = ""
    music_path: str = ""
    chat_history: list[dict[str, Any]] = Field(default_factory=list)
    rerun_stage_id: str = ""
    forced_agent_instructions: dict[str, str] = Field(default_factory=dict)
    settings_patch: dict[str, Any] = Field(default_factory=dict)


class PlaygroundStageRerunRequest(BaseModel):
    message: str = ""
    music_path: str = ""
    settings_patch: dict[str, Any] = Field(default_factory=dict)
    forced_agent_instructions: dict[str, str] = Field(default_factory=dict)


VISIBLE_STAGES: list[dict[str, str]] = [
    {
        "id": "desktop_master_agent",
        "agent_name": "desktop_master_agent",
        "execution_mode": "ai",
        "prompt_text": "Read the chat context and decide whether this is new generation, calibration, or an edit/remake request.",
    },
    {
        "id": "style_sampler_agent",
        "agent_name": "style_sampler_agent",
        "execution_mode": "ai",
        "prompt_text": "Create three calibration style profiles when the desktop onboarding flow asks for samples.",
    },
    {
        "id": "parameter_agent",
        "agent_name": "parameter_agent",
        "execution_mode": "hybrid",
        "prompt_text": "Map follow-up feedback into settings patches and target pipeline-agent repair notes.",
    },
    {
        "id": "master_agent",
        "agent_name": "master_agent",
        "execution_mode": "deterministic",
        "prompt_text": "Prepare the playground run, validate inputs, and start the shared final pipeline.",
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
        "id": "validation_agent",
        "agent_name": "validation_agent",
        "execution_mode": "hybrid",
        "prompt_text": "Validate each pipeline artifact, then send repair notes back to the responsible agent when needed.",
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
        "id": "music_agent",
        "agent_name": "music_agent",
        "execution_mode": "deterministic",
        "prompt_text": "Mix uploaded music and resolved SFX under clean narration, or skip when no audio layers are selected.",
    },
    {
        "id": "render_agent",
        "agent_name": "render_agent",
        "execution_mode": "deterministic",
        "prompt_text": "Render a vertical MP4 from visuals, final audio, and captions.",
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
    "validate_script": "validation_agent",
    "validate_script_result": "validation_agent",
    "validation_agent": "validation_agent",
    "audio_agent": "audio_agent",
    "validate_audio": "validation_agent",
    "validate_audio_result": "validation_agent",
    "caption_agent": "caption_agent",
    "validate_captions": "validation_agent",
    "validate_captions_result": "validation_agent",
    "timed_visual_agent": "timed_visual_agent",
    "asset_agent": "asset_agent",
    "validate_assets": "validation_agent",
    "validate_assets_result": "validation_agent",
    "music_agent": "music_agent",
    "render_agent": "render_agent",
    "validate_render": "validation_agent",
    "validate_render_result": "validation_agent",
    "thumbnail_agent": "thumbnail_agent",
}

STDOUT_STAGE_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"^\[validation\]", re.I), "validation_agent"),
    (re.compile(r"^\[repair\].*script_agent", re.I), "script_agent"),
    (re.compile(r"^\[repair\].*audio_agent", re.I), "audio_agent"),
    (re.compile(r"^\[repair\].*caption_agent", re.I), "caption_agent"),
    (re.compile(r"^\[repair\].*asset_agent", re.I), "asset_agent"),
    (re.compile(r"^\[repair\].*render_agent", re.I), "render_agent"),
    (re.compile(r"Discovering grounded angle", re.I), "topic_discovery_agent"),
    (re.compile(r"Building research brief", re.I), "research_agent"),
    (re.compile(r"Generating script", re.I), "script_agent"),
    (re.compile(r"Generating audio", re.I), "audio_agent"),
    (re.compile(r"Building captions", re.I), "caption_agent"),
    (re.compile(r"Building timed visual cues", re.I), "timed_visual_agent"),
    (re.compile(r"Fetching assets", re.I), "asset_agent"),
    (re.compile(r"Preparing music/SFX mix|Preparing music mix", re.I), "music_agent"),
    (re.compile(r"Rendering video", re.I), "render_agent"),
    (re.compile(r"Generating thumbnails", re.I), "thumbnail_agent"),
)


def _positive_int_env(name: str, default: int) -> int:
    try:
        return max(1, int(os.getenv(name, str(default)) or default))
    except (TypeError, ValueError):
        return default


DEFAULT_PLAYGROUND_SETTINGS: dict[str, Any] = {
    "voice_speed": 1.0,
    "caption_words": 4,
    "image_count": 8,
    "music_volume": 0.12,
    "min_visual_segment_ms": 3500,
    "visual_motion": True,
    "transition_style": "slide",
    "transition_seconds": 0.45,
    "zoom_variant": "mixed",
    "music_path": "",
}

TRANSITION_STYLES = {"slide", "fade", "wipe", "cut"}
ZOOM_VARIANTS = {"mixed", "center_in", "center_out", "still"}
ALLOWED_MUSIC_EXTENSIONS = {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac"}
MAX_MUSIC_UPLOAD_MB = _positive_int_env("PLAYGROUND_MAX_MUSIC_UPLOAD_MB", 300)
MAX_MUSIC_UPLOAD_BYTES = MAX_MUSIC_UPLOAD_MB * 1024 * 1024


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


def _legacy_runs_dir() -> Path:
    return _project_root() / "playground" / "data" / "runs"


def _all_runs_dirs() -> list[Path]:
    roots: list[Path] = []
    for path in (_runs_dir(), _legacy_runs_dir()):
        resolved = path.expanduser().resolve()
        if resolved not in roots:
            roots.append(resolved)
    return roots


def _pipeline_output_runs_dir() -> Path:
    configured = os.getenv("PLAYGROUND_PIPELINE_RUNS_DIR", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return _runs_dir() / "_pipeline_outputs"


def _legacy_pipeline_output_runs_dir() -> Path:
    return _legacy_runs_dir() / "_pipeline_outputs"


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
    if stage_id == "desktop_master_agent":
        return _desktop_agent_prompt_text("master_agent", "Desktop Master Agent") or fallback
    if stage_id == "style_sampler_agent":
        return _desktop_agent_prompt_text("style_sampler_agent", "Desktop Style Sampler Agent") or fallback
    if stage_id == "parameter_agent":
        return _desktop_agent_prompt_text("parameter_agent", "Desktop Parameter Agent") or fallback
    if stage_id == "script_agent":
        return _render_prompt_module("agents.prompts.script_prompts", fallback)
    if stage_id == "asset_agent":
        return _render_prompt_module("agents.prompts.asset_prompts", fallback)
    if stage_id == "validation_agent":
        return _render_prompt_module("agents.prompts.validation_prompts", fallback)
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


def _desktop_agent_prompt_text(only_module: str = "", only_title: str = "") -> str:
    sections = []
    try:
        from desktop_pipeline.message_base import render_messages_for_single_prompt
        from desktop_pipeline import master_agent, parameter_agent, style_sampler_agent

        modules = (
            ("Desktop Master Agent", master_agent),
            ("Desktop Style Sampler Agent", style_sampler_agent),
            ("Desktop Parameter Agent", parameter_agent),
        )
        if only_module:
            modules = tuple((title, module) for title, module in modules if module.__name__.rsplit(".", 1)[-1] == only_module)
        for title, module in modules:
            display_title = only_title or title
            if hasattr(module, "messages_base"):
                sections.append(f"\n\n--- {display_title} Examples ---\n\n{render_messages_for_single_prompt(module.messages_base())}")
    except Exception as exc:
        sections.append(f"\n\nDesktop agent examples could not be loaded: {type(exc).__name__}: {exc}")
    return "".join(sections)


def _run_path(run_id: str) -> Path:
    return _runs_dir() / f"{run_id}.json"


def _existing_run_path(run_id: str) -> Path:
    for root in _all_runs_dirs():
        path = root / f"{run_id}.json"
        if path.exists():
            return path
    return _run_path(run_id)


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


@router.post("/music")
def upload_music(file: UploadFile = File(...)) -> dict[str, Any]:
    filename = file.filename or "uploaded_music"
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_MUSIC_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Upload an audio file: mp3, wav, m4a, aac, ogg, or flac.")

    target_dir = _pipeline_data_dir() / "assets" / "music" / "uploads"
    target_dir.mkdir(parents=True, exist_ok=True)
    stem = re.sub(r"[^A-Za-z0-9_.-]+", "-", Path(filename).stem).strip(".-")[:60] or "music"
    target = target_dir / f"{stem}-{uuid4().hex[:8]}{suffix}"

    total = 0
    with target.open("wb") as handle:
        while True:
            chunk = file.file.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_MUSIC_UPLOAD_BYTES:
                handle.close()
                target.unlink(missing_ok=True)
                raise HTTPException(status_code=413, detail=f"Music upload is too large. Keep it under {MAX_MUSIC_UPLOAD_MB} MB.")
            handle.write(chunk)

    if total <= 0:
        target.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="Uploaded music file is empty.")

    return {
        "filename": target.name,
        "music_path": str(target.resolve()),
        "size_bytes": total,
    }


@router.get("/runs")
def list_runs() -> list[dict[str, Any]]:
    _runs_dir().mkdir(parents=True, exist_ok=True)
    runs_by_id: dict[str, dict[str, Any]] = {}
    for run in _list_runs_from_db():
        runs_by_id[str(run.get("id") or "")] = run
    paths = sorted(
        (path for root in _all_runs_dirs() for path in root.glob("*.json")),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )
    for path in paths:
        try:
            run = _read_run(path)
            runs_by_id[str(run["id"])] = {
                "id": run["id"],
                "user_message": run.get("user_message", ""),
                "status": run.get("status", "failed"),
                "created_at": run.get("created_at", ""),
                "updated_at": run.get("updated_at", ""),
            }
        except Exception as exc:
            broken = _broken_run_summary(path, exc)
            runs_by_id[str(broken["id"])] = broken
    runs = sorted(runs_by_id.values(), key=lambda run: str(run.get("updated_at") or run.get("created_at") or ""), reverse=True)
    return runs[:50]


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


@router.post("/runs/{run_id}/stages/{stage_id}/rerun")
def rerun_stage(run_id: str, stage_id: str, request: PlaygroundStageRerunRequest | None = None) -> dict[str, Any]:
    request = request or PlaygroundStageRerunRequest()
    parent = get_run(run_id)
    stage = _stage_by_id(parent, stage_id)
    if str(parent.get("status") or "") not in TERMINAL_STATUSES:
        raise HTTPException(status_code=409, detail="Wait for the current run to finish before rerunning a node.")

    target_agent = _target_agent_for_rerun(stage_id)
    stage_name = _display_stage_name(stage.get("agent_name") or stage_id)
    source_prompt = _source_prompt_from_parent(parent) or str(parent.get("effective_message") or parent.get("user_message") or "")
    message = request.message.strip() or f"Rerun the {stage_name} node for the existing video."
    instruction = (
        f"Rerun the {stage_name} stage for the existing video. Preserve the original topic, duration, genre, "
        "and every unrelated stage decision unless this node requires a dependent artifact to be rebuilt."
    )
    option_instruction = _stage_option_instruction(stage_id, request.settings_patch, request.forced_agent_instructions)
    if option_instruction:
        instruction = f"{instruction} {option_instruction}"
    forced_instructions = {target_agent: instruction}
    forced_instructions.update(
        {
            str(agent): str(text)
            for agent, text in (request.forced_agent_instructions or {}).items()
            if str(agent).strip() and str(text).strip()
        }
    )
    notes = "\n".join(
        part
        for part in (
            str(parent.get("notes") or "").strip(),
            f"NODE RERUN REQUEST: {instruction}",
            f"Previous run id: {parent.get('id', run_id)}",
            f"Previous stage status: {stage.get('status', '')}",
        )
        if part
    )
    payload = PlaygroundRunCreate(
        message=message,
        genre_id=str(parent.get("genre_id") or "scary_stories"),
        duration=int(parent.get("duration") or 30),
        notes=notes,
        llm_provider=str(parent.get("llm_provider") or "env"),
        llm_model=str(parent.get("llm_model") or ""),
        parent_run_id=str(parent.get("id") or run_id),
        music_path=_valid_music_path(request.music_path),
        chat_history=list(parent.get("chat_history") or []),
        rerun_stage_id=stage_id,
        forced_agent_instructions=forced_instructions,
        settings_patch=_clean_settings_patch(request.settings_patch),
    )
    if source_prompt:
        payload = payload.model_copy(update={"message": f"{message} Keep the original topic: {source_prompt}"})
    return create_run(payload)


@router.get("/runs/{run_id}")
def get_run(run_id: str) -> dict[str, Any]:
    db_run = _read_run_from_db(run_id)
    if db_run is not None:
        path = _existing_run_path(run_id)
        if path.exists():
            return _read_run(path)
        _refresh_run_from_pipeline_files(db_run)
        if db_run.get("status") in TERMINAL_STATUSES:
            final = _stage_by_id(db_run, "final_output")
            final["output_json"].update(_final_output_json(db_run))
            final["artifacts"] = _collect_final_artifacts(db_run)
        return db_run
    path = _existing_run_path(run_id)
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


def _playground_route(payload: PlaygroundRunCreate) -> dict[str, Any]:
    parent = _parent_run_context(payload.parent_run_id)
    current_settings = _current_settings_from_parent(parent, payload)
    parameter_patch, edit_like = _parameter_feedback(payload.message, current_settings)
    forced_instructions = {
        str(agent): str(text)
        for agent, text in (payload.forced_agent_instructions or {}).items()
        if str(agent).strip() and str(text).strip()
    }
    forced_target = _target_agent_for_rerun(payload.rerun_stage_id) if payload.rerun_stage_id else ""
    is_followup = bool(parent and (forced_target or _should_use_parent_context(payload.message, parameter_patch, edit_like)))
    settings_patch = dict(parameter_patch.get("settings_patch") or {}) if is_followup else {}
    manual_settings_patch = _clean_settings_patch(payload.settings_patch)
    if is_followup and manual_settings_patch:
        settings_patch.update(manual_settings_patch)
    agent_instructions = dict(parameter_patch.get("agent_instructions") or {}) if is_followup else {}
    target_agent = str(parameter_patch.get("target_agent") or "")
    if forced_target:
        target_agent = forced_target
    if forced_instructions:
        agent_instructions.update(forced_instructions)

    music_path = _valid_music_path(payload.music_path)
    if not music_path and is_followup:
        music_path = _valid_music_path(str((parent.get("settings") or {}).get("music_path") or ""))

    if is_followup and not settings_patch and not agent_instructions:
        target_agent = "script_agent"
        agent_instructions["script_agent"] = (
            "Apply the user's follow-up feedback to the script while preserving the original source prompt and named subject. "
            "Do not treat the follow-up complaint as a new video topic."
        )

    source_prompt = _source_prompt_from_parent(parent) if is_followup else _strip_duration_instruction(payload.message)
    source_prompt = source_prompt or _strip_duration_instruction(payload.message)
    effective_duration = _safe_duration(int(
        settings_patch.get("duration")
        or _duration_from_text(payload.message)
        or (parent.get("duration") if is_followup else None)
        or _safe_duration(payload.duration)
    ))
    notes = _route_notes(payload, parent, is_followup, agent_instructions)
    feedback = _strip_duration_instruction(payload.message) or payload.message
    display_message = f"Fix: {_clip(feedback, 90)} -> {_clip(source_prompt, 90)}" if is_followup else source_prompt
    genre = _genre_for(payload.genre_id)
    route_summary = (
        f"{genre['display_name']} remake for: {source_prompt}"
        if is_followup
        else f"{genre['display_name']} pipeline run for: {source_prompt}"
    )
    repair_notes = [
        f"Original prompt: {source_prompt}",
        f"User follow-up feedback: {feedback}",
    ] if is_followup else []
    if target_agent:
        repair_notes.append(f"Target agent: {target_agent}")
    return {
        "intent": "edit_video" if is_followup else "new_video",
        "is_followup": is_followup,
        "parent_run_id": str(parent.get("id") or "") if is_followup else "",
        "rerun_stage_id": payload.rerun_stage_id if forced_target else "",
        "effective_message": source_prompt,
        "source_prompt": source_prompt,
        "display_message": display_message,
        "effective_duration": effective_duration,
        "notes": notes,
        "target_agent": target_agent,
        "settings_patch": settings_patch,
        "music_path": music_path,
        "agent_instructions": agent_instructions,
        "repair_notes": repair_notes,
        "route_summary": route_summary,
    }


def _target_agent_for_rerun(stage_id: str) -> str:
    stage_id = str(stage_id or "").strip()
    if stage_id in {
        "topic_discovery_agent",
        "research_agent",
        "script_agent",
        "audio_agent",
        "caption_agent",
        "timed_visual_agent",
        "asset_agent",
        "music_agent",
        "render_agent",
        "thumbnail_agent",
    }:
        return stage_id
    if stage_id == "validation_agent":
        return "validation_agent"
    return "master_agent"


def _stage_option_instruction(
    stage_id: str,
    settings_patch: dict[str, Any],
    forced_agent_instructions: dict[str, str],
) -> str:
    settings = _clean_settings_patch(settings_patch)
    bits: list[str] = []
    if settings:
        rendered = ", ".join(f"{key}={value}" for key, value in settings.items())
        bits.append(f"Apply these playground options: {rendered}.")
    extra = "; ".join(str(text).strip() for text in (forced_agent_instructions or {}).values() if str(text).strip())
    if extra:
        bits.append(f"Additional node instruction: {extra}")
    if stage_id == "render_agent" and any(key in settings for key in {"visual_motion", "transition_style", "transition_seconds", "zoom_variant"}):
        bits.append("Use the selected render animation settings during the FFmpeg render.")
    return " ".join(bits)


def _clean_settings_patch(settings_patch: dict[str, Any] | None) -> dict[str, Any]:
    source = settings_patch if isinstance(settings_patch, dict) else {}
    cleaned: dict[str, Any] = {}
    if "voice_speed" in source:
        cleaned["voice_speed"] = round(_clamp_float(source.get("voice_speed"), 1.0, 0.65, 1.4), 2)
    if "caption_words" in source:
        cleaned["caption_words"] = int(_clamp_int(source.get("caption_words"), 4, 1, 8))
    if "image_count" in source:
        cleaned["image_count"] = int(_clamp_int(source.get("image_count"), 8, 1, 24))
    if "music_volume" in source:
        cleaned["music_volume"] = round(_clamp_float(source.get("music_volume"), 0.12, 0.0, 0.8), 2)
    if "min_visual_segment_ms" in source:
        cleaned["min_visual_segment_ms"] = int(_clamp_int(source.get("min_visual_segment_ms"), 3500, 1200, 8000))
    if "visual_motion" in source:
        cleaned["visual_motion"] = _as_bool(source.get("visual_motion"), True)
    if "transition_style" in source:
        style = str(source.get("transition_style") or "").strip().lower()
        aliases = {"slides": "slide", "none": "cut", "off": "cut"}
        cleaned["transition_style"] = aliases.get(style, style) if aliases.get(style, style) in TRANSITION_STYLES else "slide"
    if "transition_seconds" in source:
        cleaned["transition_seconds"] = round(_clamp_float(source.get("transition_seconds"), 0.45, 0.0, 1.2), 2)
    if "zoom_variant" in source:
        variant = str(source.get("zoom_variant") or "").strip().lower()
        aliases = {"alternate": "mixed", "center": "mixed", "in": "center_in", "out": "center_out", "none": "still", "off": "still"}
        cleaned["zoom_variant"] = aliases.get(variant, variant) if aliases.get(variant, variant) in ZOOM_VARIANTS else "mixed"
    if cleaned.get("visual_motion") is False and "zoom_variant" not in cleaned:
        cleaned["zoom_variant"] = "still"
    return cleaned


def _clamp_float(value: Any, default: float, minimum: float, maximum: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    return max(minimum, min(maximum, number))


def _clamp_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return max(minimum, min(maximum, number))


def _as_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value or "").strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return default


def _display_stage_name(value: str) -> str:
    return str(value or "").replace("_", " ").strip().title() or "Selected"


def _parameter_feedback(message: str, current_settings: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    fallback_patch = _fallback_parameter_patch(message)
    fallback_edit_like = _looks_like_edit_text(message)
    try:
        from desktop_pipeline.parameter_agent import looks_like_edit_request, map_parameter_request

        patch = map_parameter_request(message, current_settings).to_dict()
        edit_like = bool(looks_like_edit_request(message))
        return patch, edit_like or bool(patch.get("settings_patch") or patch.get("agent_instructions") or patch.get("target_agent"))
    except Exception:
        return fallback_patch, fallback_edit_like or bool(fallback_patch.get("agent_instructions"))


def _should_use_parent_context(message: str, parameter_patch: dict[str, Any], edit_like: bool) -> bool:
    if parameter_patch.get("settings_patch") or parameter_patch.get("agent_instructions") or parameter_patch.get("target_agent"):
        return True
    if _looks_like_new_video_request(message):
        return False
    return edit_like


def _looks_like_new_video_request(message: str) -> bool:
    text = " ".join(str(message or "").lower().split())
    return bool(
        re.search(r"\b(?:make|create|generate)\s+(?:a\s+|an\s+)?(?:new\s+)?(?:video|short|reel)\s+(?:on|about|for)\b", text)
        or re.search(r"\b(?:video|short|reel)\s+(?:on|about)\b", text)
    )


def _fallback_parameter_patch(message: str) -> dict[str, Any]:
    text = " ".join(str(message or "").lower().split())
    if _mentions_any(text, "script", "story", "narration", "hook", "writing", "plot", "content") and _mentions_any(
        text,
        "bad",
        "wrong",
        "random",
        "unusual",
        "weird",
        "generic",
        "boring",
        "better",
        "improve",
        "not good",
        "look good",
        "doesnt",
        "doesn't",
        "does not",
        "off topic",
        "unrelated",
    ):
        return {
            "target_agent": "script_agent",
            "settings_patch": {},
            "agent_instructions": {
                "script_agent": (
                    "Regenerate the script around the original source prompt. Keep the same named subject, "
                    "remove random or unrelated beats, and use a fresh coherent angle."
                )
            },
            "reason": "script quality or topic alignment needs repair",
        }
    return {"target_agent": "", "settings_patch": {}, "agent_instructions": {}, "reason": ""}


def _looks_like_edit_text(message: str) -> bool:
    text = " ".join(str(message or "").lower().split())
    return _mentions_any(
        text,
        "change",
        "fix",
        "remake",
        "redo",
        "again",
        "too",
        "less",
        "more",
        "faster",
        "slower",
        "loud",
        "quiet",
        "bad",
        "wrong",
        "not good",
        "same",
        "repeat",
        "random",
        "unusual",
        "weird",
        "generic",
        "boring",
        "better",
        "improve",
        "off topic",
        "doesnt",
        "doesn't",
    )


def _mentions_any(text: str, *needles: str) -> bool:
    return any(needle in text for needle in needles)


def _parent_run_context(run_id: str) -> dict[str, Any]:
    run_id = str(run_id or "").strip()
    if not run_id or not re.fullmatch(r"[A-Za-z0-9_-]{1,90}", run_id):
        return {}
    path = _existing_run_path(run_id)
    if path.exists():
        try:
            run = _read_run_raw(path)
            _sanitize_run(run)
            return run if isinstance(run, dict) else {}
        except Exception:
            return {}
    run = _read_run_from_db(run_id)
    return run or {}


def _current_settings_from_parent(parent: dict[str, Any], payload: PlaygroundRunCreate) -> dict[str, Any]:
    settings = dict(DEFAULT_PLAYGROUND_SETTINGS)
    settings["duration"] = parent.get("duration") or payload.duration
    for source in (parent.get("settings") or {}, parent.get("settings_patch") or {}):
        if isinstance(source, dict):
            settings.update(_clean_settings_patch(source))
            if source.get("duration") is not None:
                settings["duration"] = source.get("duration")
            if source.get("music_path"):
                settings["music_path"] = _valid_music_path(str(source.get("music_path") or ""))
    if payload.music_path:
        settings["music_path"] = _valid_music_path(payload.music_path)
    return settings


def _valid_music_path(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    path = _resolve_existing_path(Path(raw))
    music_root = (_pipeline_data_dir() / "assets" / "music").expanduser().resolve()
    if not path.exists() or not path.is_file():
        return ""
    if path.suffix.lower() not in ALLOWED_MUSIC_EXTENSIONS:
        return ""
    try:
        path.relative_to(music_root)
    except ValueError:
        return ""
    return str(path)


def _source_prompt_from_parent(parent: dict[str, Any]) -> str:
    candidates = (
        parent.get("source_prompt"),
        parent.get("effective_message"),
        parent.get("user_message"),
        parent.get("raw_user_message"),
    )
    for value in candidates:
        text = _strip_duration_instruction(str(value or ""))
        if text and not text.lower().startswith("fix:"):
            return text
    return ""


def _route_notes(
    payload: PlaygroundRunCreate,
    parent: dict[str, Any],
    is_followup: bool,
    agent_instructions: dict[str, str],
) -> str:
    parts = [payload.notes.strip()] if payload.notes.strip() else []
    if not is_followup:
        return "\n\n".join(parts)

    source_prompt = _source_prompt_from_parent(parent)
    feedback = payload.message.strip()
    context_lines = [
        "FOLLOW-UP EDIT CONTEXT:",
        f"- Original source prompt to preserve: {source_prompt}",
        f"- Latest user feedback: {feedback}",
        "- Keep the same topic, named subject, genre, and duration unless this feedback explicitly changes them.",
        "- Treat the feedback as repair instructions, not as the new video topic.",
    ]
    if agent_instructions:
        instruction_text = "; ".join(f"{agent}: {text}" for agent, text in agent_instructions.items() if str(text).strip())
        if instruction_text:
            context_lines.append(f"- Targeted agent repair: {instruction_text}")
    previous_script = _previous_script_excerpt(parent)
    if previous_script:
        context_lines.extend(
            [
                "",
                "PREVIOUS SCRIPT CONTEXT ONLY:",
                "Use this to understand what the user is reacting to. Do not copy this failed wording.",
                previous_script,
            ]
        )
    parts.append("\n".join(context_lines))
    return "\n\n".join(parts)


def _previous_script_excerpt(run: dict[str, Any]) -> str:
    for stage in run.get("stages", []) or []:
        if not isinstance(stage, dict) or stage.get("id") != "script_agent":
            continue
        output = stage.get("output_json") if isinstance(stage.get("output_json"), dict) else {}
        title = _clip(str(output.get("title") or ""), 140)
        narration = _clip(str(output.get("narration") or ""), 1400)
        if title or narration:
            return "\n".join(part for part in (f"Title: {title}" if title else "", f"Narration excerpt: {narration}" if narration else "") if part)
    return ""


def _compact_chat_history(history: list[dict[str, Any]] | None) -> list[dict[str, str]]:
    compact: list[dict[str, str]] = []
    for item in (history or [])[-12:]:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "").strip()[:30]
        content = _clip(str(item.get("content") or ""), 500)
        if role and content:
            compact.append({"role": role, "content": content})
    return compact


def _clip(text: str, limit: int) -> str:
    cleaned = " ".join(str(text or "").split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: max(0, limit - 3)].rstrip() + "..."


def _build_initial_run(payload: PlaygroundRunCreate) -> dict[str, Any]:
    now = _now()
    run_id = str(uuid4())
    genre = _genre_for(payload.genre_id)
    route = _playground_route(payload)
    effective_message = str(route["effective_message"])
    effective_duration = int(route["effective_duration"])
    parent_context = _parent_run_context(str(route.get("parent_run_id") or payload.parent_run_id))
    effective_settings = _current_settings_from_parent(parent_context, payload)
    effective_settings.update(_clean_settings_patch(route.get("settings_patch") if isinstance(route.get("settings_patch"), dict) else {}))
    effective_settings["duration"] = effective_duration
    effective_settings["music_path"] = str(route.get("music_path") or "")
    route_summary = str(route["route_summary"])
    intent = str(route["intent"])
    stages = [_initial_stage(stage, now) for stage in VISIBLE_STAGES]
    stages[0] = _mark_stage_dict(
        stages[0],
        "succeeded",
        now,
        input_json={
            "chat_message": payload.message,
            "genre_id": genre["genre_id"],
            "notes": payload.notes,
            "parent_run_id": payload.parent_run_id,
            "chat_history": _compact_chat_history(payload.chat_history),
        },
        output_json={
            "intent": intent,
            "target_agent": "final_pipeline",
            "parent_run_id": route.get("parent_run_id", ""),
            "source_prompt": route.get("source_prompt", ""),
            "planned_agents": [stage["id"] for stage in VISIBLE_STAGES[3:]],
        },
        message="Playground routed this as a follow-up edit run" if route["is_followup"] else "Playground routed this as a new final-pipeline video run",
    )
    stages[1] = _mark_stage_dict(
        stages[1],
        "skipped",
        now,
        output_json={"reason": "Style sampling only runs during desktop calibration."},
        message="Skipped for direct playground generation",
    )
    if route["is_followup"]:
        stages[2] = _mark_stage_dict(
            stages[2],
            "succeeded",
            now,
            input_json={
                "message": payload.message,
                "parent_run_id": route.get("parent_run_id", ""),
                "previous_topic": route.get("source_prompt", ""),
                "chat_history": _compact_chat_history(payload.chat_history),
            },
            output_json={
                "intent": intent,
                "target_agent": route.get("target_agent", ""),
                "settings_patch": route.get("settings_patch", {}),
                "agent_instructions": route.get("agent_instructions", {}),
                "repair_notes": route.get("repair_notes", []),
            },
            message="Mapped follow-up feedback into repair notes for the responsible agent",
        )
    else:
        stages[2] = _mark_stage_dict(
            stages[2],
            "skipped",
            now,
            output_json={"reason": "Parameter mapping only runs for follow-up edit/remake prompts."},
            message="Skipped because this is a new generation request",
        )
    stages[3] = _mark_stage_dict(
        stages[3],
        "running",
        now,
        input_json=_safe_payload(payload),
        output_json={
            "route_summary": route_summary,
            "genre_id": genre["genre_id"],
            "duration": effective_duration,
            "raw_message": payload.message,
            "cleaned_message": effective_message,
            "source_prompt": route.get("source_prompt", ""),
            "parent_run_id": route.get("parent_run_id", ""),
            "settings_patch": route.get("settings_patch", {}),
            "settings": effective_settings,
            "music_path": route.get("music_path", ""),
            "agent_instructions": route.get("agent_instructions", {}),
            "selected_provider": payload.llm_provider,
            "selected_model": payload.llm_model or "environment default",
        },
        message="Playground run accepted",
    )
    return {
        "schema_version": RUN_SCHEMA_VERSION,
        "id": run_id,
        "user_message": str(route["display_message"]),
        "effective_message": effective_message,
        "source_prompt": str(route.get("source_prompt") or effective_message),
        "raw_user_message": payload.message,
        "parent_run_id": str(route.get("parent_run_id") or ""),
        "intent": intent,
        "genre_id": genre["genre_id"],
        "duration": effective_duration,
        "notes": str(route["notes"]),
        "settings_patch": route.get("settings_patch", {}),
        "settings": effective_settings,
        "music_path": str(route.get("music_path") or ""),
        "agent_instructions": route.get("agent_instructions", {}),
        "chat_history": _compact_chat_history(payload.chat_history),
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
        _update_run(run_id, lambda run: _mark_stage(run, "master_agent", "succeeded", "Shared final pipeline process is starting"))
        env = _pipeline_env(payload)
        route = _playground_route(payload)
        cmd = [
            sys.executable,
            "main.py",
            "--topic",
            str(route["effective_message"]),
            "--genre",
            payload.genre_id,
            "--duration",
            str(route["effective_duration"]),
        ]
        if route.get("source_prompt"):
            cmd.extend(["--source-prompt", str(route["source_prompt"])])
        if route.get("notes"):
            cmd.extend(["--notes", str(route["notes"])])
        settings_patch = route.get("settings_patch") if isinstance(route.get("settings_patch"), dict) else {}
        settings_for_cmd = _current_settings_from_parent(_parent_run_context(str(route.get("parent_run_id") or payload.parent_run_id)), payload)
        settings_for_cmd.update(_clean_settings_patch(settings_patch))
        if settings_for_cmd.get("voice_speed") is not None:
            cmd.extend(["--voice-speed", str(settings_for_cmd["voice_speed"])])
        if settings_for_cmd.get("caption_words") is not None:
            cmd.extend(["--caption-words", str(settings_for_cmd["caption_words"])])
        if settings_for_cmd.get("image_count") is not None:
            cmd.extend(["--image-count", str(settings_for_cmd["image_count"])])
        music_path = _valid_music_path(str(route.get("music_path") or settings_for_cmd.get("music_path") or payload.music_path or ""))
        if music_path:
            cmd.extend(["--music-path", music_path])
        if settings_for_cmd.get("music_volume") is not None:
            cmd.extend(["--music-volume", str(settings_for_cmd["music_volume"])])
        if settings_for_cmd.get("min_visual_segment_ms") is not None:
            cmd.extend(["--min-visual-segment-ms", str(settings_for_cmd["min_visual_segment_ms"])])
        if settings_for_cmd.get("visual_motion") is not None:
            cmd.extend(["--visual-motion", "on" if settings_for_cmd["visual_motion"] else "off"])
        if settings_for_cmd.get("transition_style") is not None:
            cmd.extend(["--transition-style", str(settings_for_cmd["transition_style"])])
        if settings_for_cmd.get("transition_seconds") is not None:
            cmd.extend(["--transition-seconds", str(settings_for_cmd["transition_seconds"])])
        if settings_for_cmd.get("zoom_variant") is not None:
            cmd.extend(["--zoom-variant", str(settings_for_cmd["zoom_variant"])])
        agent_instructions = route.get("agent_instructions") if isinstance(route.get("agent_instructions"), dict) else {}
        if agent_instructions:
            cmd.extend(["--agent-instructions-json", json.dumps(agent_instructions, ensure_ascii=True)])
        if route.get("rerun_stage_id"):
            parent = _parent_run_context(str(route.get("parent_run_id") or payload.parent_run_id))
            parent_run_dir = _resolve_existing_path(Path(str(parent.get("pipeline_run_dir") or "")))
            if not parent_run_dir.exists():
                raise RuntimeError("Cannot rerun this node because the parent pipeline artifacts are missing.")
            cmd.extend([
                "--resume-from-run-dir",
                str(parent_run_dir),
                "--rerun-stage",
                str(route["rerun_stage_id"]),
            ])

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
    visible_stage = _visible_stage_for_pipeline_stage(str(error.get("stage") or ""))
    message = str(error.get("message") or fallback_message)
    if not visible_stage:
        visible_stage = _current_or_first_unfinished_stage(run)
    _fail_run(run, visible_stage, message, error)


def _visible_stage_for_pipeline_stage(stage: str) -> str:
    if stage in PIPELINE_STAGE_TO_VISIBLE:
        return PIPELINE_STAGE_TO_VISIBLE[stage]
    normalized = re.sub(r"_repair_\d+$", "", stage)
    if normalized in PIPELINE_STAGE_TO_VISIBLE:
        return PIPELINE_STAGE_TO_VISIBLE[normalized]
    if normalized.startswith("validate_"):
        return "validation_agent"
    return ""


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
    run_dir = _resolve_existing_path(Path(run_dir_text))
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
                stage["status"] = "skipped" if stage["output_json"].get("status") == "skipped" else "succeeded"
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
    error_stage = re.sub(r"_repair_\d+$", "", str(error.get("stage") or "")) if isinstance(error, dict) else ""
    if isinstance(error, dict) and error_stage in {validation_stage, f"{validation_stage}_result"}:
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
        paths.extend(Path(path) for path in output_json.get("sfx_paths", []) if path)
        paths.extend(Path(path) for path in output_json.get("video_paths", []) if path)
        paths.extend(Path(path) for path in output_json.get("media_paths", []) if path)
    elif stage_id == "audio_agent":
        paths.extend(Path(path) for path in (output_json.get("narration_path"), output_json.get("final_audio_path")) if path)
    elif stage_id == "music_agent":
        paths.extend(Path(path) for path in (output_json.get("input_audio_path"), output_json.get("final_audio_path"), output_json.get("music_path")) if path)
        paths.extend(Path(path) for path in output_json.get("sfx_paths", []) if path)
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
                run_dir / "intermediate" / "audio" / "final_audio_with_music.wav",
                run_dir / "output" / "thumbnails" / "shorts_cover.jpg",
                run_dir / "output" / "thumbnails" / "youtube_thumbnail.jpg",
                run_dir / "logs" / "timed_visual_agent" / "timed_visual_cues.json",
                run_dir / "logs" / "asset_agent" / "asset_selection_trace.json",
                run_dir / "errors" / "error.json",
            ]
        )
    for stage_id, keys in {
        "render_agent": ("video_path",),
        "thumbnail_agent": ("shorts_cover_path", "youtube_thumbnail_path"),
        "asset_agent": ("asset_trace_path", "timed_visual_cues_path"),
        "music_agent": ("final_audio_path", "music_path"),
    }.items():
        output = _stage_output_json(run, stage_id)
        paths.extend(Path(str(output.get(key))) for key in keys if output.get(key))
        if stage_id == "music_agent":
            paths.extend(Path(str(path)) for path in output.get("sfx_paths", []) if path)
    return _artifact_list(paths)


def _final_output_json(run: dict[str, Any]) -> dict[str, Any]:
    run_dir_text = str(run.get("pipeline_run_dir") or "")
    run_dir = Path(run_dir_text) if run_dir_text else None
    final_video = run_dir / "output" / "final.mp4" if run_dir else None
    video_path = ""
    if final_video and _resolve_existing_path(final_video).exists():
        video_path = str(final_video)
    else:
        video_path = str(_stage_output_json(run, "render_agent").get("video_path") or "")
    return {
        "status": run.get("status", "running"),
        "pipeline_run_dir": run_dir_text,
        "video_path": video_path,
        "stdout_path": run.get("stdout_path", ""),
        "returncode": run.get("returncode"),
    }


def _stage_output_json(run: dict[str, Any], stage_id: str) -> dict[str, Any]:
    try:
        stage = _stage_by_id(run, stage_id)
    except KeyError:
        return {}
    output = stage.get("output_json")
    return output if isinstance(output, dict) else {}


def _artifact_list(paths: list[Path]) -> list[dict[str, Any]]:
    artifacts: list[dict[str, Any]] = []
    seen: set[str] = set()
    for path in paths:
        try:
            resolved = _resolve_existing_path(path)
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
    path = _existing_run_path(str(run["id"]))
    if not path.exists():
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
    _save_run_to_db(run)


def _list_runs_from_db() -> list[dict[str, Any]]:
    try:
        from sqlalchemy import select

        from app.core.database import SessionLocal
        from app.models import AgentRunSnapshot

        with SessionLocal() as db:
            rows = db.scalars(
                select(AgentRunSnapshot)
                .where(AgentRunSnapshot.surface == "playground")
                .order_by(AgentRunSnapshot.updated_at.desc())
                .limit(50)
            ).all()
            return [
                {
                    "id": row.id,
                    "user_message": row.user_message,
                    "status": row.status,
                    "created_at": row.created_at.isoformat() if row.created_at else "",
                    "updated_at": row.updated_at.isoformat() if row.updated_at else "",
                }
                for row in rows
            ]
    except Exception:
        return []


def _read_run_from_db(run_id: str) -> dict[str, Any] | None:
    try:
        from app.core.database import SessionLocal
        from app.models import AgentRunSnapshot

        with SessionLocal() as db:
            row = db.get(AgentRunSnapshot, run_id)
            if row is None or row.surface != "playground":
                return None
            payload = row.payload_json if isinstance(row.payload_json, dict) else {}
            if not payload:
                return None
            payload = dict(payload)
            payload.setdefault("id", row.id)
            payload.setdefault("status", row.status)
            payload.setdefault("user_message", row.user_message)
            payload.setdefault("genre_id", row.genre_id)
            payload.setdefault("pipeline_run_dir", row.pipeline_run_dir)
            return payload
    except Exception:
        return None


def _save_run_to_db(run: dict[str, Any]) -> None:
    try:
        from app.core.database import SessionLocal
        from app.models import AgentRunSnapshot

        with SessionLocal() as db:
            row = db.get(AgentRunSnapshot, str(run["id"]))
            if row is None:
                row = AgentRunSnapshot(id=str(run["id"]), surface="playground")
                db.add(row)
            row.user_message = str(run.get("user_message") or run.get("raw_user_message") or "")
            row.genre_id = str(run.get("genre_id") or "")
            row.status = str(run.get("status") or "running")
            row.pipeline_run_dir = str(run.get("pipeline_run_dir") or "")
            row.payload_json = run
            db.commit()
    except Exception:
        pass


def _update_run(run_id: str, updater) -> None:
    with _RUN_LOCK:
        path = _existing_run_path(run_id)
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
            "desktop_master_agent",
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
    data["chat_history"] = _compact_chat_history(payload.chat_history)
    route = _playground_route(payload)
    data["effective_message"] = route["effective_message"]
    data["effective_duration"] = route["effective_duration"]
    data["intent"] = route["intent"]
    data["source_prompt"] = route["source_prompt"]
    data["settings_patch"] = route["settings_patch"]
    data["settings"] = {
        **_current_settings_from_parent(_parent_run_context(str(route.get("parent_run_id") or payload.parent_run_id)), payload),
        **_clean_settings_patch(route["settings_patch"] if isinstance(route["settings_patch"], dict) else {}),
    }
    data["settings"]["music_path"] = str(route.get("music_path") or "")
    data["music_path"] = str(route.get("music_path") or "")
    data["agent_instructions"] = route["agent_instructions"]
    return data


def _effective_duration(payload: PlaygroundRunCreate) -> int:
    return int(_playground_route(payload)["effective_duration"])


def _effective_message(payload: PlaygroundRunCreate) -> str:
    return str(_playground_route(payload)["effective_message"])


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
    path = _resolve_existing_path(Path(raw))
    allowed = [
        *_all_runs_dirs(),
        _pipeline_data_dir(),
        _pipeline_output_runs_dir(),
        _legacy_pipeline_output_runs_dir(),
    ]
    if any(_is_relative_to(path, root.resolve()) for root in allowed):
        return path
    return None


def _resolve_existing_path(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    if resolved.exists():
        return resolved
    raw = str(path)
    remaps = (
        ("/app/playground/data/runs", _legacy_runs_dir()),
        ("/app/data/playground/runs", _runs_dir()),
        ("/app/playground/data/pipeline", _pipeline_data_dir()),
    )
    for prefix, root in remaps:
        if raw == prefix or raw.startswith(prefix + "/"):
            suffix = raw[len(prefix) :].lstrip("/")
            candidate = (root / suffix).expanduser().resolve()
            if candidate.exists():
                return candidate
    return resolved


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False
