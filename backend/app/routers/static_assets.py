from __future__ import annotations

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.core.database import get_static_db
from app.dependencies import require_active_entitlement
from app.models import User
from app.services.static_asset_catalog import (
    delete_music_asset,
    delete_sfx_asset,
    list_music_assets,
    list_sfx_assets,
    music_file_response,
    sfx_file_response,
    upload_music_asset,
    upload_sfx_asset,
)


router = APIRouter(prefix="/assets", tags=["static-assets"])


@router.get("/music")
def music_assets(db: Session = Depends(get_static_db)) -> list[dict]:
    return list_music_assets(db)


@router.post("/music")
def upload_music(
    file: UploadFile = File(...),
    db: Session = Depends(get_static_db),
    user: User = Depends(require_active_entitlement),
) -> dict:
    return upload_music_asset(db, file)


@router.delete("/music/{asset_id}")
def delete_music(
    asset_id: str,
    db: Session = Depends(get_static_db),
    user: User = Depends(require_active_entitlement),
) -> dict:
    return delete_music_asset(db, asset_id)


@router.get("/music/{asset_id}/file")
def music_file(asset_id: str, db: Session = Depends(get_static_db)) -> FileResponse:
    return music_file_response(db, asset_id)


@router.get("/sfx")
def sfx_assets(db: Session = Depends(get_static_db)) -> list[dict]:
    return list_sfx_assets(db)


@router.post("/sfx")
def upload_sfx(
    file: UploadFile = File(...),
    db: Session = Depends(get_static_db),
    user: User = Depends(require_active_entitlement),
) -> dict:
    return upload_sfx_asset(db, file)


@router.delete("/sfx/{asset_id}")
def delete_sfx(
    asset_id: str,
    db: Session = Depends(get_static_db),
    user: User = Depends(require_active_entitlement),
) -> dict:
    return delete_sfx_asset(db, asset_id)


@router.get("/sfx/{asset_id}/file")
def sfx_file(asset_id: str, db: Session = Depends(get_static_db)) -> FileResponse:
    return sfx_file_response(db, asset_id)
