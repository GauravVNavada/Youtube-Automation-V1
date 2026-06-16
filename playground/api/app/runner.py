from __future__ import annotations

import json
import mimetypes
import os
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import PlaygroundArtifact, PlaygroundEvent, PlaygroundRun, PlaygroundStage, utc_now
from app.schemas import RunCreate
from app.settings import get_settings


AGENTS = [
    "master_agent",
    "topic_discovery_agent",
    "research_agent",
    "script_agent",
    "validation_agent",
    "asset_agent",
    "audio_agent",
    "caption_agent",
    "render_agent",
    "thumbnail_agent",
]

DEFAULT_AGENT_EXECUTION_MODES = {
    "master_agent": "deterministic",
    "topic_discovery_agent": "deterministic",
    "research_agent": "deterministic",
    "script_agent": "ai",
    "validation_agent": "deterministic",
    "asset_agent": "hybrid",
    "audio_agent": "deterministic",
    "caption_agent": "deterministic",
    "render_agent": "deterministic",
    "thumbnail_agent": "deterministic",
}

EXECUTION_MODE_PRIORITY = {
    "deterministic": 1,
    "fallback": 2,
    "ai": 3,
    "hybrid": 4,
}

LOG_MODULE_TO_AGENT = {
    "topic_discovery_agent": "topic_discovery_agent",
    "research_agent": "research_agent",
    "script_agent": "script_agent",
    "validation_agent": "validation_agent",
    "asset_agent": "asset_agent",
    "audio_agent": "audio_agent",
    "caption_agent": "caption_agent",
    "render_agent": "render_agent",
    "thumbnail_agent": "thumbnail_agent",
}

ERROR_STAGE_TO_AGENT = {
    "topic_discovery_agent": "topic_discovery_agent",
    "research_agent": "research_agent",
    "script_agent": "script_agent",
    "validate_script": "validation_agent",
    "validate_script_result": "validation_agent",
    "asset_agent": "asset_agent",
    "validate_assets": "validation_agent",
    "validate_assets_result": "validation_agent",
    "audio_agent": "audio_agent",
    "validate_audio": "validation_agent",
    "validate_audio_result": "validation_agent",
    "caption_agent": "caption_agent",
    "validate_captions": "validation_agent",
    "validate_captions_result": "validation_agent",
    "render_agent": "render_agent",
    "validate_render": "validation_agent",
    "validate_render_result": "validation_agent",
    "thumbnail_agent": "thumbnail_agent",
}

PROMPT_FILES = {
    "script_agent": "agents/prompts/script_prompts.py",
    "validation_agent": "agents/prompts/validation_prompts.py",
    "asset_agent": "agents/prompts/asset_prompts.py",
}

GENERIC_MESSAGES = {"hi", "hello", "hey", "how are you", "what are you doing", "what can you do", "thanks", "thank you"}
EXECUTOR = ThreadPoolExecutor(max_workers=2)

LLM_MODEL_OPTIONS = {
    "openai": ["gpt-4o-mini", "gpt-4o", "gpt-4.1-mini", "gpt-4.1"],
    "anthropic": [
        "claude-3-5-haiku-20241022",
        "claude-3-5-sonnet-20241022",
        "claude-3-7-sonnet-20250219",
        "claude-sonnet-4-20250514",
    ],
    "gemini": ["gemini-2.5-flash", "gemini-2.5-pro", "gemini-1.5-flash", "gemini-1.5-pro"],
    "groq": ["openai/gpt-oss-20b", "llama-3.3-70b-versatile", "llama-3.1-8b-instant", "llama3-70b-8192", "mixtral-8x7b-32768"],
}

MODEL_ENV_MAP = {
    "openai": "OPENAI_MODEL",
    "anthropic": "ANTHROPIC_MODEL",
    "gemini": "GEMINI_MODEL",
    "groq": "GROQ_MODEL",
}

KEY_ENV_MAP = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "groq": "GROQ_API_KEY",
}


