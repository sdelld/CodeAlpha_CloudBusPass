"""Unit tests for the service layer (no HTTP)."""

from datetime import timedelta

import pytest

from buspass import repositories as repo
from buspass.errors import Conflict, Forbidden, PaymentError, ValidationFailed
from buspass.extensions import db
from buspass.models import Pass, Ride
from buspass.services import auth, passes, pricing, qr, sponsors, validation, wallet
from buspass.timeutil import local_today

from .conftest import bus_on, key, route, token_for, user, wallet_token

# ---------- pricing ----------


def test_base_price_uses_integer_multipliers(app):
    daily = repo.PassTypes.by_code("daily")
    assert pricing.base_price(route("R1"), daily) == 1200 * 5 // 2


def test_student_discount_then_promo(app):
    q = pricing.quote(user("student@cu.test"), route("R1"), repo.PassTypes.by_code("monthly"), "WELCOME20")
    base = 1200 * 40
    after_student = base - base * 40 // 100
    assert q["total_cents"] == after_student - after_student * 20 // 100
    assert [line["label"] for line in q["lines"]] == ["base", "student_discount", "promo"]


def test_pending_discount_is_not_applied(app):
    q = pricing.quote(user("senior@cloudbus.test"), route("R1"), repo.PassTypes.by_code("monthly"))
    assert q["discount_cents"] == 0


def test_single_tickets_are_not_discountable(app):
    q = pricing.quote(user("student@cu.test"), route("R1"), repo.PassTypes.by_code("single"))
    assert q["total_cents"] == 1200


@pytest.mark.parametrize("code,error", [("NOPE", "promo_invalid"), ("SUMMER10", "promo_expired")])
def test_bad_promo_codes(app, code, error):
    with pytest.raises(ValidationFailed) as e:
        pricing.quote(None, route("R1"), repo.PassTypes.by_code("weekly"), code)
    assert e.value.code == error


def test_fixed_promo_never_goes_negative(app):
    q = pricing.quote(None, route("R5"), repo.PassTypes.by_code("single"), "CAMPUS50")
    assert q["total_cents"] == 0


# ---------- QR ----------


def test_qr_roundtrip_and_tamper(app):
    token = qr.make_token("s" * 64, "P", "abc123", 1000)
    parsed = qr.parse(token)
    assert parsed == {"kind": "P", "id": "abc123", "window": 1000, "sig": token.rsplit(".", 1)[1]}
    assert qr.signature_ok("s" * 64, parsed)
    assert not qr.signature_ok("t" * 64, parsed)
    assert not qr.signature_ok("s" * 64, {**parsed, "window": 1001})
    assert qr.parse("BP1.old.format") is None and qr.parse("") is None


def test_qr_freshness_window(app):
    assert qr.window_fresh(100, 101) and qr.window_fresh(101, 100)
    assert not qr.window_fresh(98, 100)


# ---------- wallet ----------


def test_wallet_debit_and_ledger(app):
    u = user("rider@cloudbus.test")
    wallet.debit(u.id, 1000, "ride")
    db.session.commit()
    assert u.balance_cents == 24000
    assert repo.Wallet.history(u.id)[0].balance_after_cents == 24000
    with pytest.raises(PaymentError):
        wallet.debit(u.id, 10**7, "ride")


# ---------- auth ----------


def test_otp_wrong_attempts_lock_out(app):
    out = auth.register("New Person", "password123", email="new@example.test")
    for _ in range(5):
        with pytest.raises(ValidationFailed):
            auth.verify_signup("new@example.test", "000000" if out["dev_code"] != "000000" else "111111")
    with pytest.raises(ValidationFailed) as e:
        auth.verify_signup("new@example.test", out["dev_code"])
    assert e.value.code == "otp_locked"


def test_egyptian_phone_normalised(app):
    out = auth.register("Phone User", "password123", phone="010 1234 5678")
    assert out["target"] == "+201012345678"
    tokens = auth.verify_signup("01012345678", out["dev_code"])
    assert tokens["user"]["phone"] == "+201012345678"


def test_unverified_account_cannot_log_in(app):
    auth.register("Pending", "password123", email="pending@example.test")
    with pytest.raises(Forbidden):
        auth.login_with_password("pending@example.test", "password123")


# ---------- passes ----------


def test_buy_with_wallet_is_idempotent(app):
    u = user("rider@cloudbus.test")
    k = key()
    a = passes.buy_with_wallet(u, route("R5").id, "daily", idempotency_key=k)
    b = passes.buy_with_wallet(u, route("R5").id, "daily", idempotency_key=k)
    assert a.id == b.id
    assert u.balance_cents == 25000 - 1000 * 5 // 2


def test_single_ticket_capacity(app):
    u = user("rider@cloudbus.test")
    r = route("R5")
    r.daily_single_capacity = 1
    db.session.commit()
    passes.buy_with_wallet(u, r.id, "single", idempotency_key=key())
    with pytest.raises(Conflict):
        passes.buy_with_wallet(u, r.id, "single", idempotency_key=key())


def test_start_date_limits(app):
    with pytest.raises(ValidationFailed):
        passes.parse_start(local_today() - timedelta(days=1))
    with pytest.raises(ValidationFailed):
        passes.parse_start(local_today() + timedelta(days=31))


