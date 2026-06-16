from __future__ import annotations

import shutil
from pathlib import Path
from tempfile import NamedTemporaryFile

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.dependencies import get_current_user
from app.models import Genre, GenreHook, GenreRule, ReferenceVideo, ScriptAnalysis, TopicResearchSource, User, VisualStyleRule
from tools.genre_knowledge import (
    REAL_WORLD_SEED_PATH,
    backup_database,
    create_template,
    export_knowledge_workbook,
    import_workbook,
    reset_knowledge_tables,
)


router = APIRouter(prefix="/knowledge", tags=["knowledge"])


@router.get("")
def list_knowledge(
    genre_id: str | None = None,
    kind: str | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict]:
    if kind == "genre" or kind is None:
        query = select(Genre)
        if genre_id:
            query = query.where(Genre.id == genre_id)
        genres = db.scalars(query.order_by(Genre.updated_at.desc()).limit(200)).all()
        if kind == "genre":
            return [_genre_payload(genre) for genre in genres]
    else:
        genres = []

    if kind == "reference_video":
        query = select(ReferenceVideo)
        if genre_id:
            query = query.where(ReferenceVideo.genre_id == genre_id)
        return [_reference_payload(record) for record in db.scalars(query.order_by(ReferenceVideo.updated_at.desc()).limit(200))]

    if kind == "script_analysis":
        query = select(ScriptAnalysis).join(ReferenceVideo)
        if genre_id:
            query = query.where(ReferenceVideo.genre_id == genre_id)
        return [_analysis_payload(record) for record in db.scalars(query.order_by(ScriptAnalysis.updated_at.desc()).limit(200))]

    if kind == "genre_rule":
        query = select(GenreRule)
        if genre_id:
            query = query.where(GenreRule.genre_id == genre_id)
        return [_rule_payload(record) for record in db.scalars(query.order_by(GenreRule.created_at.desc()).limit(200))]

    if kind == "genre_hook":
        query = select(GenreHook)
        if genre_id:
            query = query.where(GenreHook.genre_id == genre_id)
        return [_hook_payload(record) for record in db.scalars(query.order_by(GenreHook.created_at.desc()).limit(200))]

    if kind == "visual_style_rule":
        query = select(VisualStyleRule)
        if genre_id:
            query = query.where(VisualStyleRule.genre_id == genre_id)
        return [_visual_payload(record) for record in db.scalars(query.order_by(VisualStyleRule.updated_at.desc()).limit(200))]

    if kind == "topic_research_source":
        query = select(TopicResearchSource)
        if genre_id:
            query = query.where(TopicResearchSource.genre_id == genre_id)
        return [_research_source_payload(record) for record in db.scalars(query.order_by(TopicResearchSource.fetched_at.desc()).limit(200))]

    records: list[dict] = []
    records.extend(_genre_payload(genre) for genre in genres)
    records.extend(
        _reference_payload(record)
        for record in db.scalars(select(ReferenceVideo).order_by(ReferenceVideo.updated_at.desc()).limit(80))
    )
    records.extend(
        _rule_payload(record)
        for record in db.scalars(select(GenreRule).order_by(GenreRule.created_at.desc()).limit(80))
    )
    return records[:200]


@router.get("/export.xlsx")
def export_knowledge(user: User = Depends(get_current_user)) -> FileResponse:
    path = Path("/tmp") / f"genre_knowledge_export_{user.id}.xlsx"
    export_knowledge_workbook(path)
    return FileResponse(
        path,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename="Genre_Knowledge_DB_Export.xlsx",
    )


@router.get("/real-world-seed.xlsx")
def download_real_world_seed(user: User = Depends(get_current_user)) -> FileResponse:
    if not REAL_WORLD_SEED_PATH.exists():
        create_template(REAL_WORLD_SEED_PATH)
    return FileResponse(
        REAL_WORLD_SEED_PATH,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename="Genre_Knowledge_Real_World_Seed.xlsx",
    )


