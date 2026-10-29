"""Checkout, webhook processing (exactly-once) and refunds."""

import logging

from flask import current_app
from sqlalchemy.exc import IntegrityError

from .. import repositories as repo
from ..errors import Conflict, NotFound, PaymentError, ValidationFailed
from ..extensions import db
from ..models import Pass, Payment, PaymentEvent, utcnow
from ..payments import get_provider
from ..timeutil import format_money
from . import audit, notify, passes, pricing, sponsors, wallet

log = logging.getLogger(__name__)

TOPUP_MIN, TOPUP_MAX = 20_00, 5_000_00


def start_checkout(user, purpose, idempotency_key, amount_cents=None, **params):
    existing = repo.Payments.by_idempotency(user.id, idempotency_key)
    if existing:
        return existing
    currency = current_app.config["CURRENCY"]
    if purpose == "topup":
        if amount_cents is None or not TOPUP_MIN <= amount_cents <= TOPUP_MAX:
            raise ValidationFailed(
                f"Top-up must be between {TOPUP_MIN // 100} and {TOPUP_MAX // 100} {currency}.",
                details={"field": "amount_cents"},
            )
        meta, description = {}, f"Wallet top-up {format_money(amount_cents, currency)}"
    elif purpose == "pass":
        route, pass_type = passes.load_product(params["route_id"], params["pass_type"])
        start = passes.parse_start(params.get("start_date"))
        passes.check_capacity(route, pass_type, start)
        q = pricing.quote(user, route, pass_type, params.get("promo_code"))
        amount_cents = q["total_cents"]
        if amount_cents == 0:
            raise ValidationFailed("This pass is free with your discount — use wallet checkout instead.")
        meta = {
            "route_id": route.id,
            "pass_type": pass_type.code,
            "start_date": start.isoformat(),
            "promo_code": params.get("promo_code"),
            "auto_renew": bool(params.get("auto_renew")),
            "discount_cents": q["discount_cents"],
        }
        description = f"{pass_type.name_en} — {route.code} {route.name_en}"
    elif purpose == "sponsor_seats":
        meta, amount_cents, description = sponsors.prepare_purchase(user, **params)
    else:
        raise ValidationFailed("Unknown payment purpose.")

    provider = get_provider()
    payment = repo.add(
        Payment(
            user_id=user.id,
            purpose=purpose,
            amount_cents=amount_cents,
            currency=currency,
            provider=provider.name,
            idempotency_key=idempotency_key,
            meta=meta,
        )
    )
    try:
        db.session.flush()
    except IntegrityError:
        db.session.rollback()
        return repo.Payments.by_idempotency(user.id, idempotency_key)
    base = current_app.config["PUBLIC_BASE_URL"].rstrip("/")
    back = f"{base}/sponsor" if purpose == "sponsor_seats" else f"{base}/app#/payment/{payment.id}"
    session = provider.create_checkout(payment, description, success_url=back, cancel_url=back)
    payment.provider_ref = session.provider_ref
    payment.meta = {**meta, "checkout_url": session.checkout_url, "description": description}
    db.session.commit()
    log.info(
        "checkout_started",
        extra={"payment_id": payment.id, "purpose": purpose, "amount_cents": amount_cents, "provider": provider.name},
    )
    return payment


def handle_webhook(provider_name, body, headers):
    provider = get_provider(provider_name)
    try:
        event = provider.parse_webhook(body, headers)
    except (ValueError, KeyError) as e:
        log.warning("webhook_rejected", extra={"provider": provider_name, "reason": str(e)})
        raise PaymentError("Invalid webhook signature.", code="bad_signature", status=400) from None

    if repo.Payments.event_seen(provider_name, event.event_id):
        return {"status": "duplicate"}
    payment = (
        repo.get_for_update(Payment, event.payment_id)
        if event.payment_id
        else repo.Payments.by_provider_ref(provider_name, event.provider_ref)
    )
    repo.add(
        PaymentEvent(
            provider=provider_name, event_id=event.event_id, type=event.type, payment_id=payment.id if payment else None
        )
    )
    try:
        db.session.flush()  # unique (provider, event_id): a concurrent duplicate delivery fails here
    except IntegrityError:
        db.session.rollback()
        return {"status": "duplicate"}

    if payment is None or event.type == "ignored":
        db.session.commit()
        return {"status": "ignored"}
    if event.type == "payment.succeeded":
        if event.amount_cents is not None and event.amount_cents != payment.amount_cents:
            log.error("webhook_amount_mismatch", extra={"payment_id": payment.id})
            payment.status = "failed"
        elif payment.status == "pending":
            fulfill(payment)
    elif event.type == "payment.failed" and payment.status == "pending":
        payment.status = "failed"
    db.session.commit()
    return {"status": payment.status}


