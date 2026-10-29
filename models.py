from datetime import datetime, timezone

from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)

    tickets = db.relationship("Ticket", back_populates="user", lazy="dynamic")


class Route(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(16), unique=True, nullable=False)
    origin = db.Column(db.String(120), nullable=False)
    destination = db.Column(db.String(120), nullable=False)
    departure_time = db.Column(db.String(5), nullable=False)  # "HH:MM"
    base_fare_cents = db.Column(db.Integer, nullable=False)
    capacity = db.Column(db.Integer, nullable=False)  # seats per day for single tickets

    def to_dict(self):
        return {
            "id": self.id,
            "code": self.code,
            "origin": self.origin,
            "destination": self.destination,
            "departure_time": self.departure_time,
            "base_fare_cents": self.base_fare_cents,
            "capacity": self.capacity,
        }


class Ticket(db.Model):
    # Random UUID: ticket ids cannot be guessed or enumerated.
    id = db.Column(db.String(32), primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    route_id = db.Column(db.Integer, db.ForeignKey("route.id"), nullable=False, index=True)
    pass_type = db.Column(db.String(16), nullable=False)
    price_cents = db.Column(db.Integer, nullable=False)
    valid_from = db.Column(db.Date, nullable=False, index=True)
    valid_until = db.Column(db.Date, nullable=False)
    # active -> used (single rides) | revoked (reported lost/stolen, replaced)
    status = db.Column(db.String(16), nullable=False, default="active")
    signature = db.Column(db.String(64), nullable=False)
    idempotency_key = db.Column(db.String(64), nullable=False)
    replaces_id = db.Column(db.String(32), nullable=True)
    scan_count = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)
    used_at = db.Column(db.DateTime, nullable=True)

    user = db.relationship("User", back_populates="tickets")
    route = db.relationship("Route")

    # The same booking form submitted twice (double click, retry) creates one ticket.
    __table_args__ = (db.UniqueConstraint("user_id", "idempotency_key", name="uq_ticket_idempotency"),)
