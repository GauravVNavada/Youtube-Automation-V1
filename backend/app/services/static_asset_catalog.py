from __future__ import annotations

import mimetypes
import os
from pathlib import Path
import re
from uuid import uuid4

from fastapi import HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import StaticAsset
from app.services.knowledge_seed import AUDIO_EXTENSIONS, upsert_music_asset, upsert_sfx_asset


MAX_AUDIO_UPLOAD_MB = max(1, int(os.getenv("STATIC_ASSET_MAX_UPLOAD_MB", os.getenv("PLAYGROUND_MAX_MUSIC_UPLOAD_MB", "300"))))
MAX_AUDIO_UPLOAD_BYTES = MAX_AUDIO_UPLOAD_MB * 1024 * 1024


def pipeline_data_dir() -> Path:
    configured = os.getenv("PLAYGROUND_PIPELINE_DATA_DIR") or os.getenv("MODULARSHORTS_DATA_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    return project_root() / "playground" / "data" / "pipeline"


def project_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "final_pipeline" / "main.py").exists():
            return parent
    return Path(__file__).resolve().parents[3]


def list_music_assets(db: Session) -> list[dict]:
    _sync_music_templates(db)
    rows = db.scalars(
        select(StaticAsset)
        .where(StaticAsset.asset_type == "music", StaticAsset.enabled.is_(True))
        .order_by(StaticAsset.source.asc(), StaticAsset.name.asc(), StaticAsset.id.asc())
    ).all()
    return [music_asset_dict(row) for row in rows if _valid_catalog_path(row.path, "music")]


def _sync_music_templates(db: Session) -> None:
    changed = False
    seen_paths: set[str] = set()
    for root in _asset_roots("music"):
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*"), key=lambda item: item.name.lower()):
            if not path.is_file() or path.suffix.lower() not in AUDIO_EXTENSIONS or "uploads" in path.parts:
                continue
            resolved = str(path.resolve())
            if resolved in seen_paths:
                continue
            seen_paths.add(resolved)
            upsert_music_asset(db, path, source="template")
            changed = True
    if changed:
        db.commit()


def list_sfx_assets(db: Session) -> list[dict]:
    rows = db.scalars(
        select(StaticAsset)
        .where(StaticAsset.asset_type == "sfx", StaticAsset.enabled.is_(True))
        .order_by(StaticAsset.intensity.desc(), StaticAsset.name.asc(), StaticAsset.id.asc())
    ).all()
    return [sfx_asset_dict(row) for row in rows if _valid_catalog_path(row.path, "sfx")]


def upload_music_asset(db: Session, file: UploadFile) -> dict:
    path, size = _save_audio_upload(file, pipeline_data_dir() / "assets" / "music" / "uploads")
    row = upsert_music_asset(db, path, source="upload")
    db.commit()
    db.refresh(row)
    payload = music_asset_dict(row)
    payload["size_bytes"] = size
    return payload


def upload_sfx_asset(db: Session, file: UploadFile) -> dict:
    path, size = _save_audio_upload(file, pipeline_data_dir() / "assets" / "sfx" / "uploads")
    row = upsert_sfx_asset(db, path, source="upload")
    db.commit()
    db.refresh(row)
    payload = sfx_asset_dict(row)
    payload["size_bytes"] = size
    return payload


def delete_music_asset(db: Session, asset_id: str) -> dict:
    row = db.get(StaticAsset, asset_id)
    if row is None or row.asset_type != "music":
        raise HTTPException(status_code=404, detail="Music asset not found")
    deleted_file = _delete_upload_file(row.path, "music")
    if row.source == "upload":
        db.delete(row)
    else:
        row.enabled = False
    db.commit()
    return {"status": "deleted", "id": asset_id, "deleted_file": deleted_file}


def delete_sfx_asset(db: Session, asset_id: str) -> dict:
    row = db.get(StaticAsset, asset_id)
    if row is None or row.asset_type != "sfx":
        raise HTTPException(status_code=404, detail="SFX asset not found")
    deleted_file = _delete_upload_file(row.path, "sfx")
    if row.source == "upload":
        db.delete(row)
    else:
        row.enabled = False
    db.commit()
    return {"status": "deleted", "id": asset_id, "deleted_file": deleted_file}


def music_file_response(db: Session, asset_id: str) -> FileResponse:
    row = db.get(StaticAsset, asset_id)
    if row is None or row.asset_type != "music" or not row.enabled:
        raise HTTPException(status_code=404, detail="Music asset not found")
    return _audio_file_response(row.path, "music")


def sfx_file_response(db: Session, asset_id: str) -> FileResponse:
    row = db.get(StaticAsset, asset_id)
    if row is None or row.asset_type != "sfx" or not row.enabled:
        raise HTTPException(status_code=404, detail="SFX asset not found")
    return _audio_file_response(row.path, "sfx")


def music_asset_dict(row: StaticAsset) -> dict:
    path = _resolve_catalog_path(row.path)
    return {
        "id": row.id,
        "name": row.name,
        "description": row.description,
        "tags": row.tags or [],
        "mood": row.mood,
        "source": row.source,
        "duration_ms": row.duration_ms,
        "music_path": str(path),
        "url": f"/api/assets/music/{row.id}/file",
        "filename": path.name,
    }