def fulfill(payment):
    payment.status, payment.completed_at = "succeeded", utcnow()
    user = payment.user
    amount = format_money(payment.amount_cents, payment.currency)
    if payment.purpose == "topup":
        wallet.credit(user.id, payment.amount_cents, "topup", reference=payment.id)
        wallet.create_receipt(
            user.id, "Wallet top-up", payment.amount_cents, "card", payment_id=payment.id, revenue=False
        )
        notify.notify(
            user, "payment", "payment_success", what={"en": "Wallet top-up", "ar": "شحن المحفظة"}, amount=amount
        )
    elif payment.purpose == "pass":
        if passes.fulfill_card_purchase(payment):
            notify.notify(
                user, "payment", "payment_success", what={"en": "Pass purchase", "ar": "شراء اشتراك"}, amount=amount
            )
    elif payment.purpose == "sponsor_seats":
        sponsors.fulfill_purchase(payment)
    audit.record("payment.succeeded", "payment", payment.id, {"amount_cents": payment.amount_cents}, actor=user)


def get_owned(user, payment_id):
    payment = repo.get(Payment, payment_id)
    if payment is None or (payment.user_id != user.id and user.role != "admin"):
        raise NotFound("Payment not found.")
    return payment


def refund(admin, payment_id, target="wallet", reason=""):
    payment = repo.get_for_update(Payment, payment_id)
    if payment is None:
        raise NotFound("Payment not found.")
    if payment.status != "succeeded":
        raise Conflict("Only successful payments can be refunded.")
    amount = payment.amount_cents - payment.refunded_cents
    if payment.purpose == "topup":
        # Money already spent from the wallet can't be refunded twice.
        amount = min(amount, payment.user.balance_cents)
        if amount <= 0:
            raise Conflict("The top-up has already been spent.")
        wallet.debit(payment.user_id, amount, "adjustment", reference=f"refund:{payment.id}")
        target = "card"
    if target == "card":
        try:
            get_provider(payment.provider).refund(payment, amount)
        except NotImplementedError as e:
            raise PaymentError(str(e), code="refund_unsupported") from None
    else:
        wallet.credit(payment.user_id, amount, "refund", reference=payment.id)
    for p in db.session.query(Pass).filter_by(payment_id=payment.id).all():
        p.status = "refunded"
    payment.refunded_cents += amount
    payment.status = "refunded"
    notify.notify(
        payment.user,
        "payment",
        "refund",
        amount=format_money(amount, payment.currency),
        target={"en": "wallet" if target == "wallet" else "card", "ar": "المحفظة" if target == "wallet" else "البطاقة"},
    )
    audit.record(
        "payment.refunded",
        "payment",
        payment.id,
        {"amount_cents": amount, "target": target, "reason": reason},
        actor=admin,
    )
    db.session.commit()
    return payment


def refund_wallet_pass(admin, pass_id, reason=""):
    """Refund a pass bought with wallet balance back to the wallet."""
    p = repo.get_for_update(Pass, pass_id)
    if p is None:
        raise NotFound("Pass not found.")
    if p.payment_id:
        return refund(admin, p.payment_id, "wallet", reason)
    if p.status not in ("active", "expired") or p.source == "sponsor":
        raise Conflict("This pass can't be refunded.")
    wallet.credit(p.user_id, p.price_cents, "refund", reference=p.id)
    p.status = "refunded"
    notify.notify(
        p.user,
        "payment",
        "refund",
        amount=format_money(p.price_cents, current_app.config["CURRENCY"]),
        target={"en": "wallet", "ar": "المحفظة"},
    )
    audit.record("pass.refunded", "pass", p.id, {"amount_cents": p.price_cents, "reason": reason}, actor=admin)
    db.session.commit()
    return p