@router.post("/import.xlsx")
async def import_knowledge(
    reset: bool = True,
    backup: bool = True,
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
) -> dict:
    if not file.filename.lower().endswith(".xlsx"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Upload an .xlsx workbook")
    with NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = Path(tmp.name)
    try:
        backup_path = str(backup_database()) if backup else ""
        if reset:
            reset_knowledge_tables()
        counts = import_workbook(tmp_path)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    finally:
        tmp_path.unlink(missing_ok=True)
    return {"status": "imported", "counts": counts, "backup_path": backup_path}


def _genre_payload(genre: Genre) -> dict:
    return {
        "id": genre.id,
        "genre_id": genre.id,
        "kind": "genre",
        "source": "genres",
        "score": genre.recommended_score,
        "payload": {
            "display_name": genre.display_name,
            "category": genre.category,
            "tone": genre.tone,
            "word_count_min": genre.word_count_min,
            "word_count_max": genre.word_count_max,
            "realism_mode": genre.realism_mode,
            "is_active": genre.is_active,
        },
        "created_at": genre.created_at.isoformat(),
    }


def _reference_payload(record: ReferenceVideo) -> dict:
    return {
        "id": record.id,
        "genre_id": record.genre_id,
        "kind": "reference_video",
        "source": record.video_url,
        "score": record.overall_score,
        "payload": {
            "title": record.title,
            "channel_name": record.channel_name,
            "views": record.views,
            "duration_sec": record.duration_sec,
            "full_script": record.full_script,
            "usable_as_few_shot": record.usable_as_few_shot,
        },
        "created_at": record.created_at.isoformat(),
    }


def _analysis_payload(record: ScriptAnalysis) -> dict:
    return {
        "id": record.id,
        "genre_id": record.reference_video.genre_id,
        "kind": "script_analysis",
        "source": str(record.reference_video_id),
        "score": 0,
        "payload": {
            "hook_type": record.hook_type,
            "hook_first_sentence": record.hook_first_sentence,
            "narrative_technique": record.narrative_technique,
            "emotional_arc": record.emotional_arc,
            "why_it_worked": record.why_it_worked,
            "what_to_improve": record.what_to_improve,
        },
        "created_at": record.created_at.isoformat(),
    }


def _rule_payload(record: GenreRule) -> dict:
    return {
        "id": record.id,
        "genre_id": record.genre_id,
        "kind": "genre_rule",
        "source": record.rule_type,
        "score": record.weight,
        "payload": {"value": record.value, "notes": record.notes},
        "created_at": record.created_at.isoformat(),
    }


def _hook_payload(record: GenreHook) -> dict:
    return {
        "id": record.id,
        "genre_id": record.genre_id,
        "kind": "genre_hook",
        "source": record.hook_type,
        "score": record.avg_score,
        "payload": {"template": record.template, "emotional_trigger": record.emotional_trigger, "notes": record.notes},
        "created_at": record.created_at.isoformat(),
    }


def _visual_payload(record: VisualStyleRule) -> dict:
    return {
        "id": record.id,
        "genre_id": record.genre_id,
        "kind": "visual_style_rule",
        "source": record.source_policy,
        "score": 0,
        "payload": {
            "layout_type": record.layout_type,
            "image_style": record.image_style,
            "visual_keywords": record.visual_keywords,
            "negative_visual_keywords": record.negative_visual_keywords,
            "caption_style": record.caption_style,
            "music_mood": record.music_mood,
        },
        "created_at": record.created_at.isoformat(),
    }


def _research_source_payload(record: TopicResearchSource) -> dict:
    return {
        "id": record.id,
        "genre_id": record.genre_id,
        "kind": "topic_research_source",
        "source": record.url,
        "score": record.relevance_score,
        "payload": {
            "topic": record.topic,
            "title": record.title,
            "source_type": record.source_type,
            "snippet": record.snippet,
            "extracted_facts": record.extracted_facts,
            "credibility_score": record.credibility_score,
            "relevance_score": record.relevance_score,
        },
        "created_at": record.fetched_at.isoformat(),
    }