def create_playground_run(db: Session, payload: RunCreate) -> PlaygroundRun:
    route = decide_route(
        payload.message,
        genre_id=payload.genre_id,
        llm_provider=payload.llm_provider,
        llm_model=payload.llm_model,
        has_api_key=bool(payload.llm_api_key.strip()),
    )
    run = PlaygroundRun(user_message=payload.message, route_summary=route["summary"], status="running")
    db.add(run)
    db.flush()
    _create_stage(
        db,
        run,
        "master_agent",
        0,
        status="succeeded",
        input_json={
            "message": payload.message,
            "genre_id": payload.genre_id,
            "llm_provider": payload.llm_provider,
            "llm_model": payload.llm_model,
            "has_api_key": bool(payload.llm_api_key.strip()),
        },
        prompt_text=_master_prompt(),
        output_json=route,
    )
    db.add(
        PlaygroundEvent(
            run_id=run.id,
            stage_id=_stage_by_agent(db, run.id, "master_agent").id,
            level="info",
            message="Master agent routed the message",
            payload_json=_provenance_payload(
                "deterministic",
                route,
                method="rule-based request routing",
            ),
        )
    )

    if route["action"] != "generate_video":
        run.status = "succeeded"
        run.updated_at = utc_now()
        db.commit()
        db.refresh(run)
        return run

    for index, agent in enumerate(AGENTS[1:], start=1):
        _create_stage(
            db,
            run,
            agent,
            index,
            status="pending",
            prompt_text=prompt_text_for_agent(agent),
        )
    db.commit()
    db.refresh(run)
    EXECUTOR.submit(run_pipeline_job, run.id, route, payload.llm_api_key.strip())
    return run


def decide_route(
    message: str,
    genre_id: str = "scary_stories",
    llm_provider: str = "env",
    llm_model: str = "",
    has_api_key: bool = False,
) -> dict[str, Any]:
    normalized = " ".join(message.strip().split())
    lower = normalized.lower()
    cleaned = re.sub(r"[^a-z\s]", "", lower).strip()
    if cleaned in GENERIC_MESSAGES:
        return {
            "action": "conversation",
            "summary": "Generic chat handled by master_agent only",
            "response": "Hi. This playground is ready to test agent routing. Send a concrete video request to see the full graph.",
            "agents": ["master_agent"],
        }
    if not _looks_like_generation(lower):
        return {
            "action": "ask_clarifying_question",
            "summary": "Master agent asked for a concrete video request",
            "response": "Give me a concrete short-video request, for example: make a 15 sec scary story about a sealed exam paper leak.",
            "agents": ["master_agent"],
        }

    duration = _extract_duration(lower)
    settings = _extract_settings(lower, duration)
    topic = _extract_topic(normalized)
    if len(topic.split()) < 3 and _has_generation_subject_signal(lower):
        topic = normalized
    if len(topic.split()) < 3:
        return {
            "action": "ask_clarifying_question",
            "summary": "Master agent rejected a vague generation request",
            "response": "I need one clear topic detail before running the full pipeline.",
            "agents": ["master_agent"],
        }
    genre = _normalize_genre(genre_id, lower)
    provider = _normalize_provider(llm_provider)
    model = _normalize_model(provider, llm_model)
    constraints = _playground_constraints(genre, duration, settings)
    contracts = _playground_agent_contracts(constraints)
    return {
        "action": "generate_video",
        "summary": f"Full pipeline route for a {duration}s {genre} video",
        "topic": topic,
        "genre": genre,
        "duration": duration,
        "settings": settings,
        "constraints": constraints,
        "agent_contracts": contracts,
        "llm_provider": provider,
        "llm_model": model,
        "has_user_api_key": has_api_key,
        "notes": (
            "Playground run: expose every agent input, prompt, output, log, error, and artifact for debugging.\n"
            f"Master constraints JSON: {json.dumps(constraints, ensure_ascii=True)}\n"
            "Required execution order: Master decides route and constraints; Topic discovery and research enrich the idea; "
            "Script writes within constraints and growth context; Script self-checks; Validation checks; invalid scripts "
            "auto-repair; assets/audio/captions/render follow; thumbnail generation finishes the run."
        ),
        "agents": AGENTS,
    }


