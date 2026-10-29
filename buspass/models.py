"""Database schema. Money is always integer piastres/cents (`*_cents`); times are naive UTC."""

import secrets
import uuid
from datetime import UTC, datetime

from .extensions import db


def utcnow():
    return datetime.now(UTC).replace(tzinfo=None)


def new_id():
    return uuid.uuid4().hex


def new_qr_secret():
    return secrets.token_hex(32)


ROLES = ("rider", "validator", "admin", "sponsor")


class TimestampMixin:
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)


# ---------- identity ----------


class Organization(TimestampMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(160), nullable=False)
    kind = db.Column(db.String(20), nullable=False, default="university")  # university | company
    email_domain = db.Column(db.String(120))  # members must use this domain when set


class User(TimestampMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(255), unique=True, index=True)
    phone = db.Column(db.String(20), unique=True, index=True)
    password_hash = db.Column(db.String(255))
    role = db.Column(db.String(16), nullable=False, default="rider", index=True)
    status = db.Column(db.String(16), nullable=False, default="active")  # pending | active | suspended
    language = db.Column(db.String(2), nullable=False, default="en")
    discount_type = db.Column(db.String(10), nullable=False, default="none")  # none | student | senior
    discount_status = db.Column(db.String(10), nullable=False, default="none")  # none|pending|approved|rejected
    organization_id = db.Column(db.Integer, db.ForeignKey("organization.id"))
    balance_cents = db.Column(db.Integer, nullable=False, default=0)
    # Key for the rider's pay-per-ride wallet QR (rotating codes are derived from it).
    wallet_qr_secret = db.Column(db.String(64), nullable=False, default=new_qr_secret)
    last_login_at = db.Column(db.DateTime)

    organization = db.relationship("Organization")

    def to_dict(self, private=True):
        d = {"id": self.id, "name": self.name, "role": self.role, "status": self.status}
        if private:
            d.update(
                email=self.email,
                phone=self.phone,
                language=self.language,
                discount_type=self.discount_type,
                discount_status=self.discount_status,
                balance_cents=self.balance_cents,
                organization_id=self.organization_id,
                created_at=self.created_at.isoformat(),
            )
        return d