def sfx_asset_dict(row: StaticAsset) -> dict:
    path = _resolve_catalog_path(row.path)
    return {
        "id": row.id,
        "name": row.name,
        "description": row.description,
        "tags": row.tags or [],
        "aliases": row.aliases or [],
        "use_cases": row.use_cases or [],
        "intensity": row.intensity,
        "source": row.source,
        "duration_ms": row.duration_ms,
        "path": str(path),
        "url": f"/api/assets/sfx/{row.id}/file",
        "filename": path.name,
    }


def _save_audio_upload(file: UploadFile, target_dir: Path) -> tuple[Path, int]:
    filename = file.filename or "uploaded_audio"
    suffix = Path(filename).suffix.lower()
    if suffix not in AUDIO_EXTENSIONS:
        allowed = ", ".join(sorted(ext.lstrip(".") for ext in AUDIO_EXTENSIONS))
        raise HTTPException(status_code=400, detail=f"Upload an audio file: {allowed}.")

    target_dir.mkdir(parents=True, exist_ok=True)
    stem = re.sub(r"[^A-Za-z0-9_.-]+", "-", Path(filename).stem).strip(".-")[:60] or "audio"
    target = target_dir / f"{stem}-{uuid4().hex[:8]}{suffix}"

    total = 0
    with target.open("wb") as handle:
        while True:
            chunk = file.file.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_AUDIO_UPLOAD_BYTES:
                handle.close()
                target.unlink(missing_ok=True)
                raise HTTPException(status_code=413, detail=f"Audio upload is too large. Keep it under {MAX_AUDIO_UPLOAD_MB} MB.")
            handle.write(chunk)

    if total <= 0:
        target.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="Uploaded audio file is empty.")
    return target.resolve(), total


def _audio_file_response(raw_path: str, asset_kind: str) -> FileResponse:
    path = _resolve_catalog_path(raw_path)
    if not _valid_catalog_path(str(path), asset_kind):
        raise HTTPException(status_code=404, detail="Asset file not found")
    media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return FileResponse(path, media_type=media_type, filename=path.name)


def _delete_upload_file(raw_path: str, asset_kind: str) -> bool:
    path = _resolve_catalog_path(raw_path)
    for root in _asset_roots(asset_kind):
        upload_root = root / "uploads"
        if path.exists() and path.is_file() and _is_relative_to(path, upload_root.resolve()):
            path.unlink(missing_ok=True)
            return True
    return False


def _valid_catalog_path(raw_path: str, asset_kind: str) -> bool:
    path = _resolve_catalog_path(raw_path)
    return (
        path.exists()
        and path.is_file()
        and path.suffix.lower() in AUDIO_EXTENSIONS
        and any(_is_relative_to(path, root.resolve()) for root in _asset_roots(asset_kind))
    )


def _asset_roots(asset_kind: str) -> list[Path]:
    roots: list[Path] = []
    for configured in _csv_paths(os.getenv("STATIC_ASSET_EXTRA_ROOTS", "")):
        roots.extend(_extra_asset_roots(configured, asset_kind))
    for env_name in ("MODULARSHORTS_DATA_DIR", "PLAYGROUND_PIPELINE_DATA_DIR"):
        configured = os.getenv(env_name, "").strip()
        if configured:
            roots.append(Path(configured).expanduser() / "assets" / asset_kind)
    root = project_root()
    roots.extend(
        [
            pipeline_data_dir() / "assets" / asset_kind,
            root / "data" / "pipeline" / "assets" / asset_kind,
            root / "backend" / "data" / "pipeline" / "assets" / asset_kind,
            root / "playground" / "data" / "pipeline" / "assets" / asset_kind,
            root / "final_pipeline" / "data" / "assets" / asset_kind,
        ]
    )
    deduped: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        key = str(root)
        if key not in seen:
            seen.add(key)
            deduped.append(root)
    return deduped


def _csv_paths(value: str) -> list[Path]:
    return [Path(item.strip()).expanduser() for item in value.split(",") if item.strip()]


def _extra_asset_roots(configured: Path, asset_kind: str) -> list[Path]:
    roots = [configured / asset_kind, configured / "assets" / asset_kind]
    if configured.name.lower() == asset_kind or _has_direct_audio_files(configured):
        roots.insert(0, configured)
    return roots


def _has_direct_audio_files(path: Path) -> bool:
    try:
        return any(child.is_file() and child.suffix.lower() in AUDIO_EXTENSIONS for child in path.iterdir())
    except OSError:
        return False


def _resolve_catalog_path(raw_path: str) -> Path:
    path = Path(str(raw_path or "")).expanduser()
    resolved = path.resolve()
    if resolved.exists():
        return resolved
    remaps = (
        ("/app/playground/data/pipeline", pipeline_data_dir()),
        ("/app/data/pipeline", project_root() / "backend" / "data" / "pipeline"),
    )
    raw = str(path)
    for prefix, root in remaps:
        if raw == prefix or raw.startswith(prefix + "/"):
            candidate = (root / raw[len(prefix) :].lstrip("/")).expanduser().resolve()
            if candidate.exists():
                return candidate
    return resolved


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False
