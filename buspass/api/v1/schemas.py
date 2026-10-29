"""Request validation schemas (marshmallow). Unknown fields are rejected everywhere."""

import re

from marshmallow import RAISE, Schema, ValidationError, fields, validate, validates_schema

PHONE = re.compile(r"^\+?\d{8,15}$")
HHMM = validate.Regexp(r"^([01]\d|2[0-3]):[0-5]\d$", error="Use HH:MM (24h).")
IDEM = validate.Regexp(r"^[A-Za-z0-9_-]{8,64}$", error="8-64 letters, digits, - or _.")
LANG = validate.OneOf(["en", "ar"])


class Base(Schema):
    class Meta:
        unknown = RAISE


# ---- auth ----
class Register(Base):
    name = fields.String(required=True, validate=validate.Length(min=2, max=120))
    email = fields.Email(load_default=None, validate=validate.Length(max=255))
    phone = fields.String(load_default=None)
    password = fields.String(required=True, load_only=True, validate=validate.Length(min=8, max=128))
    language = fields.String(load_default="en", validate=LANG)

    @validates_schema
    def one_contact(self, data, **_):
        if not data.get("email") and not data.get("phone"):
            raise ValidationError("Enter an email address or a phone number.", "email")
        if data.get("phone") and not PHONE.match(re.sub(r"[\s-]", "", data["phone"])):
            raise ValidationError("Enter a valid phone number, e.g. 01012345678.", "phone")


class Target(Base):
    target = fields.String(required=True, validate=validate.Length(min=5, max=255))


class TargetCode(Target):
    code = fields.String(required=True, validate=validate.Regexp(r"^\d{6}$", error="Enter the 6-digit code."))


class Login(Base):
    identifier = fields.String(required=True, validate=validate.Length(min=5, max=255))
    password = fields.String(required=True, load_only=True, validate=validate.Length(min=1, max=128))


class RefreshBody(Base):
    refresh_token = fields.String(load_default=None)


# ---- me ----
class ProfileUpdate(Base):
    name = fields.String(validate=validate.Length(min=2, max=120))
    language = fields.String(validate=LANG)


class PasswordChange(Base):
    current_password = fields.String(load_default="")
    new_password = fields.String(required=True, validate=validate.Length(min=8, max=128))


class NotificationIds(Base):
    ids = fields.List(fields.Integer(), load_default=None)


class VerificationForm(Schema):
    kind = fields.String(required=True, validate=validate.OneOf(["student", "senior"]))


class SupportForm(Base):
    category = fields.String(required=True, validate=validate.OneOf(["payment", "pass", "app", "bus", "other"]))
    message = fields.String(required=True, validate=validate.Length(min=10, max=2000))


# ---- passes & payments ----
class QuoteArgs(Schema):
    route_id = fields.Integer(required=True)
    pass_type = fields.String(required=True, validate=validate.Length(max=16))
    promo_code = fields.String(load_default=None, validate=validate.Length(max=32))


class BuyPass(Base):
    route_id = fields.Integer(required=True)
    pass_type = fields.String(required=True, validate=validate.Length(max=16))
    start_date = fields.Date(load_default=None)
    promo_code = fields.String(load_default=None, validate=validate.Length(max=32))
    auto_renew = fields.Boolean(load_default=False)
    idempotency_key = fields.String(required=True, validate=IDEM)


class PassUpdate(Base):
    auto_renew = fields.Boolean(required=True)


class Redeem(Base):
    code = fields.String(required=True, validate=validate.Length(min=4, max=16))
    start_date = fields.Date(load_default=None)


class Checkout(Base):
    purpose = fields.String(required=True, validate=validate.OneOf(["topup", "pass", "sponsor_seats"]))
    idempotency_key = fields.String(required=True, validate=IDEM)
    amount_cents = fields.Integer(load_default=None)
    route_id = fields.Integer(load_default=None)
    pass_type = fields.String(load_default=None, validate=validate.Length(max=16))
    start_date = fields.Date(load_default=None)
    promo_code = fields.String(load_default=None, validate=validate.Length(max=32))
    auto_renew = fields.Boolean(load_default=False)
    seats = fields.Integer(load_default=None)

    @validates_schema
    def needs_product(self, data, **_):
        if data["purpose"] in ("pass", "sponsor_seats") and not (data.get("route_id") and data.get("pass_type")):
            raise ValidationError("route_id and pass_type are required.", "route_id")
        if data["purpose"] == "topup" and data.get("amount_cents") is None:
            raise ValidationError("amount_cents is required.", "amount_cents")


# ---- validator ----
class Scan(Base):
    token = fields.String(required=True, validate=validate.Length(max=200))
    bus_id = fields.Integer(required=True)
    client_scan_id = fields.String(load_default=None, validate=IDEM)
    scanned_at = fields.AwareDateTime(load_default=None)


class SyncScan(Scan):
    client_scan_id = fields.String(required=True, validate=IDEM)
    scanned_at = fields.AwareDateTime(required=True)


class SyncBatch(Base):
    scans = fields.List(fields.Nested(SyncScan), required=True, validate=validate.Length(min=1, max=200))


# ---- admin ----
class RouteStopIn(Base):
    stop_id = fields.Integer(required=True)
    minutes_from_start = fields.Integer(required=True, validate=validate.Range(min=0, max=600))


