"""Server-side ticket validation. Every attempt is stored as a Ride (the scan audit trail).

Results: valid · duplicate (same pass, same bus, recently — not charged again) · expired ·
fraud (forged / replayed / anti-passback / revoked) · invalid (unreadable, wrong route) · insufficient_funds.
"""

import logging
import time
from datetime import UTC, datetime, timedelta

from flask import current_app

from .. import repositories as repo
from ..errors import NotFound, ValidationFailed
from ..extensions import db
from ..models import Bus, Pass, Ride, User, utcnow
from ..timeutil import tz
from . import qr, wallet

log = logging.getLogger(__name__)


def _scan_time(scanned_at):
    if scanned_at is None:
        return utcnow()
    if scanned_at.tzinfo:
        scanned_at = scanned_at.astimezone(UTC).replace(tzinfo=None)
    # Device clocks can't claim scans from the future.
    return min(scanned_at, utcnow())


def validate(validator, token, bus_id, scanned_at=None, client_scan_id=None, offline=False):
    if client_scan_id:
        previous = repo.Rides.by_client_id(client_scan_id)
        if previous:
            return _result(previous)  # offline sync retried: same answer, no double charge

    bus = repo.get(Bus, bus_id)
    if bus is None or bus.status != "active":
        raise NotFound("Bus not found or not in service.")
    when = _scan_time(scanned_at)
    ride = Ride(
        validator_id=validator.id,
        bus_id=bus.id,
        route_id=bus.route_id,
        scanned_at=when,
        offline=offline,
        client_scan_id=client_scan_id,
    )

    parsed = qr.parse(token)
    if parsed is None:
        return _finish(ride, "invalid", "Not a CloudBus code.")
    # For offline scans, judge freshness against the time the scan happened on the bus.
    reference_window = qr.current_window(when.replace(tzinfo=UTC).timestamp())

    if parsed["kind"] == "P":
        return _validate_pass(ride, parsed, bus, when, reference_window)
    return _validate_wallet(ride, parsed, bus, when, reference_window)


def _check_token(ride, secret, parsed, last_window, reference_window):
    if not qr.signature_ok(secret, parsed):
        return _finish(ride, "fraud", "Forged or outdated code (signature mismatch).")
    if not qr.window_fresh(parsed["window"], reference_window):
        return _finish(ride, "fraud", "Code is too old — likely a screenshot. Ask the rider to open the live pass.")
    if last_window is not None and parsed["window"] < last_window:
        return _finish(ride, "fraud", "Replayed code (older than the last accepted scan).")
    return None


def _validate_pass(ride, parsed, bus, when, reference_window):
    p = repo.get_for_update(Pass, parsed["id"])
    if p is None:
        return _finish(ride, "fraud", "Unknown pass.")
    ride.pass_id, ride.user_id = p.id, p.user_id
    failed = _check_token(ride, p.qr_secret, parsed, p.last_window, reference_window)
    if failed:
        return failed
    if p.user.status == "suspended":
        return _finish(ride, "fraud", "Rider account suspended.")
    if p.status in ("revoked", "refunded", "cancelled"):
        return _finish(ride, "fraud", f"Pass {p.status}.")
    if p.status == "used":
        return _finish(ride, "expired", "Single ride already used.")
    local_day = when.replace(tzinfo=UTC).astimezone(tz()).date()
    if local_day > p.valid_until:
        return _finish(ride, "expired", f"Pass expired on {p.valid_until.isoformat()}.")
    if local_day < p.valid_from:
        return _finish(ride, "invalid", f"Pass starts on {p.valid_from.isoformat()}.")
    if bus.route_id != p.route_id:
        return _finish(ride, "invalid", f"Pass is for route {p.route.code}, this bus runs route {bus.route.code}.")

    recent = p.last_scan_at and when - p.last_scan_at < timedelta(minutes=current_app.config["ANTI_PASSBACK_MINUTES"])
    if recent and p.last_scan_bus_id == bus.id:
        return _finish(ride, "duplicate", "Already validated on this bus.", p=p)
    if recent:
        return _finish(ride, "fraud", "Anti-passback: this pass was just used on another bus.")

    p.last_scan_at, p.last_scan_bus_id, p.last_window = when, bus.id, parsed["window"]
    p.rides_used += 1
    if p.pass_type.max_rides and p.rides_used >= p.pass_type.max_rides:
        p.status = "used"
    return _finish(ride, "valid", None, p=p)


