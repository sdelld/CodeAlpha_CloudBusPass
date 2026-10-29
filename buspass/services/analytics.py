"""Admin analytics and CSV exports."""

import csv
import io
from datetime import UTC, datetime, time, timedelta

from sqlalchemy import func

from .. import repositories as repo
from ..extensions import db
from ..models import Pass, Payment, Receipt, Ride, Route, User
from ..timeutil import local_today, to_local, tz


def _utc_start(day):
    return datetime.combine(day, time.min, tzinfo=tz()).astimezone(UTC).replace(tzinfo=None)


def overview(days=30):
    today = local_today()
    start_day = today - timedelta(days=days - 1)
    since = _utc_start(start_day)

    receipts = (
        db.session.query(Receipt.created_at, Receipt.amount_cents)
        .filter(Receipt.revenue.is_(True), Receipt.created_at >= since)
        .all()
    )
    ride_fares = (
        db.session.query(Ride.scanned_at, Ride.fare_cents)
        .filter(Ride.result == "valid", Ride.fare_cents > 0, Ride.scanned_at >= since)
        .all()
    )
    revenue = {(start_day + timedelta(days=i)).isoformat(): 0 for i in range(days)}
    for created, amount in list(receipts) + list(ride_fares):
        key = to_local(created).date().isoformat()
        if key in revenue:
            revenue[key] += amount

    rides = (
        db.session.query(Ride.scanned_at, Ride.route_id).filter(Ride.result == "valid", Ride.scanned_at >= since).all()
    )
    hours = [0] * 24
    for scanned, _ in rides:
        hours[to_local(scanned).hour] += 1
    codes = {r.id: r.code for r in db.session.query(Route).all()}
    per_route = {}
    for _, route_id in rides:
        per_route[codes.get(route_id, "?")] = per_route.get(codes.get(route_id, "?"), 0) + 1

    total_scans = db.session.query(func.count(Ride.id)).filter(Ride.scanned_at >= since).scalar() or 0
    fraud = db.session.query(func.count(Ride.id)).filter(Ride.scanned_at >= since, Ride.result == "fraud").scalar() or 0
    mau = (
        db.session.query(func.count(func.distinct(Ride.user_id)))
        .filter(Ride.result == "valid", Ride.scanned_at >= _utc_start(today - timedelta(days=29)))
        .scalar()
        or 0
    )
    signups = db.session.query(User.id).filter(User.role == "rider", User.created_at >= since).all()
    signup_ids = [u.id for u in signups]
    converted = (
        db.session.query(func.count(func.distinct(Receipt.user_id))).filter(Receipt.user_id.in_(signup_ids)).scalar()
        if signup_ids
        else 0
    )
    ended = (
        db.session.query(Pass)
        .join(Pass.pass_type)
        .filter(Pass.valid_until >= start_day, Pass.valid_until < today, Pass.source != "sponsor")
        .all()
    )
    ended_multi = [p for p in ended if p.pass_type.validity_days >= 7]
    renewed = sum(
        1
        for p in ended_multi
        if db.session.query(Pass.id)
        .filter(Pass.user_id == p.user_id, Pass.route_id == p.route_id, Pass.created_at > p.created_at)
        .first()
    )
    revenue_total = sum(revenue.values())

    return {
        "period_days": days,
        "kpis": {
            "revenue_cents": revenue_total,
            "active_passes": repo.Passes.count_active(today),
            "rides": len(rides),
            "rides_per_day": round(len(rides) / days, 1),
            "mau": mau,
            "arpu_cents": round(revenue_total / mau) if mau else 0,
            "conversion_rate": round(converted / len(signup_ids), 3) if signup_ids else None,
            "churn_rate": round(1 - renewed / len(ended_multi), 3) if ended_multi else None,
            "fraud_rate": round(fraud / total_scans, 4) if total_scans else 0,
            "wallet_float_cents": db.session.query(func.coalesce(func.sum(User.balance_cents), 0)).scalar(),
        },
        "revenue_by_day": [{"date": d, "amount_cents": v} for d, v in revenue.items()],
        "rides_by_route": sorted([{"route": k, "rides": v} for k, v in per_route.items()], key=lambda x: -x["rides"]),
        "rides_by_hour": [{"hour": h, "rides": c} for h, c in enumerate(hours)],
        "scan_results": dict(
            db.session.query(Ride.result, func.count(Ride.id))
            .filter(Ride.scanned_at >= since)
            .group_by(Ride.result)
            .all()
        ),
    }


EXPORTS = {
    "payments": (
        Payment,
        [
            "id",
            "user_id",
            "purpose",
            "amount_cents",
            "currency",
            "provider",
            "status",
            "refunded_cents",
            "created_at",
            "completed_at",
        ],
    ),
    "rides": (
        Ride,
        [
            "id",
            "scanned_at",
            "result",
            "reason",
            "pass_id",
            "user_id",
            "validator_id",
            "bus_id",
            "route_id",
            "fare_cents",
            "offline",
        ],
    ),
    "users": (
        User,
        [
            "id",
            "name",
            "email",
            "phone",
            "role",
            "status",
            "discount_type",
            "discount_status",
            "balance_cents",
            "created_at",
        ],
    ),
    "receipts": (
        Receipt,
        ["number", "user_id", "description", "amount_cents", "discount_cents", "method", "revenue", "created_at"],
    ),
}


def export_csv(kind):
    model, columns = EXPORTS[kind]
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(columns)
    for row in db.session.query(model).order_by(getattr(model, columns[0])).yield_per(500):
        writer.writerow([_cell(getattr(row, c)) for c in columns])
    return buf.getvalue()


def _cell(value):
    if isinstance(value, datetime):
        return value.isoformat()
    text = "" if value is None else str(value)
    # Prevent CSV formula injection when the file is opened in Excel.
    return "'" + text if text[:1] in ("=", "+", "-", "@") and not text.lstrip("-").isdigit() else text
