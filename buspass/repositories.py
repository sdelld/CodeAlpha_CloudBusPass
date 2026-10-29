"""Data access. Services call these functions; they never build queries themselves."""

from sqlalchemy import func, or_, select

from .extensions import db
from .models import (
    AuditLog,
    Bus,
    DiscountRule,
    FavoriteRoute,
    Notification,
    OtpCode,
    Pass,
    PassType,
    Payment,
    PaymentEvent,
    PromoCode,
    Receipt,
    RefreshToken,
    Ride,
    Route,
    SponsorBlock,
    SupportTicket,
    User,
    VerificationDocument,
    WalletTransaction,
)


def get(model, pk):
    return db.session.get(model, pk)


def get_for_update(model, pk):
    # Row lock on PostgreSQL; SQLite serialises writers at the database level instead.
    return db.session.execute(select(model).filter_by(**{_pk_name(model): pk}).with_for_update()).scalar_one_or_none()


def _pk_name(model):
    return model.__mapper__.primary_key[0].name


def add(obj):
    db.session.add(obj)
    return obj


def page(query, limit=50, offset=0):
    return db.session.execute(query.limit(limit).offset(offset)).scalars().all()


class Users:
    @staticmethod
    def by_identifier(identifier):
        identifier = identifier.strip().lower()
        return db.session.execute(
            select(User).where(or_(User.email == identifier, User.phone == identifier))
        ).scalar_one_or_none()

    @staticmethod
    def search(q=None, role=None, limit=50, offset=0):
        stmt = select(User).order_by(User.created_at.desc())
        if q:
            like = f"%{q.lower()}%"
            stmt = stmt.where(or_(func.lower(User.name).like(like), User.email.like(like), User.phone.like(like)))
        if role:
            stmt = stmt.where(User.role == role)
        return page(stmt, limit, offset)


class Otps:
    @staticmethod
    def latest_active(target, purpose):
        return (
            db.session.execute(
                select(OtpCode)
                .where(OtpCode.target == target, OtpCode.purpose == purpose, OtpCode.consumed_at.is_(None))
                .order_by(OtpCode.created_at.desc())
            )
            .scalars()
            .first()
        )


class RefreshTokens:
    @staticmethod
    def revoke_all_for(user_id, now):
        db.session.execute(
            RefreshToken.__table__.update()
            .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=now)
        )


class Routes:
    @staticmethod
    def all(active_only=True):
        stmt = select(Route).order_by(Route.code)
        if active_only:
            stmt = stmt.where(Route.active.is_(True))
        return db.session.execute(stmt).scalars().all()

    @staticmethod
    def by_code(code):
        return db.session.execute(select(Route).where(Route.code == code)).scalar_one_or_none()

    @staticmethod
    def favorites_of(user_id):
        return set(db.session.execute(select(FavoriteRoute.route_id).where(FavoriteRoute.user_id == user_id)).scalars())

    @staticmethod
    def users_following(route_id):
        favs = select(FavoriteRoute.user_id).where(FavoriteRoute.route_id == route_id)
        holders = select(Pass.user_id).where(Pass.route_id == route_id, Pass.status == "active")
        return set(db.session.execute(favs).scalars()) | set(db.session.execute(holders).scalars())


class Buses:
    @staticmethod
    def on_route(route_id):
        return (
            db.session.execute(select(Bus).where(Bus.route_id == route_id, Bus.status == "active").order_by(Bus.id))
            .scalars()
            .all()
        )

    @staticmethod
    def all():
        return db.session.execute(select(Bus).order_by(Bus.plate)).scalars().all()


class PassTypes:
    @staticmethod
    def all(active_only=True):
        stmt = select(PassType).order_by(PassType.sort)
        if active_only:
            stmt = stmt.where(PassType.active.is_(True))
        return db.session.execute(stmt).scalars().all()

    @staticmethod
    def by_code(code):
        return db.session.execute(select(PassType).where(PassType.code == code)).scalar_one_or_none()


class Discounts:
    @staticmethod
    def rule(code):
        return db.session.get(DiscountRule, code)

    @staticmethod
    def all():
        return db.session.execute(select(DiscountRule)).scalars().all()

    @staticmethod
    def promo(code):
        return db.session.execute(
            select(PromoCode).where(func.upper(PromoCode.code) == code.upper()).with_for_update()
        ).scalar_one_or_none()

    @staticmethod
    def promos():
        return db.session.execute(select(PromoCode).order_by(PromoCode.created_at.desc())).scalars().all()


