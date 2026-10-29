"""Paymob (Egypt) adapter — ready to wire up, not exercised against the live API in this build.

Flow: create an "intention" with the secret key, send the rider to the unified checkout, receive the
transaction-processed callback, and verify its HMAC-SHA512 over Paymob's documented field order.
Check field order and endpoints against your Paymob dashboard docs before going live.
"""

import hashlib
import hmac
import json

import requests

from .base import CheckoutSession, PaymentProvider, WebhookEvent

HMAC_FIELDS = [
    "amount_cents",
    "created_at",
    "currency",
    "error_occured",
    "has_parent_transaction",
    "id",
    "integration_id",
    "is_3d_secure",
    "is_auth",
    "is_capture",
    "is_refunded",
    "is_standalone_payment",
    "is_voided",
    "order.id",
    "owner",
    "pending",
    "source_data.pan",
    "source_data.sub_type",
    "source_data.type",
    "success",
]


def _get(obj, dotted):
    for part in dotted.split("."):
        obj = (obj or {}).get(part)
    if isinstance(obj, bool):
        return str(obj).lower()
    return "" if obj is None else str(obj)


class PaymobProvider(PaymentProvider):
    name = "paymob"
    API = "https://accept.paymob.com"

    def __init__(self, config):
        super().__init__(config)
        if not (config["PAYMOB_API_KEY"] and config["PAYMOB_HMAC_SECRET"] and config["PAYMOB_INTEGRATION_ID"]):
            raise RuntimeError("PAYMOB_API_KEY, PAYMOB_HMAC_SECRET and PAYMOB_INTEGRATION_ID must be set")

    def create_checkout(self, payment, description, success_url, cancel_url):
        resp = requests.post(
            f"{self.API}/v1/intention/",
            timeout=15,
            headers={"Authorization": f"Token {self.config['PAYMOB_API_KEY']}"},
            json={
                "amount": payment.amount_cents,
                "currency": payment.currency,
                "payment_methods": [int(self.config["PAYMOB_INTEGRATION_ID"])],
                "items": [{"name": description[:50], "amount": payment.amount_cents, "quantity": 1}],
                "special_reference": payment.id,
                "redirection_url": success_url,
                "billing_data": {
                    "first_name": payment.user.name,
                    "last_name": "-",
                    "email": payment.user.email or "na@example.com",
                    "phone_number": payment.user.phone or "+200000000000",
                },
            },
        )
        resp.raise_for_status()
        data = resp.json()
        return CheckoutSession(
            provider_ref=str(data["id"]),
            checkout_url=f"{self.API}/unifiedcheckout/?publicKey=&clientSecret={data['client_secret']}",
        )

    def parse_webhook(self, body, headers):
        data = json.loads(body)
        obj = data.get("obj", {})
        concatenated = "".join(_get(obj, f) for f in HMAC_FIELDS)
        expected = hmac.new(
            self.config["PAYMOB_HMAC_SECRET"].encode(), concatenated.encode(), hashlib.sha512
        ).hexdigest()
        if not hmac.compare_digest(expected, headers.get("X-Paymob-Hmac", data.get("hmac", ""))):
            raise ValueError("bad signature")
        kind = "payment.succeeded" if obj.get("success") and not obj.get("pending") else "payment.failed"
        return WebhookEvent(
            event_id=f"txn_{obj.get('id')}",
            type=kind,
            provider_ref=None,
            payment_id=_get(obj, "order.merchant_order_id") or obj.get("special_reference"),
            amount_cents=obj.get("amount_cents"),
            raw={"id": obj.get("id")},
        )