class RouteIn(Base):
    code = fields.String(required=True, validate=validate.Regexp(r"^[A-Z0-9-]{1,16}$"))
    name_en = fields.String(required=True, validate=validate.Length(min=2, max=160))
    name_ar = fields.String(required=True, validate=validate.Length(min=2, max=160))
    color = fields.String(load_default="#2563eb", validate=validate.Regexp(r"^#[0-9a-fA-F]{6}$"))
    base_fare_cents = fields.Integer(required=True, validate=validate.Range(min=100, max=100_000))
    daily_single_capacity = fields.Integer(load_default=200, validate=validate.Range(min=1, max=100_000))
    active = fields.Boolean(load_default=True)
    stops = fields.List(fields.Nested(RouteStopIn), validate=validate.Length(min=2, max=60))
    departures = fields.List(fields.String(validate=HHMM), validate=validate.Length(max=200))


class StopIn(Base):
    name_en = fields.String(required=True, validate=validate.Length(min=2, max=120))
    name_ar = fields.String(required=True, validate=validate.Length(min=2, max=120))
    lat = fields.Float(required=True, validate=validate.Range(min=-90, max=90))
    lng = fields.Float(required=True, validate=validate.Range(min=-180, max=180))


class BusIn(Base):
    plate = fields.String(required=True, validate=validate.Length(min=3, max=20))
    route_id = fields.Integer(load_default=None)
    capacity = fields.Integer(load_default=50, validate=validate.Range(min=1, max=200))
    status = fields.String(load_default="active", validate=validate.OneOf(["active", "maintenance"]))


class PassTypeIn(Base):
    code = fields.String(required=True, validate=validate.Regexp(r"^[a-z_]{2,16}$"))
    name_en = fields.String(required=True, validate=validate.Length(min=2, max=60))
    name_ar = fields.String(required=True, validate=validate.Length(min=2, max=60))
    multiplier_num = fields.Integer(required=True, validate=validate.Range(min=1, max=1000))
    multiplier_den = fields.Integer(load_default=1, validate=validate.Range(min=1, max=100))
    validity_days = fields.Integer(required=True, validate=validate.Range(min=1, max=366))
    max_rides = fields.Integer(load_default=None, allow_none=True, validate=validate.Range(min=1, max=1000))
    discountable = fields.Boolean(load_default=True)
    active = fields.Boolean(load_default=True)
    sort = fields.Integer(load_default=0)


class PromoIn(Base):
    code = fields.String(required=True, validate=validate.Regexp(r"^[A-Za-z0-9]{3,32}$"))
    kind = fields.String(required=True, validate=validate.OneOf(["percent", "fixed"]))
    value = fields.Integer(required=True, validate=validate.Range(min=1, max=1_000_000))
    max_uses = fields.Integer(load_default=None, allow_none=True, validate=validate.Range(min=1))
    expires_at = fields.DateTime(load_default=None, allow_none=True)
    active = fields.Boolean(load_default=True)

    @validates_schema
    def percent_range(self, data, **_):
        if data.get("kind") == "percent" and data.get("value", 0) > 100:
            raise ValidationError("Percent must be 1-100.", "value")


class DiscountIn(Base):
    code = fields.String(required=True, validate=validate.OneOf(["student", "senior"]))
    percent = fields.Integer(required=True, validate=validate.Range(min=0, max=100))
    active = fields.Boolean(load_default=True)


class UserUpdate(Base):
    status = fields.String(validate=validate.OneOf(["active", "suspended"]))
    role = fields.String(validate=validate.OneOf(["rider", "validator", "admin", "sponsor"]))
    organization_id = fields.Integer(allow_none=True)
    reason = fields.String(load_default="", validate=validate.Length(max=300))


class UserSearch(Schema):
    q = fields.String(load_default=None, validate=validate.Length(max=100))
    role = fields.String(load_default=None)
    limit = fields.Integer(load_default=50, validate=validate.Range(min=1, max=200))
    offset = fields.Integer(load_default=0, validate=validate.Range(min=0))


class Review(Base):
    approve = fields.Boolean(required=True)
    note = fields.String(load_default=None, validate=validate.Length(max=300))


class RefundIn(Base):
    target = fields.String(load_default="wallet", validate=validate.OneOf(["wallet", "card"]))
    reason = fields.String(load_default="", validate=validate.Length(max=300))


class AlertIn(Base):
    route_id = fields.Integer(required=True)
    severity = fields.String(load_default="delay", validate=validate.OneOf(["info", "delay", "cancelled"]))
    message_en = fields.String(required=True, validate=validate.Length(min=5, max=300))
    message_ar = fields.String(required=True, validate=validate.Length(min=5, max=300))


class OrganizationIn(Base):
    name = fields.String(required=True, validate=validate.Length(min=2, max=160))
    kind = fields.String(load_default="university", validate=validate.OneOf(["university", "company"]))
    email_domain = fields.String(load_default=None, validate=validate.Regexp(r"^[a-z0-9.-]+\.[a-z]{2,}$"))


class Paging(Schema):
    limit = fields.Integer(load_default=100, validate=validate.Range(min=1, max=500))
    offset = fields.Integer(load_default=0, validate=validate.Range(min=0))
    status = fields.String(load_default=None)
    action = fields.String(load_default=None)


class Days(Schema):
    days = fields.Integer(load_default=30, validate=validate.Range(min=1, max=365))
