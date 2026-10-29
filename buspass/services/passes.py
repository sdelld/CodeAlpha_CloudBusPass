"""Buying, renewing and managing passes."""

import logging
from datetime import date, timedelta

from flask import current_app
from sqlalchemy.exc import IntegrityError

from .. import repositories as repo
from ..errors import Conflict, NotFound, ValidationFailed
from ..extensions import db
from ..models import Pass, Route, new_qr_secret
from ..timeutil import format_money, local_today
from . import audit, notify, pricing, wallet

log = logging.getLogger(__name__)
MAX_DAYS_AHEAD = 30


def serialize(p, owner=True):
    d = {
        "id": p.id,
        "route": p.route.to_dict(),
        "pass_type": p.pass_type.to_dict(),
        "status": display_status(p),
        "valid_from": p.valid_from.isoformat(),
        "valid_until": p.valid_until.isoformat(),
        "price_cents": p.price_cents,
        "discount_cents": p.discount_cents,
        "rides_used": p.rides_used,
        "auto_renew": p.auto_renew,
        "source": p.source,
        "created_at": p.created_at.isoformat(),
    }
    if owner and d["status"] in ("active", "upcoming"):
        # Lets the rider app generate rotating QR codes offline until the pass ends.
        d["qr"] = {"secret": p.qr_secret, "kind": "P", "window_seconds": current_app.config["QR_WINDOW_SECONDS"]}
    return d


def display_status(p, today=None):
    today = today or local_today()
    if p.status == "active":
        if p.valid_until < today:
            return "expired"
        if p.valid_from > today:
            return "upcoming"
    return p.status


def parse_start(start):
    today = local_today()
    start = start or today
    if isinstance(start, str):
        start = date.fromisoformat(start)
    if not today <= start <= today + timedelta(days=MAX_DAYS_AHEAD):
        raise ValidationFailed(
            f"Start date must be between today and {MAX_DAYS_AHEAD} days ahead.", details={"field": "start_date"}
        )
    return start


def load_product(route_id, pass_type_code):
    route = repo.get(Route, route_id)
    pass_type = repo.PassTypes.by_code(pass_type_code)
    if route is None or not route.active:
        raise NotFound("Route not found.")
    if pass_type is None or not pass_type.active:
        raise NotFound("Pass type not found.")
    return route, pass_type


def check_capacity(route, pass_type, start):
    if pass_type.max_rides == 1 and repo.Passes.singles_sold(route.id, start) >= route.daily_single_capacity:
        raise Conflict("Sorry, single tickets for this route are sold out for that day.", code="sold_out")


def create_pass(
    user,
    route,
    pass_type,
    start,
    price_cents,
    discount_cents,
    source="purchase",
    payment_id=None,
    idempotency_key=None,
    auto_renew=False,
    sponsor_block_id=None,
):
    p = repo.add(
        Pass(
            user_id=user.id,
            route_id=route.id,
            pass_type_id=pass_type.id,
            valid_from=start,
            valid_until=start + timedelta(days=pass_type.validity_days - 1),
            price_cents=price_cents,
            discount_cents=discount_cents,
            source=source,
            payment_id=payment_id,
            idempotency_key=idempotency_key,
            auto_renew=auto_renew and pass_type.max_rides != 1,
            sponsor_block_id=sponsor_block_id,
        )
    )
    p.route, p.pass_type = route, pass_type
    notify.notify(
        user,
        "payment",
        "pass_active",
        product={"en": pass_type.name_en, "ar": pass_type.name_ar},
        route=route.code,
        until=p.valid_until.isoformat(),
    )
    return p


def buy_with_wallet(
    user, route_id, pass_type_code, start_date=None, promo_code=None, idempotency_key=None, auto_renew=False
):
    existing = repo.Passes.by_idempotency(user.id, idempotency_key) if idempotency_key else None
    if existing:
        return existing
    route, pass_type = load_product(route_id, pass_type_code)
    start = parse_start(start_date)
    # Lock the route row so concurrent buyers can't both take the last single seat.
    repo.get_for_update(Route, route.id)
    check_capacity(route, pass_type, start)
    q = pricing.quote(user, route, pass_type, promo_code, lock_promo=True)
    wallet.debit(user.id, q["total_cents"], "pass_purchase", reference=f"{route.code}/{pass_type.code}")
    p = create_pass(
        user,
        route,
        pass_type,
        start,
        q["total_cents"],
        q["discount_cents"],
        idempotency_key=idempotency_key,
        auto_renew=auto_renew,
    )
    if q["promo"]:
        q["promo"].used_count += 1
    db.session.flush()
    wallet.create_receipt(
        user.id,
        f"{pass_type.name_en} — {route.code} {route.name_en}",
        q["total_cents"],
        "wallet",
        discount_cents=q["discount_cents"],
        pass_id=p.id,
    )
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        existing = repo.Passes.by_idempotency(user.id, idempotency_key)
        if existing:
            return existing
        raise
    log.info(
        "pass_purchased",
        extra={"pass_id": p.id, "user_id": user.id, "method": "wallet", "amount_cents": q["total_cents"]},
    )
    return p


