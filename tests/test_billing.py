from __future__ import annotations

from datetime import timedelta
import hashlib
import hmac
import json
import os
from pathlib import Path
from types import SimpleNamespace
import sys
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT / "backend"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

os.environ.setdefault("USER_DATABASE_URL", "sqlite+pysqlite:///:memory:")
os.environ.setdefault("STATIC_DATABASE_URL", "sqlite+pysqlite:///:memory:")
os.environ.setdefault("PLAYGROUND_DATABASE_URL", "sqlite+pysqlite:///:memory:")

from app.core.config import get_settings
from app.core.database import UserBase
from app.dependencies import require_active_entitlement
from app.models import PaymentCheckout, User, UserEntitlement, utc_now
from app.services.api_keys import save_user_api_key, user_key_env_overrides
from app.services.billing import (
    activate_entitlement,
    billing_plans,
    create_checkout,
    entitlement_is_active,
    process_webhook,
    verify_checkout,
)


class FakeOrderApi:
    def __init__(self) -> None:
        self.last_data = {}

    def create(self, data):
        self.last_data = data
        return {"id": "order_test_123", "status": "created", **data}


class FakeSubscriptionApi:
    def __init__(self) -> None:
        self.last_data = {}

    def create(self, data):
        self.last_data = data
        return {"id": "sub_test_123", "status": "created", **data}


class FakeRazorpayClient:
    def __init__(self) -> None:
        self.order = FakeOrderApi()
        self.subscription = FakeSubscriptionApi()


class BillingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.env = patch.dict(
            os.environ,
            {
                "RAZORPAY_KEY_ID": "rzp_test_key",
                "RAZORPAY_KEY_SECRET": "secret",
                "RAZORPAY_WEBHOOK_SECRET": "webhook_secret",
                "PAYMENT_CURRENCY": "INR",
                "PAYMENT_MONTHLY_PLAN_ID": "plan_month",
                "PAYMENT_YEARLY_PLAN_ID": "plan_year",
                "PAYMENT_MONTHLY_AMOUNT_PAISE": "12000",
                "PAYMENT_YEARLY_AMOUNT_PAISE": "120000",
                "PAYMENT_LIFETIME_AMOUNT_PAISE": "250000",
            },
            clear=False,
        )
        self.env.start()
        get_settings.cache_clear()
        self.engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
        UserBase.metadata.create_all(bind=self.engine)
        self.Session = sessionmaker(bind=self.engine, autoflush=False, autocommit=False, expire_on_commit=False)
        self.db = self.Session()
        self.user = User(email="buyer@example.com", password_hash="x", display_name="Buyer")
        self.db.add(self.user)
        self.db.commit()
        self.db.refresh(self.user)

    def tearDown(self) -> None:
        self.db.close()
        UserBase.metadata.drop_all(bind=self.engine)
        self.env.stop()
        get_settings.cache_clear()

    def test_plan_catalog_is_env_driven(self) -> None:
        plans = {plan.code: plan for plan in billing_plans()}
        self.assertEqual(plans["monthly"].amount_paise, 12000)
        self.assertEqual(plans["yearly"].amount_paise, 120000)
        self.assertEqual(plans["lifetime"].amount_paise, 250000)
        self.assertTrue(plans["monthly"].configured)
        self.assertTrue(plans["lifetime"].configured)

    def test_lifetime_checkout_and_signature_verification_activate_access(self) -> None:
        fake = FakeRazorpayClient()
        with patch("app.services.billing._razorpay_client", return_value=fake):
            checkout = create_checkout(self.db, self.user, "lifetime")

        self.assertEqual(checkout.order_id, "order_test_123")
        self.assertEqual(fake.order.last_data["amount"], 250000)
        signature = _signature("order_test_123|pay_test_123", "secret")
        entitlement = verify_checkout(
            self.db,
            self.user,
            SimpleNamespace(
                checkout_id=checkout.checkout_id,
                razorpay_payment_id="pay_test_123",
                razorpay_signature=signature,
                razorpay_order_id="order_test_123",
                razorpay_subscription_id="",
            ),
        )

        self.assertTrue(entitlement.active)
        self.assertEqual(entitlement.source, "lifetime")
        self.assertIsNone(entitlement.expires_at)

    def test_subscription_checkout_uses_subscription_signature_order(self) -> None:
        fake = FakeRazorpayClient()
        with patch("app.services.billing._razorpay_client", return_value=fake):
            checkout = create_checkout(self.db, self.user, "monthly")

        self.assertEqual(checkout.subscription_id, "sub_test_123")
        self.assertEqual(fake.subscription.last_data["plan_id"], "plan_month")
        signature = _signature("pay_sub_123|sub_test_123", "secret")
        entitlement = verify_checkout(
            self.db,
            self.user,
            SimpleNamespace(
                checkout_id=checkout.checkout_id,
                razorpay_payment_id="pay_sub_123",
                razorpay_signature=signature,
                razorpay_order_id="",
                razorpay_subscription_id="sub_test_123",
            ),
        )

        self.assertTrue(entitlement.active)
        self.assertEqual(entitlement.source, "subscription")
        self.assertEqual(entitlement.plan_code, "monthly")
        self.assertIsNotNone(entitlement.expires_at)

    def test_webhook_processing_is_idempotent_and_can_activate_lifetime_access(self) -> None:
        checkout = PaymentCheckout(
            user_id=self.user.id,
            plan_code="lifetime",
            kind="lifetime",
            amount_paise=250000,
            currency="INR",
            razorpay_order_id="order_webhook",
        )
        self.db.add(checkout)
        self.db.commit()
        body = json.dumps(
            {
                "event": "payment.captured",
                "payload": {"payment": {"entity": {"id": "pay_webhook", "order_id": "order_webhook"}}},
            },
            separators=(",", ":"),
        ).encode("utf-8")
        signature = hmac.new(b"webhook_secret", body, hashlib.sha256).hexdigest()

        first = process_webhook(self.db, body, signature, "evt_1")
        second = process_webhook(self.db, body, signature, "evt_1")

        self.assertEqual(first["status"], "processed")
        self.assertEqual(second["status"], "duplicate")
        entitlement = self.db.get(UserEntitlement, self.user.id)
        self.assertTrue(entitlement_is_active(entitlement))
        self.assertEqual(entitlement.razorpay_payment_id, "pay_webhook")

    def test_payment_required_dependency_blocks_unpaid_users(self) -> None:
        with self.assertRaises(Exception) as raised:
            require_active_entitlement(user=self.user, db=self.db)

        self.assertEqual(getattr(raised.exception, "status_code", None), 402)

        activate_entitlement(
            self.db,
            user_id=self.user.id,
            source="subscription",
            status="active",
            plan_code="monthly",
            expires_at=utc_now() + timedelta(days=3),
        )
        self.db.commit()

        self.assertEqual(require_active_entitlement(user=self.user, db=self.db).id, self.user.id)

    def test_user_api_keys_are_encrypted_and_decoded_for_jobs(self) -> None:
        row = save_user_api_key(self.db, self.user.id, "gemini", "test-gemini-key", "gemini-test-model")

        self.assertTrue(row.encrypted_value.startswith("fernet:"))
        self.assertNotIn("test-gemini-key", row.encrypted_value)
        overrides = user_key_env_overrides(self.db, self.user.id)
        self.assertEqual(overrides["GEMINI_API_KEY"], "test-gemini-key")
        self.assertEqual(overrides["GEMINI_MODEL"], "gemini-test-model")


def _signature(message: str, secret: str) -> str:
    return hmac.new(secret.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).hexdigest()
