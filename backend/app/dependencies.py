from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import decode_access_token
from app.models import User, UserEntitlement
from app.services.billing import entitlement_is_active


def get_current_user(
    authorization: Annotated[str | None, Header()] = None,
    db: Session = Depends(get_db),
) -> User:
    prefix = "Bearer "
    if not authorization or not authorization.startswith(prefix):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")
    subject = decode_access_token(authorization[len(prefix) :].strip())
    if not subject:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    user = db.get(User, int(subject))
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return user


def require_active_entitlement(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> User:
    entitlement = db.get(UserEntitlement, user.id)
    if not entitlement_is_active(entitlement):
        raise HTTPException(status_code=status.HTTP_402_PAYMENT_REQUIRED, detail="Active payment required")
    return user
