from __future__ import annotations

from pathlib import Path
import shutil

from fastapi import APIRouter, Depends, File, UploadFile

from app.dependencies import require_active_entitlement
from app.models import User


router = APIRouter(prefix="/knowledge", tags=["knowledge"])


@router.post("/import.xlsx")
def import_knowledge(
    reset: bool = True,
    backup: bool = True,
    file: UploadFile = File(...),
    user: User = Depends(require_active_entitlement),
) -> dict:
    target_dir = Path(__file__).resolve().parents[2] / "data" / "knowledge" / "imports"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / (file.filename or "knowledge_import.xlsx")
    with target.open("wb") as handle:
        shutil.copyfileobj(file.file, handle)
    return {"status": "saved", "source_file": str(target), "reset": reset, "backup": backup}
