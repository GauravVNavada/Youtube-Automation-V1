from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import PaymentCheckout, RazorpayWebhookEvent, User, UserEntitlement, utc_now, uuid_str
from app.schemas import BillingCheckoutOut, BillingPlanOut, EntitlementOut


SUBSCRIPTION_PLAN_CODES = {"monthly", "yearly"}
ACTIVE_SUBSCRIPTION_STATUSES = {"active", "authenticated", "charged"}
INACTIVE_SUBSCRIPTION_STATUSES = {"cancelled", "completed", "expired", "halted", "paused"}


class BillingError(RuntimeError):
    pass


@dataclass(frozen=True)
class BillingPlan:
    code: str
    label: str
    kind: str
    amount_paise: int
    currency: str
    interval: str = ""
    razorpay_plan_id: str = ""

    @property
    def configured(self) -> bool:
        settings = get_settings()
        has_keys = bool(settings.razorpay_key_id and settings.razorpay_key_secret)
        if self.kind == "subscription":
            return has_keys and bool(self.razorpay_plan_id)
        return has_keys and self.amount_paise > 0

    def to_schema(self) -> BillingPlanOut:
        return BillingPlanOut(
            code=self.code,
            label=self.label,
            kind=self.kind,
            amount_paise=self.amount_paise,
            currency=self.currency,
            interval=self.interval,
            configured=self.configured,
        )


def plan_catalog() -> list[BillingPlan]:
    settings = get_settings()
    currency = settings.payment_currency.upper()
    return [
        BillingPlan(
            code="monthly",
            label="Monthly Subscription",
            kind="subscription",
            amount_paise=max(0, settings.payment_monthly_amount_paise),
            currency=currency,
            interval="monthly",
            razorpay_plan_id=settings.payment_monthly_plan_id,
        ),
        BillingPlan(
            code="yearly",
            label="Yearly Subscription",
            kind="subscription",
            amount_paise=max(0, settings.payment_yearly_amount_paise),
            currency=currency,
            interval="yearly",
            razorpay_plan_id=settings.payment_yearly_plan_id,
        ),
        BillingPlan(
            code="lifetime",
            label="Lifetime Access",
            kind="lifetime",
            amount_paise=max(0, settings.payment_lifetime_amount_paise),
            currency=currency,
        ),
    ]


def billing_plans() -> list[BillingPlanOut]:
    return [plan.to_schema() for plan in plan_catalog()]


def get_plan(plan_code: str) -> BillingPlan:
    normalized = str(plan_code or "").strip().lower()
    for plan in plan_catalog():
        if plan.code == normalized:
            return plan
    raise BillingError("Unknown payment plan")


def create_checkout(db: Session, user: User, plan_code: str) -> BillingCheckoutOut:
    settings = get_settings()
    plan = get_plan(plan_code)
    if not plan.configured:
        raise BillingError("This payment plan is not configured")

    client = _razorpay_client()
    checkout = PaymentCheckout(
        id=uuid_str(),
        user_id=user.id,
        plan_code=plan.code,
        kind=plan.kind,
        amount_paise=plan.amount_paise,
        currency=plan.currency,
        checkout_metadata={"label": plan.label, "interval": plan.interval},
    )

    if plan.kind == "subscription":
        subscription = client.subscription.create(
            data={
                "plan_id": plan.razorpay_plan_id,
                "total_count": 120 if plan.interval == "monthly" else 10,
                "customer_notify": 1,
                "notes": _razorpay_notes(user, checkout, plan),
            }
        )
        checkout.razorpay_subscription_id = str(subscription.get("id") or "")
        checkout.checkout_metadata = {**checkout.checkout_metadata, "razorpay_subscription": subscription}
    else:
        order = client.order.create(
            data={
                "amount": plan.amount_paise,
                "currency": plan.currency,
                "receipt": checkout.id[:40],
                "notes": _razorpay_notes(user, checkout, plan),
            }
        )
        checkout.razorpay_order_id = str(order.get("id") or "")
        checkout.checkout_metadata = {**checkout.checkout_metadata, "razorpay_order": order}

    db.add(checkout)
    db.commit()
    db.refresh(checkout)
    return _checkout_out(checkout, user, plan, settings.razorpay_key_id)


