"""Test provider: a local hosted-checkout page that sends a signed webhook, just like a real gateway."""

import hashlib
import hmac
import json
import uuid

from .base import CheckoutSession, PaymentProvider, WebhookEvent


class MockProvider(PaymentProvider):
    name = "mock"

    def create_checkout(self, payment, description, success_url, cancel_url):
        ref = "mock_" + uuid.uuid4().hex[:16]
        return CheckoutSession(provider_ref=ref, checkout_url=f"/pay/mock/{payment.id}")

    def sign(self, body: bytes):
        return hmac.new(self.config["MOCK_WEBHOOK_SECRET"].encode(), body, hashlib.sha256).hexdigest()

    def build_event(self, payment, outcome):
        body = json.dumps(
            {
                "id": "evt_" + uuid.uuid4().hex,
                "type": f"payment.{outcome}",
                "provider_ref": payment.provider_ref,
                "payment_id": payment.id,
                "amount_cents": payment.amount_cents,
            }
        ).encode()
        return body, self.sign(body)

    def parse_webhook(self, body, headers):
        if not hmac.compare_digest(headers.get("X-Mock-Signature", ""), self.sign(body)):
            raise ValueError("bad signature")
        data = json.loads(body)
        return WebhookEvent(
            event_id=data["id"],
            type=data["type"],
            provider_ref=data["provider_ref"],
            payment_id=data["payment_id"],
            amount_cents=data["amount_cents"],
            raw=data,
        )

    def refund(self, payment, amount_cents):
        return {"refund_id": "mock_re_" + uuid.uuid4().hex[:12]}
