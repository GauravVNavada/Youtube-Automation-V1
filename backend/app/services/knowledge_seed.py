from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import Genre, GenreHook, GenreRule, ReferenceVideo, ScriptAnalysis, VisualStyleRule


def seed_pipeline_knowledge(db: Session) -> None:
    """Load packaged genre and reference-script data into normalized knowledge tables once."""
    settings = get_settings()
    data_dir = Path(settings.pipeline_root) / "data"
    if not data_dir.exists():
        return

    _acquire_seed_lock(db)

    for genre_path in sorted((data_dir / "genres").glob("*.yaml")):
        genre_id = genre_path.stem
        payload = _parse_simple_yaml(genre_path.read_text(encoding="utf-8"))
        _upsert_genre(db, genre_id, payload)

    db.flush()

    for reference_path in sorted((data_dir / "reference_scripts").glob("*.json")):
        genre_id = reference_path.stem
        _ensure_minimal_genre(db, genre_id)
        try:
            records = json.loads(reference_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        for index, payload in enumerate(records if isinstance(records, list) else []):
            _insert_reference_script(db, genre_id, index, payload)

    db.commit()


def _acquire_seed_lock(db: Session) -> None:
    bind = db.get_bind()
    if bind.dialect.name == "postgresql":
        db.execute(text("SELECT pg_advisory_xact_lock(88442211)"))


def _upsert_genre(db: Session, genre_id: str, payload: dict[str, Any]) -> Genre:
    genre = db.get(Genre, genre_id)
    if not genre:
        genre = Genre(id=genre_id, display_name=str(payload.get("display_name") or genre_id.replace("_", " ").title()))
        db.add(genre)

    genre.display_name = str(payload.get("display_name") or genre.display_name)
    genre.tone = str(payload.get("tone") or genre.tone)
    genre.word_count_min = _int(payload.get("word_count_min"), genre.word_count_min)
    genre.word_count_max = _int(payload.get("word_count_max"), genre.word_count_max)
    genre.layout = str(payload.get("layout") or genre.layout)
    genre.caption_preset = str(payload.get("caption_preset") or genre.caption_preset)
    genre.voice_rate = _float(payload.get("voice_rate"), genre.voice_rate)
    genre.music_mood = str(payload.get("music_mood") or genre.music_mood)

    for phrase in payload.get("banned_phrases") or []:
        _insert_rule(db, genre_id, "banned_phrase", str(phrase), -100)
    for pattern in payload.get("hook_patterns") or []:
        existing = db.scalar(
            select(GenreHook).where(GenreHook.genre_id == genre_id, GenreHook.template == str(pattern))
        )
        if not existing:
            db.add(GenreHook(genre_id=genre_id, hook_type="packaged_pattern", template=str(pattern)))

    visual = db.scalar(select(VisualStyleRule).where(VisualStyleRule.genre_id == genre_id))
    if not visual:
        db.add(
            VisualStyleRule(
                genre_id=genre_id,
                layout_type=genre.layout,
                caption_style=genre.caption_preset,
                music_mood=genre.music_mood,
            )
        )
    return genre


def _ensure_minimal_genre(db: Session, genre_id: str) -> Genre:
    genre = db.get(Genre, genre_id)
    if genre:
        return genre
    genre = Genre(id=genre_id, display_name=genre_id.replace("_", " ").title())
    db.add(genre)
    return genre


def _insert_reference_script(db: Session, genre_id: str, index: int, payload: dict[str, Any]) -> None:
    title = str(payload.get("title") or f"{genre_id} reference {index + 1}")[:160]
    script = str(payload.get("script") or payload.get("narration") or "")
    source_url = str(payload.get("source_url") or payload.get("video_url") or f"packaged://{genre_id}/{index}")
    existing = db.scalar(select(ReferenceVideo).where(ReferenceVideo.video_url == source_url))
    if existing:
        return
    ref = ReferenceVideo(
        genre_id=genre_id,
        video_url=source_url,
        title=title,
        full_script=script,
        word_count=len(script.split()),
        overall_score=_float(payload.get("score") or payload.get("overall_score"), 0.0),
        usable_as_few_shot=True,
        notes=str(payload.get("notes") or "Packaged reference script."),
    )
    db.add(ref)
    db.flush()
    db.add(
        ScriptAnalysis(
            reference_video_id=ref.id,
            hook_type=str(payload.get("hook_type") or ""),
            hook_first_sentence=str(payload.get("hook") or payload.get("hook_first_sentence") or "")[:500],
            why_it_worked=str(payload.get("why_it_worked") or ""),
        )
    )


def _insert_rule(db: Session, genre_id: str, rule_type: str, value: str, weight: int) -> None:
    existing = db.scalar(
        select(GenreRule).where(
            GenreRule.genre_id == genre_id,
            GenreRule.rule_type == rule_type,
            GenreRule.value == value,
        )
    )
    if not existing:
        db.add(GenreRule(genre_id=genre_id, rule_type=rule_type, value=value, weight=weight))


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


def _int(value: Any, fallback: int) -> int:
    try:
        return int(float(str(value)))
    except (TypeError, ValueError):
        return fallback


def _float(value: Any, fallback: float) -> float:
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return fallback