def verify_checkout(db: Session, user: User, payload: Any) -> EntitlementOut:
    checkout = db.get(PaymentCheckout, payload.checkout_id)
    if checkout is None or checkout.user_id != user.id:
        raise BillingError("Payment checkout was not found")
    if checkout.status == "verified":
        return entitlement_out(db, user)

    payment_id = payload.razorpay_payment_id.strip()
    signature = payload.razorpay_signature.strip()
    if checkout.kind == "subscription":
        subscription_id = payload.razorpay_subscription_id.strip()
        if subscription_id != checkout.razorpay_subscription_id:
            raise BillingError("Subscription id does not match checkout")
        expected_message = f"{payment_id}|{subscription_id}"
    else:
        order_id = payload.razorpay_order_id.strip()
        if order_id != checkout.razorpay_order_id:
            raise BillingError("Order id does not match checkout")
        expected_message = f"{order_id}|{payment_id}"

    if not verify_razorpay_signature(expected_message.encode("utf-8"), signature, get_settings().razorpay_key_secret):
        checkout.status = "failed"
        db.commit()
        raise BillingError("Payment signature verification failed")

    checkout.status = "verified"
    checkout.razorpay_payment_id = payment_id
    checkout.razorpay_signature = signature
    checkout.verified_at = utc_now()
    activate_entitlement(
        db,
        user_id=user.id,
        source="subscription" if checkout.kind == "subscription" else "lifetime",
        status="active",
        plan_code=checkout.plan_code,
        razorpay_subscription_id=checkout.razorpay_subscription_id,
        razorpay_payment_id=payment_id,
    )
    db.commit()
    return entitlement_out(db, user)


def entitlement_out(db: Session, user: User) -> EntitlementOut:
    entitlement = db.get(UserEntitlement, user.id)
    return EntitlementOut(
        active=entitlement_is_active(entitlement),
        source=entitlement.source if entitlement else "none",
        status=entitlement.status if entitlement else "inactive",
        plan_code=entitlement.plan_code if entitlement else "",
        expires_at=entitlement.expires_at if entitlement else None,
    )


def entitlement_is_active(entitlement: UserEntitlement | None) -> bool:
    if entitlement is None:
        return False
    if entitlement.status not in {"active", "authenticated", "charged"}:
        return False
    expires_at = _aware(entitlement.expires_at)
    return expires_at is None or expires_at > utc_now()


def activate_entitlement(
    db: Session,
    *,
    user_id: int,
    source: str,
    status: str,
    plan_code: str,
    razorpay_subscription_id: str = "",
    razorpay_payment_id: str = "",
    expires_at: datetime | None = None,
) -> UserEntitlement:
    now = utc_now()
    entitlement = db.get(UserEntitlement, user_id)
    if entitlement is None:
        entitlement = UserEntitlement(user_id=user_id, starts_at=now)
        db.add(entitlement)

    entitlement.source = source
    entitlement.status = status
    entitlement.plan_code = plan_code
    entitlement.razorpay_subscription_id = razorpay_subscription_id or entitlement.razorpay_subscription_id
    entitlement.razorpay_payment_id = razorpay_payment_id or entitlement.razorpay_payment_id
    entitlement.last_verified_at = now
    entitlement.updated_at = now
    if expires_at is not None:
        entitlement.expires_at = expires_at
    elif source == "subscription":
        entitlement.expires_at = now + _subscription_fallback_window(plan_code)
    else:
        entitlement.expires_at = None
    return entitlement


def process_webhook(db: Session, body: bytes, signature: str, event_id: str) -> dict[str, str]:
    settings = get_settings()
    if settings.razorpay_webhook_secret:
        if not verify_razorpay_signature(body, signature, settings.razorpay_webhook_secret):
            raise BillingError("Webhook signature verification failed")

    normalized_event_id = event_id.strip() or uuid_str()
    existing = db.scalar(select(RazorpayWebhookEvent).where(RazorpayWebhookEvent.event_id == normalized_event_id))
    if existing:
        return {"status": "duplicate", "event_id": normalized_event_id}

    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BillingError("Webhook payload is invalid JSON") from exc

    event_type = str(payload.get("event") or "")
    event = RazorpayWebhookEvent(event_id=normalized_event_id, event_type=event_type, payload=payload, processed_at=utc_now())
    db.add(event)
    _apply_webhook_payload(db, event_type, payload)
    db.commit()
    return {"status": "processed", "event_id": normalized_event_id}


def verify_razorpay_signature(message: bytes, signature: str, secret: str) -> bool:
    if not secret or not signature:
        return False
    expected = hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def _apply_webhook_payload(db: Session, event_type: str, payload: dict[str, Any]) -> None:
    entities = payload.get("payload") if isinstance(payload.get("payload"), dict) else {}
    subscription = _entity(entities, "subscription")
    payment = _entity(entities, "payment")

    if subscription:
        _apply_subscription_event(db, event_type, subscription, payment)
    if payment:
        _apply_payment_event(db, event_type, payment)


