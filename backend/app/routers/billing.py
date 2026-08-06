from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.dependencies import get_current_user
from app.models import User
from app.schemas import BillingCheckoutIn, BillingCheckoutOut, BillingPlanOut, BillingVerifyIn, EntitlementOut
from app.services.billing import BillingError, billing_plans, create_checkout, entitlement_out, process_webhook, verify_checkout


router = APIRouter(prefix="/billing", tags=["billing"])


@router.get("/plans", response_model=list[BillingPlanOut])
def plans() -> list[BillingPlanOut]:
    return billing_plans()


@router.post("/checkout", response_model=BillingCheckoutOut)
def checkout(
    payload: BillingCheckoutIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> BillingCheckoutOut:
    try:
        return create_checkout(db, user, payload.plan_code)
    except BillingError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/verify", response_model=EntitlementOut)
def verify(
    payload: BillingVerifyIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> EntitlementOut:
    try:
        return verify_checkout(db, user, payload)
    except BillingError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/entitlement", response_model=EntitlementOut)
def entitlement(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> EntitlementOut:
    return entitlement_out(db, user)


@router.post("/webhook")
async def webhook(
    request: Request,
    x_razorpay_signature: str = Header(default=""),
    x_razorpay_event_id: str = Header(default=""),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    body = await request.body()
    try:
        return process_webhook(db, body, x_razorpay_signature, x_razorpay_event_id)
    except BillingError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
