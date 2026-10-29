from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class CheckoutSession:
    provider_ref: str
    checkout_url: str


@dataclass
class WebhookEvent:
    event_id: str  # unique per provider; used to process each event exactly once
    type: str  # payment.succeeded | payment.failed | ignored
    provider_ref: str | None = None
    payment_id: str | None = None
    amount_cents: int | None = None
    raw: dict = field(default_factory=dict)


class PaymentProvider(ABC):
    name = "base"

    def __init__(self, config):
        self.config = config

    @abstractmethod
    def create_checkout(self, payment, description, success_url, cancel_url) -> CheckoutSession:
        """Start a hosted checkout for `payment` and return where to send the rider."""

    @abstractmethod
    def parse_webhook(self, body: bytes, headers) -> WebhookEvent:
        """Verify the webhook signature and translate it into a WebhookEvent. Raise ValueError if invalid."""

    def refund(self, payment, amount_cents):
        """Refund to the original card. Providers that can't do it automatically raise NotImplementedError."""
        raise NotImplementedError(f"{self.name} refunds must be issued from the provider dashboard")
