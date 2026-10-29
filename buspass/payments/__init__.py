"""Payment providers behind one interface. Pick one with PAYMENT_PROVIDER (mock | stripe | paymob | fawry)."""

from flask import current_app

from .base import CheckoutSession, PaymentProvider, WebhookEvent
from .fawry import FawryProvider
from .mock import MockProvider
from .paymob import PaymobProvider
from .stripe_provider import StripeProvider

PROVIDERS = {"mock": MockProvider, "stripe": StripeProvider, "paymob": PaymobProvider, "fawry": FawryProvider}


def get_provider(name=None) -> PaymentProvider:
    name = name or current_app.config["PAYMENT_PROVIDER"]
    return PROVIDERS[name](current_app.config)


__all__ = ["CheckoutSession", "PaymentProvider", "WebhookEvent", "get_provider", "PROVIDERS"]
