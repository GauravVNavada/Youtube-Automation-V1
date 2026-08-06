from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.dependencies import get_current_user
from app.models import User
from app.schemas import ApiKeyIn, ApiKeyStatusOut, ApiSetupOut, ProfileUpdateIn, UserOut
from app.services.api_keys import api_key_statuses, llm_options, save_user_api_key


router = APIRouter(prefix="/account", tags=["account"])


@router.get("/profile", response_model=UserOut)
def profile(user: User = Depends(get_current_user)) -> User:
    return user


@router.put("/profile", response_model=UserOut)
def update_profile(
    payload: ProfileUpdateIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> User:
    user.display_name = payload.display_name.strip()
    db.commit()
    db.refresh(user)
    return user


@router.get("/api-keys", response_model=ApiSetupOut)
def api_keys(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> ApiSetupOut:
    statuses = api_key_statuses(db, user.id)
    required = {item["provider"]: item["status"] == "configured" for item in statuses}
    return ApiSetupOut(required=required, statuses=statuses, llm_options=llm_options())


@router.post("/api-keys", response_model=ApiSetupOut)
def save_api_key(payload: ApiKeyIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> ApiSetupOut:
    save_user_api_key(db, user.id, payload.provider, payload.value, payload.model)
    return api_keys(user, db)