def fulfill_card_purchase(payment):
    """Called once when a card payment for a pass succeeds (from the webhook)."""
    m = payment.meta
    user = payment.user
    route, pass_type = load_product(m["route_id"], m["pass_type"])
    start = date.fromisoformat(m["start_date"])
    if start < local_today():
        start = local_today()
    try:
        check_capacity(route, pass_type, start)
    except Conflict:
        # Paid but sold out in the meantime: give the money back to the wallet instantly.
        wallet.credit(user.id, payment.amount_cents, "refund", reference=payment.id)
        notify.notify(
            user,
            "payment",
            "refund",
            amount=format_money(payment.amount_cents, payment.currency),
            target={"en": "wallet (trip sold out)", "ar": "المحفظة (الرحلة مكتملة)"},
        )
        return None
    p = create_pass(
        user,
        route,
        pass_type,
        start,
        payment.amount_cents,
        m.get("discount_cents", 0),
        payment_id=payment.id,
        idempotency_key=f"pay:{payment.id}",
        auto_renew=m.get("auto_renew", False),
    )
    if m.get("promo_code"):
        promo = repo.Discounts.promo(m["promo_code"])
        if promo:
            promo.used_count += 1
    db.session.flush()
    wallet.create_receipt(
        user.id,
        f"{pass_type.name_en} — {route.code} {route.name_en}",
        payment.amount_cents,
        "card",
        discount_cents=m.get("discount_cents", 0),
        payment_id=payment.id,
        pass_id=p.id,
    )
    return p


def get_owned(user, pass_id):
    p = repo.get(Pass, pass_id)
    if p is None or p.user_id != user.id:
        raise NotFound("Pass not found.")
    return p


def set_auto_renew(user, pass_id, enabled):
    p = get_owned(user, pass_id)
    if p.pass_type.max_rides == 1:
        raise ValidationFailed("Single tickets can't auto-renew.")
    p.auto_renew = enabled
    db.session.commit()
    return p


def rotate_secret(user, pass_id):
    """Phone lost or stolen: old device's codes (even offline) stop working immediately."""
    p = get_owned(user, pass_id)
    p.qr_secret = new_qr_secret()
    audit.record("pass.secret_rotated", "pass", p.id)
    db.session.commit()
    return p


def rotate_wallet_secret(user):
    user.wallet_qr_secret = new_qr_secret()
    audit.record("wallet.secret_rotated", "user", user.id)
    db.session.commit()


# ---------- scheduled jobs (run daily: `flask daily-jobs`) ----------


def run_daily_jobs(today=None):
    today = today or local_today()
    reminded = remind_expiring(today)  # before renewals, so a failed renewal doesn't also send a reminder
    renewed, failed = renew_due(today)
    expired = expire_old(today)
    db.session.commit()
    return {"renewed": renewed, "renew_failed": failed, "expired": expired, "reminded": reminded}


def renew_due(today):
    renewed = failed = 0
    for p in repo.Passes.active_expiring_on(today):
        if not p.auto_renew:
            continue
        user, route, pass_type = p.user, p.route, p.pass_type
        try:
            q = pricing.quote(user, route, pass_type)
            with db.session.begin_nested():
                wallet.debit(user.id, q["total_cents"], "pass_purchase", reference=f"renew:{p.id}")
                new = create_pass(
                    user,
                    route,
                    pass_type,
                    p.valid_until + timedelta(days=1),
                    q["total_cents"],
                    q["discount_cents"],
                    source="renewal",
                    idempotency_key=f"renew:{p.id}",
                    auto_renew=True,
                )
                db.session.flush()
                wallet.create_receipt(
                    user.id,
                    f"Auto-renew {pass_type.name_en} — {route.code}",
                    q["total_cents"],
                    "wallet",
                    discount_cents=q["discount_cents"],
                    pass_id=new.id,
                )
            p.auto_renew = False  # the new pass carries the flag forward
            notify.notify(
                user,
                "renewal",
                "pass_renewed",
                product={"en": pass_type.name_en, "ar": pass_type.name_ar},
                route=route.code,
                until=new.valid_until.isoformat(),
            )
            renewed += 1
        except Exception as e:  # insufficient funds, product deactivated, …
            log.info("renew_failed", extra={"pass_id": p.id, "reason": str(e)})
            p.auto_renew = False
            notify.notify(
                user,
                "renewal",
                "renew_failed",
                product={"en": pass_type.name_en, "ar": pass_type.name_ar},
                route=route.code,
            )
            failed += 1
    return renewed, failed


def expire_old(today):
    passes = repo.Passes.active_ended_before(today)
    for p in passes:
        p.status = "expired"
    return len(passes)


def remind_expiring(today):
    count = 0
    for p in repo.Passes.active_expiring_on(today):
        if not p.auto_renew and p.pass_type.validity_days > 1:
            notify.notify(
                p.user,
                "expiring",
                "pass_expiring",
                product={"en": p.pass_type.name_en, "ar": p.pass_type.name_ar},
                route=p.route.code,
            )
            count += 1
    return count


def pass_types():
    return [t.to_dict() for t in repo.PassTypes.all()]