def _playground_constraints(genre: str, duration: int, settings: dict[str, Any]) -> dict[str, Any]:
    min_words = max(18, int(duration * 1.75))
    max_words = max(min_words + 8, int(duration * 2.55))
    if duration < 30:
        max_words += 5
    image_count = max(int(settings.get("image_count") or 8), _minimum_image_cues(duration))
    return {
        "genre_id": genre,
        "duration_seconds": duration,
        "narration_word_count": {"min": min_words, "max": max_words},
        "image_count": image_count,
        "voice_speed_multiplier": float(settings.get("voice_speed") or 1.0),
        "caption_words_per_phrase": int(settings.get("caption_words") or 4),
        "music_volume": float(settings.get("music_volume") or 0.18),
        "script_format": "strict JSON object only",
        "asset_policy": "stock video b-roll preferred with Pexels/Pixabay/Openverse/Wikimedia/Bing image fallback; every cue needs concrete visible nouns",
        "audio_policy": "Google TTS when configured, otherwise free EdgeTTS fallback; Whisper word alignment remains required",
        "repair_policy": "script must pass self-check and validation before downstream agents run",
        "growth_policy": "free topic discovery and research run before script; thumbnail generation runs after render",
    }


def _playground_agent_contracts(constraints: dict[str, Any]) -> list[dict[str, Any]]:
    word_range = constraints["narration_word_count"]
    return [
        _contract(
            "master_agent",
            "Decides route, locks constraints, and chooses whether to chat, ask a question, or run generation.",
            ["message", "genre_id", "llm_provider", "llm_model", "settings"],
            ["action", "topic", "genre", "constraints", "agent_contracts"],
            ["Ask for clarification on vague topics.", "Never continue without locked constraints."],
        ),
        _contract(
            "topic_discovery_agent",
            "Creates topic angles from the user topic, local niche profiles, references, and no-key web signals.",
            ["topic", "genre", "reference_scripts", "niche_profile"],
            ["selected_topic", "selected_angle", "candidates", "source_errors"],
            ["Never require paid APIs.", "Continue with local candidates if web sources fail."],
        ),
        _contract(
            "research_agent",
            "Builds a compact source-backed brief for the selected angle using free/no-key sources.",
            ["selected_topic", "genre", "topic_candidates", "reference_scripts"],
            ["brief", "facts", "source_snippets", "source_errors"],
            ["Never block generation on web failure.", "Keep findings short enough for the script prompt."],
        ),
        _contract(
            "script_agent",
            "Writes title, narration, hook, image cues, SFX cues, and emphasis words as strict JSON.",
            ["topic", "genre", "duration", "reference_scripts", "user_notes", "growth_context"],
            ["title", "narration", "hook_line", "image_cues", "sfx_cues", "emphasis_words"],
            [
                f"Word count must be {word_range['min']}-{word_range['max']}.",
                f"Use at least {constraints['image_count']} concrete image cues.",
            ],
        ),
        _contract(
            "validation_agent",
            "Checks stage outputs and requests repair before downstream work starts.",
            ["stage_output", "constraints"],
            ["passed", "issues", "repair_notes"],
            ["Invalid scripts trigger auto-repair.", "Render must include playable audio."],
        ),
        _contract(
            "asset_agent",
            "Fetches online visuals and SFX from concrete cues.",
            ["image_cues", "sfx_cues", "provider_keys"],
            ["image_paths", "sfx_paths", "music_path", "sources"],
            ["Use reusable image cache when possible.", "Search concrete cue variants in parallel.", "Use Bing only as a free no-key fallback."],
        ),
        _contract(
            "audio_agent",
            "Generates online narrator TTS and Whisper word alignment.",
            ["narration", "duration", "voice_speed_multiplier", "google_tts_credentials"],
            ["final_audio_path", "word_timestamps", "audio_health"],
            [f"Voice speed {constraints['voice_speed_multiplier']}x.", "Prefer Google TTS; fall back to EdgeTTS.", "Protect first-word audio."],
        ),
        _contract(
            "caption_agent",
            "Builds synced SRT/ASS captions from audio timing.",
            ["word_timestamps", "caption_preset", "words_per_caption"],
            ["srt_path", "ass_path", "phrase_count"],
            [f"Use about {constraints['caption_words_per_phrase']} words per caption.", "Never invent timings."],
        ),
        _contract(
            "render_agent",
            "Composes the final vertical MP4.",
            ["assets", "audio", "captions", "music_volume"],
            ["video_path", "width", "height", "duration_seconds", "render_plan_json"],
            ["Write output/render_plan.json.", "Render 1080x1920.", f"Music volume {constraints['music_volume']}."],
        ),
        _contract(
            "thumbnail_agent",
            "Creates free deterministic thumbnail images after render.",
            ["script", "assets", "render", "growth_context"],
            ["shorts_cover_path", "youtube_thumbnail_path", "source_image_path", "text_lines"],
            ["Generate 1080x1920 Shorts cover.", "Generate 1280x720 YouTube thumbnail."],
        ),
    ]


