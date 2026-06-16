from __future__ import annotations

from pathlib import Path
import shutil

from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.dependencies import get_current_user
from app.models import KnowledgeImportBatch, User


router = APIRouter(prefix="/knowledge", tags=["knowledge"])


@router.post("/import.xlsx")
def import_knowledge(
    reset: bool = True,
    backup: bool = True,
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    target_dir = Path(__file__).resolve().parents[2] / "data" / "knowledge" / "imports"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / (file.filename or "knowledge_import.xlsx")
    with target.open("wb") as handle:
        shutil.copyfileobj(file.file, handle)
    batch = KnowledgeImportBatch(
        source_file=str(target),
        row_counts={},
        errors=["File saved. Parser/import execution is intentionally separate."],
    )
    db.add(batch)
    db.commit()
    db.refresh(batch)
    return {"status": "saved", "batch_id": batch.id, "source_file": str(target), "reset": reset, "backup": backup}
