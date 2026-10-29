"""Fawry (Egypt) adapter — ready to wire up, not exercised against the live API in this build.

Fawry Pay supports card and "pay at Fawry outlet" reference numbers. The server-to-server notification
is verified with SHA-256 over the documented field concatenation plus the merchant security key.
Confirm the exact field order with Fawry's integration docs for your account before going live.
"""

import hashlib
import hmac
import json

from .base import CheckoutSession, PaymentProvider, WebhookEvent


class FawryProvider(PaymentProvider):
    name = "fawry"

    def __init__(self, config):
        super().__init__(config)
        if not (config["FAWRY_MERCHANT_CODE"] and config["FAWRY_SECURITY_KEY"]):
            raise RuntimeError("FAWRY_MERCHANT_CODE and FAWRY_SECURITY_KEY must be set")

    def charge_signature(self, payment, return_url):
        amount = f"{payment.amount_cents / 100:.2f}"
        raw = (
            self.config["FAWRY_MERCHANT_CODE"]
            + payment.id
            + str(payment.user_id)
            + return_url
            + f"{payment.purpose}1{amount}"
            + self.config["FAWRY_SECURITY_KEY"]
        )
        return hashlib.sha256(raw.encode()).hexdigest()

    def create_checkout(self, payment, description, success_url, cancel_url):
        # Fawry's hosted checkout is opened client-side with the FawryPay JS SDK using these params.
        sig = self.charge_signature(payment, success_url)
        return CheckoutSession(provider_ref=payment.id, checkout_url=f"/pay/fawry/{payment.id}?signature={sig}")

    def parse_webhook(self, body, headers):
        data = json.loads(body)
        fields = [
            data.get("fawryRefNumber", ""),
            data.get("merchantRefNumber", ""),
            f"{float(data.get('paymentAmount', 0)):.2f}",
            f"{float(data.get('orderAmount', 0)):.2f}",
            data.get("orderStatus", ""),
            data.get("paymentMethod", ""),
            data.get("paymentRefrenceNumber", ""),
        ]
        expected = hashlib.sha256(("".join(fields) + self.config["FAWRY_SECURITY_KEY"]).encode()).hexdigest()
        if not hmac.compare_digest(expected, data.get("messageSignature", "")):
            raise ValueError("bad signature")
        status = data.get("orderStatus")
        kind = {"PAID": "payment.succeeded", "EXPIRED": "payment.failed", "FAILED": "payment.failed"}.get(
            status, "ignored"
        )
        return WebhookEvent(
            event_id=f"{data.get('fawryRefNumber')}:{status}",
            type=kind,
            provider_ref=data.get("merchantRefNumber"),
            payment_id=data.get("merchantRefNumber"),
            amount_cents=round(float(data.get("paymentAmount", 0)) * 100),
            raw={"status": status},
        )