class Passes:
    @staticmethod
    def of_user(user_id):
        return (
            db.session.execute(select(Pass).where(Pass.user_id == user_id).order_by(Pass.created_at.desc()))
            .scalars()
            .all()
        )

    @staticmethod
    def by_idempotency(user_id, key):
        return db.session.execute(
            select(Pass).where(Pass.user_id == user_id, Pass.idempotency_key == key)
        ).scalar_one_or_none()

    @staticmethod
    def singles_sold(route_id, day):
        single = select(PassType.id).where(PassType.max_rides == 1)
        return db.session.execute(
            select(func.count(Pass.id)).where(
                Pass.route_id == route_id,
                Pass.valid_from == day,
                Pass.pass_type_id.in_(single),
                Pass.status.notin_(["cancelled", "refunded", "revoked"]),
            )
        ).scalar()

    @staticmethod
    def active_expiring_on(day):
        return db.session.execute(select(Pass).where(Pass.status == "active", Pass.valid_until == day)).scalars().all()

    @staticmethod
    def active_ended_before(day):
        return db.session.execute(select(Pass).where(Pass.status == "active", Pass.valid_until < day)).scalars().all()

    @staticmethod
    def count_active(today):
        return db.session.execute(
            select(func.count(Pass.id)).where(
                Pass.status == "active", Pass.valid_from <= today, Pass.valid_until >= today
            )
        ).scalar()


class Payments:
    @staticmethod
    def by_idempotency(user_id, key):
        return db.session.execute(
            select(Payment).where(Payment.user_id == user_id, Payment.idempotency_key == key)
        ).scalar_one_or_none()

    @staticmethod
    def by_provider_ref(provider, ref):
        return db.session.execute(
            select(Payment).where(Payment.provider == provider, Payment.provider_ref == ref)
        ).scalar_one_or_none()

    @staticmethod
    def event_seen(provider, event_id):
        return (
            db.session.execute(
                select(PaymentEvent.id).where(PaymentEvent.provider == provider, PaymentEvent.event_id == event_id)
            ).first()
            is not None
        )

    @staticmethod
    def list(status=None, limit=100, offset=0):
        stmt = select(Payment).order_by(Payment.created_at.desc())
        if status:
            stmt = stmt.where(Payment.status == status)
        return page(stmt, limit, offset)


class Wallet:
    @staticmethod
    def history(user_id, limit=50):
        return (
            db.session.execute(
                select(WalletTransaction)
                .where(WalletTransaction.user_id == user_id)
                .order_by(WalletTransaction.id.desc())
                .limit(limit)
            )
            .scalars()
            .all()
        )


class Receipts:
    @staticmethod
    def of_user(user_id):
        return (
            db.session.execute(select(Receipt).where(Receipt.user_id == user_id).order_by(Receipt.created_at.desc()))
            .scalars()
            .all()
        )

    @staticmethod
    def next_number(year):
        count = db.session.execute(select(func.count(Receipt.id))).scalar()
        return f"CB-{year}-{count + 1:06d}"


class Rides:
    @staticmethod
    def of_user(user_id, limit=50):
        return (
            db.session.execute(
                select(Ride)
                .where(Ride.user_id == user_id, Ride.result.in_(["valid"]))
                .order_by(Ride.scanned_at.desc())
                .limit(limit)
            )
            .scalars()
            .all()
        )

    @staticmethod
    def by_client_id(client_scan_id):
        return db.session.execute(select(Ride).where(Ride.client_scan_id == client_scan_id)).scalar_one_or_none()

    @staticmethod
    def by_validator(validator_id, limit=30):
        return (
            db.session.execute(
                select(Ride).where(Ride.validator_id == validator_id).order_by(Ride.scanned_at.desc()).limit(limit)
            )
            .scalars()
            .all()
        )


class Notifications:
    @staticmethod
    def of_user(user_id, limit=50):
        return (
            db.session.execute(
                select(Notification)
                .where(Notification.user_id == user_id)
                .order_by(Notification.created_at.desc())
                .limit(limit)
            )
            .scalars()
            .all()
        )

    @staticmethod
    def unread_count(user_id):
        return db.session.execute(
            select(func.count(Notification.id)).where(Notification.user_id == user_id, Notification.read_at.is_(None))
        ).scalar()


class Verifications:
    @staticmethod
    def pending():
        return (
            db.session.execute(
                select(VerificationDocument)
                .where(VerificationDocument.status == "pending")
                .order_by(VerificationDocument.created_at)
            )
            .scalars()
            .all()
        )


class Support:
    @staticmethod
    def list(status=None):
        stmt = select(SupportTicket).order_by(SupportTicket.created_at.desc())
        if status:
            stmt = stmt.where(SupportTicket.status == status)
        return db.session.execute(stmt.limit(200)).scalars().all()


class Audit:
    @staticmethod
    def list(limit=100, offset=0, action=None):
        stmt = select(AuditLog).order_by(AuditLog.id.desc())
        if action:
            stmt = stmt.where(AuditLog.action.like(f"{action}%"))
        return page(stmt, limit, offset)


class Sponsors:
    @staticmethod
    def block_by_code(code):
        return db.session.execute(
            select(SponsorBlock).where(func.upper(SponsorBlock.invite_code) == code.upper()).with_for_update()
        ).scalar_one_or_none()

    @staticmethod
    def blocks_of(org_id):
        return (
            db.session.execute(
                select(SponsorBlock)
                .where(SponsorBlock.organization_id == org_id)
                .order_by(SponsorBlock.created_at.desc())
            )
            .scalars()
            .all()
        )