class OtpCode(TimestampMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    target = db.Column(db.String(255), nullable=False, index=True)  # email or phone
    purpose = db.Column(db.String(20), nullable=False)  # verify | login
    code_hash = db.Column(db.String(128), nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)
    attempts = db.Column(db.Integer, nullable=False, default=0)
    consumed_at = db.Column(db.DateTime)


class RefreshToken(TimestampMixin, db.Model):
    id = db.Column(db.String(32), primary_key=True, default=new_id)  # the JWT "jti"
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    expires_at = db.Column(db.DateTime, nullable=False)
    revoked_at = db.Column(db.DateTime)
    replaced_by = db.Column(db.String(32))


# ---------- network ----------


class Stop(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name_en = db.Column(db.String(120), nullable=False)
    name_ar = db.Column(db.String(120), nullable=False)
    lat = db.Column(db.Float, nullable=False)
    lng = db.Column(db.Float, nullable=False)

    def to_dict(self):
        return {"id": self.id, "name_en": self.name_en, "name_ar": self.name_ar, "lat": self.lat, "lng": self.lng}


class Route(TimestampMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(16), unique=True, nullable=False)
    name_en = db.Column(db.String(160), nullable=False)
    name_ar = db.Column(db.String(160), nullable=False)
    color = db.Column(db.String(7), nullable=False, default="#2563eb")
    base_fare_cents = db.Column(db.Integer, nullable=False)
    daily_single_capacity = db.Column(db.Integer, nullable=False, default=200)
    active = db.Column(db.Boolean, nullable=False, default=True)

    stops = db.relationship("RouteStop", order_by="RouteStop.seq", cascade="all, delete-orphan", back_populates="route")
    departures = db.relationship("Departure", order_by="Departure.time", cascade="all, delete-orphan")

    def to_dict(self, detail=False):
        d = {
            "id": self.id,
            "code": self.code,
            "name_en": self.name_en,
            "name_ar": self.name_ar,
            "color": self.color,
            "base_fare_cents": self.base_fare_cents,
            "active": self.active,
            "daily_single_capacity": self.daily_single_capacity,
        }
        if detail:
            d["stops"] = [
                dict(rs.stop.to_dict(), seq=rs.seq, minutes_from_start=rs.minutes_from_start) for rs in self.stops
            ]
            d["departures"] = [dep.time for dep in self.departures]
        return d


class RouteStop(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    route_id = db.Column(db.Integer, db.ForeignKey("route.id"), nullable=False, index=True)
    stop_id = db.Column(db.Integer, db.ForeignKey("stop.id"), nullable=False)
    seq = db.Column(db.Integer, nullable=False)
    minutes_from_start = db.Column(db.Integer, nullable=False)

    route = db.relationship("Route", back_populates="stops")
    stop = db.relationship("Stop")


class Departure(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    route_id = db.Column(db.Integer, db.ForeignKey("route.id"), nullable=False, index=True)
    time = db.Column(db.String(5), nullable=False)  # "HH:MM" local time, daily


class Bus(TimestampMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    plate = db.Column(db.String(20), unique=True, nullable=False)
    route_id = db.Column(db.Integer, db.ForeignKey("route.id"), index=True)
    capacity = db.Column(db.Integer, nullable=False, default=50)
    status = db.Column(db.String(16), nullable=False, default="active")  # active | maintenance

    route = db.relationship("Route")

    def to_dict(self):
        return {
            "id": self.id,
            "plate": self.plate,
            "route_id": self.route_id,
            "capacity": self.capacity,
            "status": self.status,
        }


class FavoriteRoute(db.Model):
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), primary_key=True)
    route_id = db.Column(db.Integer, db.ForeignKey("route.id"), primary_key=True)


class ServiceAlert(TimestampMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    route_id = db.Column(db.Integer, db.ForeignKey("route.id"), nullable=False, index=True)
    severity = db.Column(db.String(10), nullable=False, default="delay")  # info | delay | cancelled
    message_en = db.Column(db.String(300), nullable=False)
    message_ar = db.Column(db.String(300), nullable=False)
    created_by = db.Column(db.Integer, db.ForeignKey("user.id"))

    def to_dict(self):
        return {
            "id": self.id,
            "route_id": self.route_id,
            "severity": self.severity,
            "message_en": self.message_en,
            "message_ar": self.message_ar,
            "created_at": self.created_at.isoformat(),
        }


# ---------- products ----------


class PassType(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(16), unique=True, nullable=False)  # single | daily | weekly | monthly | semester
    name_en = db.Column(db.String(60), nullable=False)
    name_ar = db.Column(db.String(60), nullable=False)
    multiplier_num = db.Column(db.Integer, nullable=False)
    multiplier_den = db.Column(db.Integer, nullable=False, default=1)
    validity_days = db.Column(db.Integer, nullable=False)
    max_rides = db.Column(db.Integer)  # None = unlimited; 1 = single ride (capacity-limited)
    discountable = db.Column(db.Boolean, nullable=False, default=True)
    active = db.Column(db.Boolean, nullable=False, default=True)
    sort = db.Column(db.Integer, nullable=False, default=0)

    def to_dict(self):
        return {
            "id": self.id,
            "code": self.code,
            "name_en": self.name_en,
            "name_ar": self.name_ar,
            "multiplier": [self.multiplier_num, self.multiplier_den],
            "validity_days": self.validity_days,
            "max_rides": self.max_rides,
            "discountable": self.discountable,
            "active": self.active,
        }


class DiscountRule(db.Model):
    code = db.Column(db.String(10), primary_key=True)  # student | senior
    percent = db.Column(db.Integer, nullable=False)
    active = db.Column(db.Boolean, nullable=False, default=True)

    def to_dict(self):
        return {"code": self.code, "percent": self.percent, "active": self.active}


class PromoCode(TimestampMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(32), unique=True, nullable=False)
    kind = db.Column(db.String(8), nullable=False)  # percent | fixed
    value = db.Column(db.Integer, nullable=False)  # percent (1-100) or cents
    max_uses = db.Column(db.Integer)
    used_count = db.Column(db.Integer, nullable=False, default=0)
    expires_at = db.Column(db.DateTime)
    active = db.Column(db.Boolean, nullable=False, default=True)

    def to_dict(self):
        return {
            "id": self.id,
            "code": self.code,
            "kind": self.kind,
            "value": self.value,
            "max_uses": self.max_uses,
            "used_count": self.used_count,
            "active": self.active,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
        }


class Pass(TimestampMixin, db.Model):
    id = db.Column(db.String(32), primary_key=True, default=new_id)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    route_id = db.Column(db.Integer, db.ForeignKey("route.id"), nullable=False, index=True)
    pass_type_id = db.Column(db.Integer, db.ForeignKey("pass_type.id"), nullable=False)
    # active | used | expired | cancelled | refunded | revoked
    status = db.Column(db.String(12), nullable=False, default="active", index=True)
    valid_from = db.Column(db.Date, nullable=False)
    valid_until = db.Column(db.Date, nullable=False, index=True)
    price_cents = db.Column(db.Integer, nullable=False)
    discount_cents = db.Column(db.Integer, nullable=False, default=0)
    rides_used = db.Column(db.Integer, nullable=False, default=0)
    auto_renew = db.Column(db.Boolean, nullable=False, default=False)
    source = db.Column(db.String(12), nullable=False, default="purchase")  # purchase | renewal | sponsor
    qr_secret = db.Column(db.String(64), nullable=False, default=new_qr_secret)
    payment_id = db.Column(db.String(32), db.ForeignKey("payment.id"))
    sponsor_block_id = db.Column(db.Integer, db.ForeignKey("sponsor_block.id"))
    idempotency_key = db.Column(db.String(64))
    last_scan_at = db.Column(db.DateTime)
    last_scan_bus_id = db.Column(db.Integer)
    last_window = db.Column(db.BigInteger)

    user = db.relationship("User")
    route = db.relationship("Route")
    pass_type = db.relationship("PassType")

    __table_args__ = (db.UniqueConstraint("user_id", "idempotency_key", name="uq_pass_user_idem"),)


# ---------- money ----------


class Payment(TimestampMixin, db.Model):
    id = db.Column(db.String(32), primary_key=True, default=new_id)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    purpose = db.Column(db.String(16), nullable=False)  # topup | pass | sponsor_seats
    amount_cents = db.Column(db.Integer, nullable=False)
    currency = db.Column(db.String(3), nullable=False)
    provider = db.Column(db.String(12), nullable=False)
    provider_ref = db.Column(db.String(255), index=True)
    status = db.Column(
        db.String(12), nullable=False, default="pending", index=True
    )  # pending|succeeded|failed|refunded
    idempotency_key = db.Column(db.String(64), nullable=False)
    meta = db.Column(db.JSON, nullable=False, default=dict)
    completed_at = db.Column(db.DateTime)
    refunded_cents = db.Column(db.Integer, nullable=False, default=0)

    user = db.relationship("User")

    __table_args__ = (db.UniqueConstraint("user_id", "idempotency_key", name="uq_payment_user_idem"),)

    def to_dict(self):
        return {
            "id": self.id,
            "purpose": self.purpose,
            "amount_cents": self.amount_cents,
            "currency": self.currency,
            "provider": self.provider,
            "status": self.status,
            "created_at": self.created_at.isoformat(),
            "refunded_cents": self.refunded_cents,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }


class PaymentEvent(TimestampMixin, db.Model):
    """Every webhook event processed once: (provider, event_id) is unique."""

    id = db.Column(db.Integer, primary_key=True)
    provider = db.Column(db.String(12), nullable=False)
    event_id = db.Column(db.String(255), nullable=False)
    type = db.Column(db.String(60), nullable=False)
    payment_id = db.Column(db.String(32))

    __table_args__ = (db.UniqueConstraint("provider", "event_id", name="uq_payment_event"),)


class WalletTransaction(TimestampMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    amount_cents = db.Column(db.Integer, nullable=False)  # + credit, - debit
    kind = db.Column(db.String(16), nullable=False)  # topup | pass_purchase | ride | refund | adjustment
    reference = db.Column(db.String(64))
    balance_after_cents = db.Column(db.Integer, nullable=False)

    def to_dict(self):
        return {
            "id": self.id,
            "amount_cents": self.amount_cents,
            "kind": self.kind,
            "reference": self.reference,
            "balance_after_cents": self.balance_after_cents,
            "created_at": self.created_at.isoformat(),
        }


class Receipt(TimestampMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    number = db.Column(db.String(24), unique=True, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    description = db.Column(db.String(200), nullable=False)
    amount_cents = db.Column(db.Integer, nullable=False)
    discount_cents = db.Column(db.Integer, nullable=False, default=0)
    method = db.Column(db.String(10), nullable=False)  # card | wallet | sponsor
    payment_id = db.Column(db.String(32))
    pass_id = db.Column(db.String(32))
    revenue = db.Column(db.Boolean, nullable=False, default=True)  # top-ups are not revenue until spent

    def to_dict(self):
        return {
            "id": self.id,
            "number": self.number,
            "description": self.description,
            "amount_cents": self.amount_cents,
            "discount_cents": self.discount_cents,
            "method": self.method,
            "pass_id": self.pass_id,
            "created_at": self.created_at.isoformat(),
        }


# ---------- operations ----------


class Ride(TimestampMixin, db.Model):
    """One validation attempt (successful or not) — the audit trail of every scan."""

    id = db.Column(db.Integer, primary_key=True)
    client_scan_id = db.Column(db.String(64), unique=True)  # makes offline sync idempotent
    pass_id = db.Column(db.String(32), db.ForeignKey("pass.id"), index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), index=True)
    validator_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    bus_id = db.Column(db.Integer, db.ForeignKey("bus.id"))
    route_id = db.Column(db.Integer, db.ForeignKey("route.id"), index=True)
    result = db.Column(
        db.String(20), nullable=False, index=True
    )  # valid|duplicate|expired|fraud|invalid|insufficient_funds
    reason = db.Column(db.String(200))
    fare_cents = db.Column(db.Integer, nullable=False, default=0)
    scanned_at = db.Column(db.DateTime, nullable=False, default=utcnow, index=True)
    offline = db.Column(db.Boolean, nullable=False, default=False)

    route = db.relationship("Route")
    bus = db.relationship("Bus")

    def to_dict(self):
        return {
            "id": self.id,
            "pass_id": self.pass_id,
            "route_id": self.route_id,
            "bus_id": self.bus_id,
            "result": self.result,
            "reason": self.reason,
            "fare_cents": self.fare_cents,
            "scanned_at": self.scanned_at.isoformat(),
            "offline": self.offline,
        }


class Notification(TimestampMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    kind = db.Column(db.String(20), nullable=False)  # payment | expiring | delay | renewal | account | support
    title = db.Column(db.String(160), nullable=False)
    body = db.Column(db.String(500), nullable=False)
    read_at = db.Column(db.DateTime)

    def to_dict(self):
        return {
            "id": self.id,
            "kind": self.kind,
            "title": self.title,
            "body": self.body,
            "read": self.read_at is not None,
            "created_at": self.created_at.isoformat(),
        }


class VerificationDocument(TimestampMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    kind = db.Column(db.String(10), nullable=False)  # student | senior
    stored_name = db.Column(db.String(80), nullable=False)
    original_name = db.Column(db.String(200), nullable=False)
    content_type = db.Column(db.String(60), nullable=False)
    status = db.Column(db.String(10), nullable=False, default="pending")
    reviewed_by = db.Column(db.Integer, db.ForeignKey("user.id"))
    reviewed_at = db.Column(db.DateTime)
    note = db.Column(db.String(300))

    user = db.relationship("User", foreign_keys=[user_id])

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "user_name": self.user.name if self.user else None,
            "kind": self.kind,
            "original_name": self.original_name,
            "status": self.status,
            "note": self.note,
            "created_at": self.created_at.isoformat(),
        }


class SupportTicket(TimestampMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    category = db.Column(db.String(20), nullable=False)  # payment | pass | app | bus | other
    message = db.Column(db.String(2000), nullable=False)
    status = db.Column(db.String(10), nullable=False, default="open")

    user = db.relationship("User")

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "user_name": self.user.name if self.user else None,
            "category": self.category,
            "message": self.message,
            "status": self.status,
            "created_at": self.created_at.isoformat(),
        }


class AuditLog(TimestampMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    actor_id = db.Column(db.Integer, db.ForeignKey("user.id"), index=True)
    action = db.Column(db.String(60), nullable=False, index=True)
    entity = db.Column(db.String(40))
    entity_id = db.Column(db.String(64))
    details = db.Column(db.JSON)
    ip = db.Column(db.String(64))

    actor = db.relationship("User")

    def to_dict(self):
        return {
            "id": self.id,
            "actor": self.actor.name if self.actor else "system",
            "action": self.action,
            "entity": self.entity,
            "entity_id": self.entity_id,
            "details": self.details,
            "ip": self.ip,
            "created_at": self.created_at.isoformat(),
        }


class SponsorBlock(TimestampMixin, db.Model):
    """Seats bought by a university/company; members redeem `invite_code` for a free pass."""

    id = db.Column(db.Integer, primary_key=True)
    organization_id = db.Column(db.Integer, db.ForeignKey("organization.id"), nullable=False, index=True)
    route_id = db.Column(db.Integer, db.ForeignKey("route.id"), nullable=False)
    pass_type_id = db.Column(db.Integer, db.ForeignKey("pass_type.id"), nullable=False)
    seats_total = db.Column(db.Integer, nullable=False)
    seats_used = db.Column(db.Integer, nullable=False, default=0)
    invite_code = db.Column(db.String(16), unique=True, nullable=False)
    status = db.Column(db.String(10), nullable=False, default="pending")  # pending | active | cancelled
    payment_id = db.Column(db.String(32))

    organization = db.relationship("Organization")
    route = db.relationship("Route")
    pass_type = db.relationship("PassType")

    def to_dict(self):
        return {
            "id": self.id,
            "organization": self.organization.name,
            "route_id": self.route_id,
            "route_code": self.route.code,
            "pass_type": self.pass_type.code,
            "seats_total": self.seats_total,
            "seats_used": self.seats_used,
            "invite_code": self.invite_code,
            "status": self.status,
            "created_at": self.created_at.isoformat(),
        }


class PartnerOffer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    partner = db.Column(db.String(80), nullable=False)
    title_en = db.Column(db.String(120), nullable=False)
    title_ar = db.Column(db.String(120), nullable=False)
    body_en = db.Column(db.String(240), nullable=False)
    body_ar = db.Column(db.String(240), nullable=False)
    active = db.Column(db.Boolean, nullable=False, default=True)

    def to_dict(self):
        return {
            "id": self.id,
            "partner": self.partner,
            "title_en": self.title_en,
            "title_ar": self.title_ar,
            "body_en": self.body_en,
            "body_ar": self.body_ar,
        }