def _validate_wallet(ride, parsed, bus, when, reference_window):
    user = repo.get_for_update(User, int(parsed["id"]))
    if user is None:
        return _finish(ride, "fraud", "Unknown wallet.")
    ride.user_id = user.id
    # Wallet codes reuse Pass-level replay protection through the last ride of this user.
    last = (
        db.session.query(Ride)
        .filter(Ride.user_id == user.id, Ride.pass_id.is_(None), Ride.result == "valid")
        .order_by(Ride.scanned_at.desc())
        .first()
    )
    last_window = qr.current_window(last.scanned_at.replace(tzinfo=UTC).timestamp()) if last else None
    failed = _check_token(ride, user.wallet_qr_secret, parsed, last_window, reference_window)
    if failed:
        return failed
    if user.status == "suspended":
        return _finish(ride, "fraud", "Rider account suspended.")
    if (
        last
        and last.bus_id == bus.id
        and when - last.scanned_at < timedelta(minutes=current_app.config["ANTI_PASSBACK_MINUTES"])
    ):
        return _finish(ride, "duplicate", "Already paid on this bus.", user=user)
    fare = bus.route.base_fare_cents
    if user.balance_cents < fare:
        return _finish(ride, "insufficient_funds", "Not enough wallet balance.", user=user)
    wallet.debit(user.id, fare, "ride", reference=f"{bus.route.code}/{bus.plate}")
    ride.fare_cents = fare
    return _finish(ride, "valid", None, user=user)


def _finish(ride, result, reason, p=None, user=None):
    ride.result, ride.reason = result, reason
    repo.add(ride)
    db.session.commit()
    log.info(
        "scan",
        extra={
            "result": result,
            "reason": reason,
            "validator_id": ride.validator_id,
            "bus_id": ride.bus_id,
            "pass_id": ride.pass_id,
            "offline": ride.offline,
        },
    )
    return _result(ride, p, user)


def _result(ride, p=None, user=None):
    p = p or (repo.get(Pass, ride.pass_id) if ride.pass_id else None)
    user = user or (repo.get(User, ride.user_id) if ride.user_id else None)
    out = {
        "scan_id": ride.id,
        "result": ride.result,
        "valid": ride.result in ("valid", "duplicate"),
        "reason": ride.reason,
        "scanned_at": ride.scanned_at.isoformat(),
        "fare_cents": ride.fare_cents,
    }
    if user:
        out["passenger"] = user.name
        out["discount_type"] = user.discount_type if user.discount_status == "approved" else "none"
    if p:
        out["pass"] = {
            "type_en": p.pass_type.name_en,
            "type_ar": p.pass_type.name_ar,
            "route": p.route.code,
            "valid_until": p.valid_until.isoformat(),
            "rides_used": p.rides_used,
        }
    elif user and ride.result in ("valid", "duplicate", "insufficient_funds"):
        out["wallet"] = {"balance_cents": user.balance_cents}
    return out


def sync_batch(validator, scans):
    if len(scans) > 200:
        raise ValidationFailed("Send at most 200 scans per batch.")
    results = []
    for s in scans:
        try:
            r = validate(validator, s["token"], s["bus_id"], s.get("scanned_at"), s["client_scan_id"], offline=True)
        except NotFound as e:
            db.session.rollback()
            r = {"result": "invalid", "valid": False, "reason": e.message}
        results.append({"client_scan_id": s["client_scan_id"], **r})
    return results


def recent_for(validator):
    return [r.to_dict() for r in repo.Rides.by_validator(validator.id)]


def now_window():
    return qr.current_window(time.time())


__all__ = ["validate", "sync_batch", "recent_for", "datetime"]
