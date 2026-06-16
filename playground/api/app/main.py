from __future__ import annotations

from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db, init_database
from app.models import PlaygroundArtifact, PlaygroundEvent, PlaygroundRun, PlaygroundStage
from app.runner import create_playground_run, llm_options, stage_execution_mode_from_events
from app.schemas import ArtifactOut, EventOut, GenreOut, GraphEdgeOut, LLMOptionOut, RunCreate, RunDetailOut, RunSummaryOut, StageDetailOut, StageSummaryOut
from app.settings import ensure_runtime_dirs, get_settings


settings = get_settings()
app = FastAPI(title="AI Agent Playground API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup() -> None:
    ensure_runtime_dirs(settings)
    init_database()


@app.get("/api/playground/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/playground/runs", response_model=RunDetailOut)
def create_run(payload: RunCreate, db: Session = Depends(get_db)) -> RunDetailOut:
    run = create_playground_run(db, payload)
    return _run_detail(db, run.id)


@app.get("/api/playground/genres", response_model=list[GenreOut])
def list_genres() -> list[GenreOut]:
    genre_dir = Path(settings.pipeline_root) / "data" / "genres"
    genres: list[GenreOut] = []
    for path in sorted(genre_dir.glob("*.yaml")):
        data = _parse_simple_yaml(path.read_text(encoding="utf-8"))
        genres.append(
            GenreOut(
                genre_id=str(data.get("genre_id", path.stem)),
                display_name=str(data.get("display_name", path.stem.replace("_", " ").title())),
                tone=str(data.get("tone", "")),
                word_count_min=int(data.get("word_count_min", 70)),
                word_count_max=int(data.get("word_count_max", 130)),
            )
        )
    return genres


@app.get("/api/playground/llm-options", response_model=list[LLMOptionOut])
def get_llm_options() -> list[LLMOptionOut]:
    return [LLMOptionOut(**item) for item in llm_options()]


@app.get("/api/playground/runs", response_model=list[RunSummaryOut])
def list_runs(db: Session = Depends(get_db)) -> list[PlaygroundRun]:
    return list(
        db.scalars(
            select(PlaygroundRun)
            .order_by(PlaygroundRun.created_at.desc())
            .limit(50)
        )
    )


@app.get("/api/playground/runs/{run_id}", response_model=RunDetailOut)
def get_run(run_id: str, db: Session = Depends(get_db)) -> RunDetailOut:
    return _run_detail(db, run_id)


@app.get("/api/playground/runs/{run_id}/stages/{stage_id}", response_model=StageDetailOut)
def get_stage(run_id: str, stage_id: str, db: Session = Depends(get_db)) -> StageDetailOut:
    stage = db.get(PlaygroundStage, stage_id)
    if not stage or stage.run_id != run_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Stage not found")
    events = list(
        db.scalars(
            select(PlaygroundEvent)
            .where(PlaygroundEvent.stage_id == stage.id)
            .order_by(PlaygroundEvent.timestamp.asc(), PlaygroundEvent.id.asc())
        )
    )
    artifacts = list(
        db.scalars(
            select(PlaygroundArtifact)
            .where(PlaygroundArtifact.stage_id == stage.id)
            .order_by(PlaygroundArtifact.kind.asc(), PlaygroundArtifact.path.asc())
        )
    )
    return StageDetailOut(
        **_stage_summary(stage, events).model_dump(),
        input_json=stage.input_json or {},
        prompt_text=stage.prompt_text,
        output_json=stage.output_json or {},
        events=[EventOut.model_validate(event) for event in events],
        artifacts=[ArtifactOut.model_validate(artifact) for artifact in artifacts],
    )


@app.get("/api/playground/runs/{run_id}/events", response_model=list[EventOut])
def get_run_events(run_id: str, db: Session = Depends(get_db)) -> list[PlaygroundEvent]:
    _owned_run(db, run_id)
    return list(
        db.scalars(
            select(PlaygroundEvent)
            .where(PlaygroundEvent.run_id == run_id)
            .order_by(PlaygroundEvent.timestamp.asc(), PlaygroundEvent.id.asc())
        )
    )


@app.get("/api/playground/artifacts/{artifact_id}")
def get_artifact(artifact_id: str, db: Session = Depends(get_db)) -> FileResponse:
    artifact = db.get(PlaygroundArtifact, artifact_id)
    if not artifact:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Artifact not found")
    path = Path(artifact.path).resolve()
    root = Path(settings.playground_runs_dir).resolve()
    if not path.exists() or not path.is_file() or not path.is_relative_to(root):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Artifact file is not available")
    return FileResponse(str(path), media_type=artifact.mime_type, filename=path.name)


def _owned_run(db: Session, run_id: str) -> PlaygroundRun:
    run = db.get(PlaygroundRun, run_id)
    if not run:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    return run


def _run_detail(db: Session, run_id: str) -> RunDetailOut:
    run = _owned_run(db, run_id)
    stages = list(
        db.scalars(
            select(PlaygroundStage)
            .where(PlaygroundStage.run_id == run.id)
            .order_by(PlaygroundStage.order_index.asc())
        )
    )
    edges = [
        GraphEdgeOut(source=stages[index].id, target=stages[index + 1].id)
        for index in range(len(stages) - 1)
    ]
    events_by_stage = _events_by_stage_id(db, [stage.id for stage in stages])
    return RunDetailOut(
        **RunSummaryOut.model_validate(run).model_dump(),
        stages=[_stage_summary(stage, events_by_stage.get(stage.id, [])) for stage in stages],
        edges=edges,
    )


def _events_by_stage_id(db: Session, stage_ids: list[str]) -> dict[str, list[PlaygroundEvent]]:
    if not stage_ids:
        return {}
    events_by_stage: dict[str, list[PlaygroundEvent]] = {stage_id: [] for stage_id in stage_ids}
    events = list(
        db.scalars(
            select(PlaygroundEvent)
            .where(PlaygroundEvent.stage_id.in_(stage_ids))
            .order_by(PlaygroundEvent.timestamp.asc(), PlaygroundEvent.id.asc())
        )
    )
    for event in events:
        if event.stage_id:
            events_by_stage.setdefault(event.stage_id, []).append(event)
    return events_by_stage


def _stage_summary(stage: PlaygroundStage, events: list[PlaygroundEvent]) -> StageSummaryOut:
    data = StageSummaryOut.model_validate(stage).model_dump()
    data["execution_mode"] = stage_execution_mode_from_events(stage.agent_name, events)
    return StageSummaryOut(**data)


def _parse_simple_yaml(text: str) -> dict[str, object]:
    result: dict[str, object] = {}
    current_key: str | None = None
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line.startswith("  - ") and current_key:
            result.setdefault(current_key, [])
            if isinstance(result[current_key], list):
                result[current_key].append(line[4:].strip().strip('"').strip("'"))
            continue
        if ":" in line and not line.startswith(" "):
            key, value = line.split(":", 1)
            current_key = key.strip()
            value = value.strip().strip('"').strip("'")
            result[current_key] = value if value else []
    return result
