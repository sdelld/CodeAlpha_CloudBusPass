"""Stripe Checkout (use test-mode keys `sk_test_…` and a webhook signing secret `whsec_…`)."""

import stripe

from .base import CheckoutSession, PaymentProvider, WebhookEvent


class StripeProvider(PaymentProvider):
    name = "stripe"

    def __init__(self, config):
        super().__init__(config)
        if not config["STRIPE_SECRET_KEY"]:
            raise RuntimeError("STRIPE_SECRET_KEY is not set")
        self.client = stripe.StripeClient(config["STRIPE_SECRET_KEY"])

    def create_checkout(self, payment, description, success_url, cancel_url):
        session = self.client.v1.checkout.sessions.create(
            params={
                "mode": "payment",
                "line_items": [
                    {
                        "quantity": 1,
                        "price_data": {
                            "currency": payment.currency.lower(),
                            "unit_amount": payment.amount_cents,
                            "product_data": {"name": description},
                        },
                    }
                ],
                "success_url": success_url,
                "cancel_url": cancel_url,
                "client_reference_id": payment.id,
                "metadata": {"payment_id": payment.id},
            },
            options={"idempotency_key": f"checkout-{payment.id}"},
        )
        return CheckoutSession(provider_ref=session.id, checkout_url=session.url)

    def parse_webhook(self, body, headers):
        try:
            event = stripe.Webhook.construct_event(
                body, headers.get("Stripe-Signature", ""), self.config["STRIPE_WEBHOOK_SECRET"]
            )
        except (ValueError, stripe.SignatureVerificationError) as e:
            raise ValueError(str(e)) from None
        obj = event["data"]["object"]
        mapping = {
            "checkout.session.completed": "payment.succeeded",
            "checkout.session.async_payment_succeeded": "payment.succeeded",
            "checkout.session.async_payment_failed": "payment.failed",
            "checkout.session.expired": "payment.failed",
        }
        kind = mapping.get(event["type"], "ignored")
        if kind == "payment.succeeded" and obj.get("payment_status") not in ("paid", "no_payment_required"):
            kind = "ignored"  # e.g. bank transfer still pending; the async_payment_* event follows
        return WebhookEvent(
            event_id=event["id"],
            type=kind,
            provider_ref=obj.get("id"),
            payment_id=(obj.get("metadata") or {}).get("payment_id"),
            amount_cents=obj.get("amount_total"),
            raw={"type": event["type"]},
        )

    def refund(self, payment, amount_cents):
        session = self.client.v1.checkout.sessions.retrieve(payment.provider_ref)
        refund = self.client.v1.refunds.create(
            params={"payment_intent": session.payment_intent, "amount": amount_cents},
            options={"idempotency_key": f"refund-{payment.id}-{amount_cents}"},
        )
        return {"refund_id": refund.id}