def test_daily_jobs_renew_and_expire(app):
    u = user("rider@cloudbus.test")
    p = passes.buy_with_wallet(u, route("R5").id, "weekly", idempotency_key=key(), auto_renew=True)
    balance = u.balance_cents
    result = passes.run_daily_jobs(today=p.valid_until)
    assert result["renewed"] >= 1
    renewed = repo.Passes.by_idempotency(u.id, f"renew:{p.id}")
    assert renewed.valid_from == p.valid_until + timedelta(days=1) and renewed.auto_renew
    assert u.balance_cents == balance - renewed.price_cents
    passes.run_daily_jobs(today=p.valid_until + timedelta(days=1))
    assert db.session.get(Pass, p.id).status == "expired"


def test_auto_renew_without_funds_notifies(app):
    u = user("rider@cloudbus.test")
    p = passes.buy_with_wallet(u, route("R5").id, "weekly", idempotency_key=key(), auto_renew=True)
    u.balance_cents = 0
    db.session.commit()
    result = passes.run_daily_jobs(today=p.valid_until)
    assert result["renew_failed"] >= 1 and not p.auto_renew
    assert repo.Notifications.of_user(u.id)[0].title == "Auto-renew failed"


# ---------- validation ----------


def _validator():
    return user("validator@cloudbus.test")


def _buy(product="daily", code="R5"):
    return passes.buy_with_wallet(user("rider@cloudbus.test"), route(code).id, product, idempotency_key=key())


def test_valid_then_duplicate_on_same_bus(app):
    p = _buy()
    bus = bus_on("R5")
    assert validation.validate(_validator(), token_for(p), bus.id)["result"] == "valid"
    assert validation.validate(_validator(), token_for(p), bus.id)["result"] == "duplicate"


def test_anti_passback_on_other_bus(app):
    p = _buy()
    buses = db.session.query(type(bus_on("R5"))).filter_by(route_id=route("R5").id).all()
    validation.validate(_validator(), token_for(p), buses[0].id)
    r = validation.validate(_validator(), token_for(p), buses[1].id)
    assert r["result"] == "fraud" and "Anti-passback" in r["reason"]


def test_screenshot_older_than_a_minute_rejected(app):
    p = _buy()
    old = token_for(p, qr.current_window() - 3)
    r = validation.validate(_validator(), old, bus_on("R5").id)
    assert r["result"] == "fraud" and "screenshot" in r["reason"]


def test_forged_code_rejected(app):
    p = _buy()
    forged = token_for(p)[:-4] + "0000"
    assert validation.validate(_validator(), forged, bus_on("R5").id)["result"] == "fraud"


def test_wrong_route_rejected(app):
    p = _buy(code="R5")
    assert validation.validate(_validator(), token_for(p), bus_on("R1").id)["result"] == "invalid"


def test_single_ride_is_consumed(app):
    p = _buy("single")
    bus = bus_on("R5")
    assert validation.validate(_validator(), token_for(p), bus.id)["valid"]
    p.last_scan_at -= timedelta(hours=1)
    db.session.commit()
    r = validation.validate(_validator(), token_for(p), bus.id)
    assert r["result"] == "expired" and "already used" in r["reason"]


def test_rotated_secret_invalidates_old_device(app):
    p = _buy()
    old_token = token_for(p)
    passes.rotate_secret(user("rider@cloudbus.test"), p.id)
    assert validation.validate(_validator(), old_token, bus_on("R5").id)["result"] == "fraud"


def test_pay_per_ride_wallet(app):
    u = user("rider@cloudbus.test")
    r = validation.validate(_validator(), wallet_token(u), bus_on("R2").id)
    assert r["result"] == "valid" and r["fare_cents"] == 3500
    assert u.balance_cents == 25000 - 3500
    u.balance_cents = 100
    db.session.commit()
    other_bus = db.session.query(type(bus_on("R5"))).filter_by(route_id=route("R5").id).first()
    ride = db.session.query(Ride).filter_by(user_id=u.id, result="valid").first()
    ride.scanned_at -= timedelta(hours=1)
    db.session.commit()
    assert validation.validate(_validator(), wallet_token(u), other_bus.id)["result"] == "insufficient_funds"


def test_offline_sync_is_idempotent(app):
    p = _buy()
    scan = {"token": token_for(p), "bus_id": bus_on("R5").id, "client_scan_id": "dev1-0001", "scanned_at": None}
    first = validation.sync_batch(_validator(), [scan])
    second = validation.sync_batch(_validator(), [scan])
    assert first[0]["result"] == second[0]["result"] == "valid"
    assert db.session.query(Ride).filter_by(client_scan_id="dev1-0001").count() == 1


# ---------- sponsors ----------


def test_sponsor_code_needs_member_email(app):
    with pytest.raises(Forbidden):
        sponsors.redeem(user("rider@cloudbus.test"), "CUFALL26")
    p = sponsors.redeem(user("student@cu.test"), "cufall26")
    assert p.price_cents == 0 and p.source == "sponsor"
    with pytest.raises(Conflict):
        sponsors.redeem(user("student@cu.test"), "CUFALL26")