def _contract(
    name: str,
    description: str,
    input_params: list[str],
    output_params: list[str],
    constraints: list[str],
) -> dict[str, Any]:
    return {
        "name": name,
        "description": description,
        "input_params": input_params,
        "output_params": output_params,
        "constraints": constraints,
    }


def run_pipeline_job(run_id: str, route: dict[str, Any], api_key: str = "") -> None:
    settings = get_settings()
    run_dir = Path(settings.playground_runs_dir) / f"run_{run_id}"
    run_dir.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["PIPELINE_RUN_DIR"] = str(run_dir)
    env["PIPELINE_RUNS_DIR"] = settings.playground_runs_dir
    _apply_llm_env(env, route, api_key)
    command = [
        sys.executable,
        "main.py",
        "--topic",
        route["topic"],
        "--genre",
        route["genre"],
        "--duration",
        str(route["duration"]),
        "--notes",
        route.get("notes", ""),
        "--settings-json",
        json.dumps(route.get("settings") or {}, ensure_ascii=True),
    ]

    with SessionLocal() as db:
        run = db.get(PlaygroundRun, run_id)
        if run:
            run.status = "running"
            run.updated_at = utc_now()
            _add_run_event(db, run_id, "Pipeline subprocess started", {"command": _safe_command(command), "run_dir": str(run_dir)})
            db.commit()

    proc = subprocess.Popen(
        command,
        cwd=settings.pipeline_root,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    while proc.poll() is None:
        with SessionLocal() as db:
            sync_pipeline_run(db, run_id, run_dir, running=True)
            db.commit()
        time.sleep(1.0)

    stdout, stderr = proc.communicate()
    with SessionLocal() as db:
        sync_pipeline_run(db, run_id, run_dir, running=False)
        run = db.get(PlaygroundRun, run_id)
        if run:
            run.status = "succeeded" if proc.returncode == 0 else "failed"
            run.updated_at = utc_now()
            _add_run_event(
                db,
                run_id,
                "Pipeline subprocess finished",
                {"returncode": proc.returncode, "stdout": stdout[-12000:], "stderr": stderr[-12000:]},
                level="info" if proc.returncode == 0 else "error",
            )
            if proc.returncode == 0:
                _mark_remaining_success(db, run_id)
            else:
                _apply_failure_from_errors(db, run_id, run_dir)
        db.commit()


def sync_pipeline_run(db: Session, run_id: str, run_dir: Path, running: bool) -> None:
    stage_map = {stage.agent_name: stage for stage in db.scalars(select(PlaygroundStage).where(PlaygroundStage.run_id == run_id))}
    for agent in AGENTS[1:]:
        stage = stage_map.get(agent)
        if not stage:
            continue
        module = _agent_to_log_module(agent)
        log_dir = run_dir / "logs" / module
        events = _read_event_file(log_dir / "events.log")
        input_json = _read_json(log_dir / "input.json")
        output_json = _read_json(log_dir / "output.json")
        if input_json:
            stage.input_json = input_json
        if output_json:
            stage.output_json = output_json
        if not stage.prompt_text:
            stage.prompt_text = prompt_text_for_agent(agent)
        if (events or input_json) and stage.status == "pending":
            stage.status = "running"
            stage.started_at = stage.started_at or utc_now()
        if output_json and stage.status in {"pending", "running"}:
            stage.status = "succeeded"
            stage.completed_at = stage.completed_at or utc_now()

    _replace_events(db, run_id, run_dir)
    _replace_artifacts(db, run_id, run_dir)
    if running:
        _apply_failure_from_errors(db, run_id, run_dir, mark_run=False)


def prompt_text_for_agent(agent: str) -> str:
    settings = get_settings()
    if agent == "master_agent":
        return _master_prompt()
    rel = PROMPT_FILES.get(agent)
    if rel:
        path = Path(settings.pipeline_root) / rel
        if path.exists():
            return path.read_text(encoding="utf-8", errors="replace")
    return "No LLM prompt for this stage. This agent is deterministic or uses runtime files from previous stages."


def _create_stage(
    db: Session,
    run: PlaygroundRun,
    agent_name: str,
    order_index: int,
    status: str = "pending",
    input_json: dict[str, Any] | None = None,
    prompt_text: str = "",
    output_json: dict[str, Any] | None = None,
) -> PlaygroundStage:
    stage = PlaygroundStage(
        run_id=run.id,
        agent_name=agent_name,
        order_index=order_index,
        status=status,
        started_at=utc_now() if status in {"running", "succeeded"} else None,
        completed_at=utc_now() if status == "succeeded" else None,
        input_json=input_json or {},
        prompt_text=prompt_text,
        output_json=output_json or {},
    )
    db.add(stage)
    db.flush()
    return stage


def _replace_events(db: Session, run_id: str, run_dir: Path) -> None:
    stage_map = {stage.agent_name: stage.id for stage in db.scalars(select(PlaygroundStage).where(PlaygroundStage.run_id == run_id))}
    master_stage_id = stage_map.get("master_agent")
    db.execute(
        delete(PlaygroundEvent).where(
            PlaygroundEvent.run_id == run_id,
            PlaygroundEvent.stage_id.is_not(None),
            PlaygroundEvent.stage_id != master_stage_id,
        )
    )
    for module, agent in LOG_MODULE_TO_AGENT.items():
        for event in _read_event_file(run_dir / "logs" / module / "events.log"):
            db.add(
                PlaygroundEvent(
                    run_id=run_id,
                    stage_id=stage_map.get(agent),
                    timestamp=_parse_ts(event.get("ts")),
                    level="info",
                    message=str(event.get("message") or "Agent event"),
                    payload_json=event,
                )
            )
    for event in _read_event_file(run_dir / "errors" / "events.log"):
        agent = ERROR_STAGE_TO_AGENT.get(str(event.get("stage") or ""))
        db.add(
            PlaygroundEvent(
                run_id=run_id,
                stage_id=stage_map.get(agent or ""),
                timestamp=_parse_ts(event.get("ts")),
                level="error",
                message=str(event.get("message") or event.get("error_type") or "Pipeline error"),
                payload_json=event,
            )
        )


def _replace_artifacts(db: Session, run_id: str, run_dir: Path) -> None:
    db.execute(delete(PlaygroundArtifact).where(PlaygroundArtifact.run_id == run_id))
    if not run_dir.exists():
        return
    stage_map = {stage.agent_name: stage.id for stage in db.scalars(select(PlaygroundStage).where(PlaygroundStage.run_id == run_id))}
    for path in sorted(run_dir.rglob("*")):
        if not path.is_file():
            continue
        rel = str(path.relative_to(run_dir))
        agent = _artifact_agent(rel)
        mime_type = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        db.add(
            PlaygroundArtifact(
                run_id=run_id,
                stage_id=stage_map.get(agent or ""),
                kind=_artifact_kind(mime_type, rel),
                path=str(path),
                mime_type=mime_type,
                size_bytes=path.stat().st_size,
                previewable=_is_previewable(mime_type, rel),
            )
        )


def _apply_failure_from_errors(db: Session, run_id: str, run_dir: Path, mark_run: bool = True) -> None:
    errors = _read_event_file(run_dir / "errors" / "events.log")
    if not errors:
        return
    failed_agent = ERROR_STAGE_TO_AGENT.get(str(errors[-1].get("stage") or ""))
    if not failed_agent:
        return
    stages = list(db.scalars(select(PlaygroundStage).where(PlaygroundStage.run_id == run_id).order_by(PlaygroundStage.order_index.asc())))
    failed_index = None
    for stage in stages:
        if stage.agent_name == failed_agent:
            failed_index = stage.order_index
            stage.status = "failed"
            stage.error_text = str(errors[-1].get("message") or errors[-1].get("error_type") or "Pipeline failed")
            stage.completed_at = stage.completed_at or utc_now()
            break
    if failed_index is not None:
        for stage in stages:
            if stage.order_index > failed_index and stage.status == "pending":
                stage.status = "skipped"
                stage.completed_at = stage.completed_at or utc_now()
    if mark_run:
        run = db.get(PlaygroundRun, run_id)
        if run:
            run.status = "failed"
            run.updated_at = utc_now()


def _mark_remaining_success(db: Session, run_id: str) -> None:
    for stage in db.scalars(select(PlaygroundStage).where(PlaygroundStage.run_id == run_id)):
        if stage.status in {"pending", "running"}:
            stage.status = "succeeded"
            stage.started_at = stage.started_at or utc_now()
            stage.completed_at = stage.completed_at or utc_now()


def _add_run_event(db: Session, run_id: str, message: str, payload: dict[str, Any] | None = None, level: str = "info") -> None:
    db.add(PlaygroundEvent(run_id=run_id, level=level, message=message, payload_json=payload or {}))


def _stage_by_agent(db: Session, run_id: str, agent: str) -> PlaygroundStage:
    return db.scalar(select(PlaygroundStage).where(PlaygroundStage.run_id == run_id, PlaygroundStage.agent_name == agent))


def _agent_to_log_module(agent: str) -> str:
    return "validation_agent" if agent == "validation_agent" else agent


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except json.JSONDecodeError:
        return {"raw": path.read_text(encoding="utf-8", errors="replace")}
    return data if isinstance(data, dict) else {"value": data}


def _read_event_file(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    events: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            event = {"message": line.strip()}
        events.append(event if isinstance(event, dict) else {"message": str(event)})
    return events


def provenance_fields(
    mode: str,
    *,
    ai_used: bool | None = None,
    deterministic: bool | None = None,
) -> dict[str, Any]:
    normalized = normalize_execution_mode(mode)
    if ai_used is None:
        ai_used = normalized in {"ai", "hybrid"}
    if deterministic is None:
        deterministic = normalized in {"deterministic", "fallback", "hybrid"}
    return {
        "execution_mode": normalized,
        "ai_used": ai_used,
        "deterministic": deterministic,
    }


def _provenance_payload(mode: str, payload: dict[str, Any] | None = None, **fields: Any) -> dict[str, Any]:
    return {
        **(payload or {}),
        **provenance_fields(mode),
        **fields,
    }


def default_execution_mode_for_agent(agent_name: str) -> str:
    return DEFAULT_AGENT_EXECUTION_MODES.get(agent_name, "deterministic")


def normalize_execution_mode(value: Any) -> str:
    normalized = str(value or "").strip().lower().replace(" ", "_")
    return normalized if normalized in EXECUTION_MODE_PRIORITY else ""


def combine_execution_modes(current: str, incoming: str) -> str:
    current = normalize_execution_mode(current)
    incoming = normalize_execution_mode(incoming)
    if not current:
        return incoming
    if not incoming:
        return current
    if {current, incoming} == {"ai", "deterministic"}:
        return "hybrid"
    return current if EXECUTION_MODE_PRIORITY[current] >= EXECUTION_MODE_PRIORITY[incoming] else incoming


def stage_execution_mode_from_events(agent_name: str, events: list[PlaygroundEvent]) -> str:
    mode = ""
    for event in events:
        payload = event.payload_json if isinstance(event.payload_json, dict) else {}
        mode = combine_execution_modes(mode, payload.get("execution_mode", ""))
    return mode or default_execution_mode_for_agent(agent_name)


def _parse_ts(value: Any) -> datetime:
    if not value:
        return utc_now()
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return utc_now()
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _looks_like_generation(lower: str) -> bool:
    triggers = (
        "generate",
        "make",
        "create",
        "render",
        "video",
        "short",
        "youtube",
        "story",
        "script",
        "narration",
        "tts",
        "voiceover",
        "cinematic",
        "calibration",
    )
    return any(word in lower for word in triggers) or bool(
        re.search(r"\b[1-9]\d{0,2}\s*(?:s|sec|secs|second|seconds)\b", lower)
    )


def _has_generation_subject_signal(lower: str) -> bool:
    filler = {
        "generate",
        "make",
        "create",
        "render",
        "a",
        "an",
        "the",
        "video",
        "short",
        "story",
        "youtube",
        "sec",
        "second",
        "seconds",
        "s",
    }
    words = [word for word in re.findall(r"[a-z0-9]+", lower) if word not in filler and not word.isdigit()]
    return len(words) >= 2


def _extract_duration(lower: str) -> int:
    match = re.search(r"\b([1-9]\d{0,2})\s*(?:second|seconds|sec|secs|s)\b", lower)
    if not match:
        return 30
    return max(10, min(180, int(match.group(1))))


def _extract_settings(lower: str, duration: int) -> dict[str, Any]:
    settings: dict[str, Any] = {
        "duration": duration,
        "voice_speed": 1.0,
        "caption_words": 4,
        "image_count": 8,
        "music_volume": 0.18,
        "schedule": "now",
    }
    if "slower" in lower or "slow voice" in lower:
        settings["voice_speed"] = 0.9
    if "faster" in lower or "fast voice" in lower:
        settings["voice_speed"] = 1.1
    voice = re.search(r"\b(?:voice\s*speed|speaking\s*rate|speed)\s*(?:is|=|:)?\s*(0\.\d+|1(?:\.\d+)?)\b", lower)
    if voice:
        settings["voice_speed"] = max(0.65, min(1.4, float(voice.group(1))))
    images = re.search(r"\b([1-9]\d?)\s*(?:images|frames|visuals|photos)\b", lower)
    if images:
        settings["image_count"] = max(3, min(24, int(images.group(1))))
    captions = re.search(r"\b(?:caption\s*words|words\s*per\s*caption)\s*(?:is|=|:)?\s*([1-9]\d?)\b", lower)
    if captions:
        settings["caption_words"] = max(1, min(10, int(captions.group(1))))
    volume = re.search(r"\b(?:music\s*volume|bgm\s*volume)\s*(?:is|=|:)?\s*(0(?:\.\d+)?|0?\.?\d+)\b", lower)
    if volume:
        settings["music_volume"] = max(0.0, min(0.8, float(volume.group(1))))
    return settings


def _minimum_image_cues(duration: int) -> int:
    if duration >= 120:
        return 18
    if duration >= 90:
        return 14
    if duration >= 60:
        return 10
    if duration >= 45:
        return 8
    return 6


def _extract_topic(message: str) -> str:
    cleaned = re.sub(r"\b(generate|make|create|render)\b", "", message, flags=re.IGNORECASE)
    cleaned = re.sub(r"\b(i\s+want|i\s+need|can\s+you|please|plz)\b", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\b(a|an)?\s*(youtube)?\s*(short|video)\b", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\b([1-9]\d{0,2})\s*(second|seconds|sec|secs|s)\b", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\b(scary|horror|reddit|story|stories)\b", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"^\s*(a|an)\s+(on|about|for)\s+", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"^\s*(on|about|for)\s+", "", cleaned, flags=re.IGNORECASE)
    return " ".join(cleaned.replace(":", " ").split())


def _normalize_genre(genre_id: str, lower: str) -> str:
    selected = (genre_id or "").strip()
    if selected:
        return selected
    if "reddit" in lower:
        return "reddit_stories"
    if "history" in lower:
        return "history_facts"
    if "science" in lower:
        return "science_facts"
    if "mystery" in lower:
        return "mystery_stories"
    if "motivation" in lower:
        return "motivational_stories"
    if "relationship" in lower:
        return "relationship_stories"
    return "scary_stories"


def _normalize_provider(provider: str) -> str:
    selected = (provider or "env").strip().lower()
    if selected in {"env", "auto", *LLM_MODEL_OPTIONS.keys()}:
        return selected
    return "env"


def _normalize_model(provider: str, model: str) -> str:
    if provider not in LLM_MODEL_OPTIONS:
        return ""
    selected = model.strip()
    return selected or LLM_MODEL_OPTIONS[provider][0]


def _apply_llm_env(env: dict[str, str], route: dict[str, Any], api_key: str) -> None:
    provider = str(route.get("llm_provider") or "env")
    model = str(route.get("llm_model") or "")
    if provider == "env":
        return
    env["LLM_PROVIDER"] = provider
    if model:
        env["LLM_MODEL"] = model
        model_env = MODEL_ENV_MAP.get(provider)
        if model_env:
            env[model_env] = model
    if api_key and provider in KEY_ENV_MAP:
        env[KEY_ENV_MAP[provider]] = api_key


def llm_options() -> list[dict[str, Any]]:
    labels = {
        "openai": "OpenAI / ChatGPT",
        "anthropic": "Claude",
        "gemini": "Gemini",
        "groq": "Groq",
    }
    return [
        {"provider": "env", "label": "Use .env / Docker environment", "models": [""], "default_model": ""},
        *[
            {
                "provider": provider,
                "label": labels.get(provider, provider.title()),
                "models": models,
                "default_model": models[0],
            }
            for provider, models in LLM_MODEL_OPTIONS.items()
        ],
    ]


def _master_prompt() -> str:
    return (
        "You are the playground master agent. Classify the chat message as generic conversation, "
        "clarifying question, or video generation. For generation, lock constraints first, explain every "
        "agent's purpose, input params, output params, and constraints, then route through topic discovery, "
        "research, script, validation, assets, audio, captions, render, and thumbnail generation. The script "
        "must write within constraints, self-check, validation must check it, and invalid scripts must auto-repair "
        "before downstream agents run."
    )


def _safe_command(command: list[str]) -> list[str]:
    safe = []
    skip_next = False
    for item in command:
        if skip_next:
            safe.append("[payload]")
            skip_next = False
            continue
        safe.append(item)
        if item in {"--settings-json"}:
            skip_next = True
    return safe


def _artifact_agent(rel: str) -> str:
    if rel.startswith("logs/script_agent/"):
        return "script_agent"
    if rel.startswith("logs/topic_discovery_agent/"):
        return "topic_discovery_agent"
    if rel.startswith("logs/research_agent/"):
        return "research_agent"
    if rel.startswith("logs/validation_agent/") or rel.startswith("errors/"):
        return "validation_agent"
    if rel.startswith("logs/asset_agent/") or rel.startswith("intermediate/images/"):
        return "asset_agent"
    if rel.startswith("logs/audio_agent/") or rel.startswith("intermediate/audio/"):
        return "audio_agent"
    if rel.startswith("logs/caption_agent/") or rel.startswith("intermediate/captions/"):
        return "caption_agent"
    if rel.startswith("logs/thumbnail_agent/") or rel.startswith("output/thumbnails/"):
        return "thumbnail_agent"
    if rel.startswith("logs/render_agent/") or rel.startswith("output/"):
        return "render_agent"
    return ""


def _artifact_kind(mime_type: str, rel: str) -> str:
    if mime_type.startswith("image/"):
        return "image"
    if mime_type.startswith("audio/"):
        return "audio"
    if mime_type.startswith("video/"):
        return "video"
    if rel.endswith(".json"):
        return "json"
    if rel.endswith((".log", ".txt", ".srt", ".ass")):
        return "text"
    return "file"


def _is_previewable(mime_type: str, rel: str) -> bool:
    return (
        mime_type.startswith(("image/", "audio/", "video/"))
        or rel.endswith((".json", ".log", ".txt", ".srt", ".ass"))
    )