def _apply_subscription_event(db: Session, event_type: str, subscription: dict[str, Any], payment: dict[str, Any]) -> None:
    subscription_id = str(subscription.get("id") or payment.get("subscription_id") or "")
    if not subscription_id:
        return
    status = _subscription_status(event_type, str(subscription.get("status") or ""))
    expires_at = _datetime_from_unix(subscription.get("current_end"))
    entitlement = db.scalar(
        select(UserEntitlement).where(UserEntitlement.razorpay_subscription_id == subscription_id)
    )
    checkout = db.scalar(
        select(PaymentCheckout).where(PaymentCheckout.razorpay_subscription_id == subscription_id)
    )
    if entitlement is None and checkout is not None:
        entitlement = activate_entitlement(
            db,
            user_id=checkout.user_id,
            source="subscription",
            status=status,
            plan_code=checkout.plan_code,
            razorpay_subscription_id=subscription_id,
            razorpay_payment_id=str(payment.get("id") or ""),
            expires_at=expires_at,
        )
    if entitlement is not None:
        entitlement.status = status
        entitlement.source = "subscription"
        entitlement.razorpay_subscription_id = subscription_id
        if payment.get("id"):
            entitlement.razorpay_payment_id = str(payment["id"])
        if expires_at is not None:
            entitlement.expires_at = expires_at
        entitlement.last_verified_at = utc_now()
        entitlement.updated_at = utc_now()


def _apply_payment_event(db: Session, event_type: str, payment: dict[str, Any]) -> None:
    if event_type != "payment.captured":
        return
    order_id = str(payment.get("order_id") or "")
    if not order_id:
        return
    checkout = db.scalar(select(PaymentCheckout).where(PaymentCheckout.razorpay_order_id == order_id))
    if checkout is None or checkout.kind != "lifetime":
        return
    checkout.status = "verified"
    checkout.razorpay_payment_id = str(payment.get("id") or checkout.razorpay_payment_id)
    checkout.verified_at = checkout.verified_at or utc_now()
    activate_entitlement(
        db,
        user_id=checkout.user_id,
        source="lifetime",
        status="active",
        plan_code=checkout.plan_code,
        razorpay_payment_id=checkout.razorpay_payment_id,
    )


def _subscription_status(event_type: str, fallback_status: str) -> str:
    if event_type in {"subscription.activated", "subscription.charged", "subscription.authenticated"}:
        return "active"
    if event_type in {"subscription.cancelled", "subscription.completed"}:
        return "cancelled"
    if event_type in {"subscription.halted", "subscription.paused"}:
        return "past_due"
    if fallback_status in ACTIVE_SUBSCRIPTION_STATUSES:
        return "active"
    if fallback_status in INACTIVE_SUBSCRIPTION_STATUSES:
        return fallback_status
    return fallback_status or "active"


def _entity(payload: dict[str, Any], name: str) -> dict[str, Any]:
    row = payload.get(name)
    if isinstance(row, dict) and isinstance(row.get("entity"), dict):
        return row["entity"]
    return {}


def _checkout_out(checkout: PaymentCheckout, user: User, plan: BillingPlan, key_id: str) -> BillingCheckoutOut:
    return BillingCheckoutOut(
        checkout_id=checkout.id,
        key_id=key_id,
        plan_code=plan.code,
        label=plan.label,
        kind=plan.kind,
        amount_paise=plan.amount_paise,
        currency=plan.currency,
        order_id=checkout.razorpay_order_id,
        subscription_id=checkout.razorpay_subscription_id,
        prefill={"name": user.display_name or "", "email": user.email},
    )


def _razorpay_client():
    settings = get_settings()
    try:
        import razorpay
    except ImportError as exc:  # pragma: no cover - covered after dependency install in Docker.
        raise BillingError("The razorpay Python package is not installed") from exc
    return razorpay.Client(auth=(settings.razorpay_key_id, settings.razorpay_key_secret))


def _razorpay_notes(user: User, checkout: PaymentCheckout, plan: BillingPlan) -> dict[str, str]:
    return {
        "user_id": str(user.id),
        "email": user.email[:256],
        "checkout_id": checkout.id,
        "plan_code": plan.code,
    }


def _subscription_fallback_window(plan_code: str) -> timedelta:
    if plan_code == "yearly":
        return timedelta(days=370)
    return timedelta(days=32)


def _datetime_from_unix(value: Any) -> datetime | None:
    try:
        timestamp = int(value)
    except (TypeError, ValueError):
        return None
    if timestamp <= 0:
        return None
    return datetime.fromtimestamp(timestamp, timezone.utc)


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value
