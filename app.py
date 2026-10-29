import hmac
import os
import secrets
import uuid
from datetime import date, datetime, timedelta, timezone
from functools import wraps

import segno
from flask import Flask, abort, current_app, flash, g, jsonify, redirect, render_template, request, session, url_for
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from werkzeug.security import check_password_hash, generate_password_hash

import tickets
from models import Route, Ticket, User, db, utcnow
from pricing import PASS_TYPES, format_money, quote_cents, validity

MAX_DAYS_AHEAD = 30

SEED_ROUTES = [
    ("R1", "Central Station", "University", "07:30", 1500, 50),
    ("R2", "Central Station", "Airport", "08:00", 4000, 40),
    ("R3", "North Terminal", "City Mall", "09:15", 1200, 50),
    ("R4", "University", "Tech Park", "10:00", 1800, 45),
    ("R5", "Old Town", "Harbour", "12:30", 1000, 30),
    ("R6", "Airport", "North Terminal", "18:45", 3500, 40),
]


def database_url():
    url = os.environ.get("DATABASE_URL", "sqlite:///buspass.db")
    # Heroku/Render/RDS style URLs -> SQLAlchemy psycopg3 driver.
    if url.startswith("postgres://"):
        url = "postgresql+psycopg://" + url[len("postgres://"):]
    elif url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


def today():
    return datetime.now(timezone.utc).date()


def create_app(config=None):
    app = Flask(__name__)
    app.config.update(
        SECRET_KEY=os.environ.get("SECRET_KEY", "dev-only-change-me"),
        CONDUCTOR_KEY=os.environ.get("CONDUCTOR_KEY", "conductor-dev-key"),
        CURRENCY=os.environ.get("CURRENCY", "USD"),
        SQLALCHEMY_DATABASE_URI=database_url(),
        SQLALCHEMY_ENGINE_OPTIONS={"pool_pre_ping": True},
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.environ.get("SESSION_COOKIE_SECURE") == "1",
    )
    if config:
        app.config.update(config)

    db.init_app(app)
    with app.app_context():
        init_db()

    register_helpers(app)
    register_routes(app)
    return app


def init_db():
    with db.engine.begin() as conn:
        # Many servers boot at once when the cluster scales; a transaction-scoped advisory lock
        # lets exactly one of them create tables and seed data while the others wait.
        if conn.dialect.name == "postgresql":
            conn.execute(text("SELECT pg_advisory_xact_lock(724001)"))
        db.metadata.create_all(bind=conn)
        if conn.execute(select(func.count()).select_from(Route.__table__)).scalar() == 0:
            conn.execute(Route.__table__.insert(), [
                {"code": code, "origin": origin, "destination": dest, "departure_time": dep,
                 "base_fare_cents": fare, "capacity": cap}
                for code, origin, dest, dep, fare, cap in SEED_ROUTES
            ])


def register_helpers(app):
    @app.before_request
    def load_user():
        uid = session.get("uid")
        g.user = db.session.get(User, uid) if uid else None

    @app.context_processor
    def inject():
        return {
            "current_user": g.get("user"),
            "csrf_token": csrf_token,
            "money": lambda cents: format_money(cents, app.config["CURRENCY"]),
            "PASS_TYPES": PASS_TYPES,
        }


def csrf_token():
    if "csrf" not in session:
        session["csrf"] = secrets.token_urlsafe(32)
    return session["csrf"]


def check_csrf():
    sent = request.form.get("csrf_token", "")
    expected = session.get("csrf")
    if not expected or not hmac.compare_digest(sent, expected):
        abort(400, "Invalid or missing CSRF token")


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if g.user is None:
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


def own_ticket_or_404(ticket_id):
    ticket = db.session.get(Ticket, ticket_id)
    # 404 rather than 403 so other users' ticket ids are not confirmed to exist.
    if ticket is None or ticket.user_id != g.user.id:
        abort(404)
    return ticket


def seats_sold(route_id, day):
    return (
        db.session.query(func.count(Ticket.id))
        .filter(Ticket.route_id == route_id, Ticket.pass_type == "single",
                Ticket.valid_from == day, Ticket.status != "revoked")
        .scalar()
    )


def issue_ticket(user_id, route, pass_type, start, price_cents, idempotency_key, replaces_id=None):
    valid_from, valid_until = validity(pass_type, start)
    t = Ticket(id=uuid.uuid4().hex, user_id=user_id, route_id=route.id, pass_type=pass_type,
               price_cents=price_cents, valid_from=valid_from, valid_until=valid_until,
               status="active", idempotency_key=idempotency_key, replaces_id=replaces_id)
    t.signature = tickets.sign(t, current_app.config["SECRET_KEY"])
    db.session.add(t)
    return t


def register_routes(app):
    @app.get("/")
    def index():
        routes = Route.query.order_by(Route.code).all()
        return render_template("index.html", routes=routes)

    @app.route("/register", methods=["GET", "POST"])
    def register():
        if request.method == "POST":
            check_csrf()
            name = request.form.get("name", "").strip()
            email = request.form.get("email", "").strip().lower()
            password = request.form.get("password", "")
            if not name or "@" not in email or len(password) < 8:
                flash("Enter your name, a valid email and a password of at least 8 characters.", "error")
            elif User.query.filter_by(email=email).first():
                flash("An account with that email already exists.", "error")
            else:
                user = User(name=name, email=email, password_hash=generate_password_hash(password))
                db.session.add(user)
                db.session.commit()
                session.clear()
                session["uid"] = user.id
                flash("Account created. Welcome!", "ok")
                return redirect(url_for("book"))
        return render_template("auth.html", mode="register")

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            check_csrf()
            email = request.form.get("email", "").strip().lower()
            user = User.query.filter_by(email=email).first()
            if user and check_password_hash(user.password_hash, request.form.get("password", "")):
                session.clear()
                session["uid"] = user.id
                nxt = request.args.get("next", "")
                return redirect(nxt if nxt.startswith("/") and not nxt.startswith("//") else url_for("my_tickets"))
            flash("Wrong email or password.", "error")
        return render_template("auth.html", mode="login")

    @app.post("/logout")
    def logout():
        check_csrf()
        session.clear()
        return redirect(url_for("index"))

    @app.route("/book", methods=["GET", "POST"])
    @login_required
    def book():
        routes = Route.query.order_by(Route.code).all()
        if request.method == "POST":
            check_csrf()
            ticket, error = book_from_form(request.form)
            if ticket:
                flash("Booking confirmed. Your ticket is saved to your account.", "ok")
                return redirect(url_for("ticket_detail", ticket_id=ticket.id))
            flash(error, "error")
        return render_template("book.html", routes=routes, today=today(),
                               max_day=today() + timedelta(days=MAX_DAYS_AHEAD),
                               idempotency_key=uuid.uuid4().hex,
                               selected=request.args.get("route", type=int))

    def book_from_form(form):
        pass_type = form.get("pass_type")
        if pass_type not in PASS_TYPES:
            return None, "Choose a valid ticket type."
        try:
            start = date.fromisoformat(form.get("travel_date", ""))
            route_id = int(form.get("route_id", ""))
        except ValueError:
            return None, "Choose a route and a valid date."
        if not today() <= start <= today() + timedelta(days=MAX_DAYS_AHEAD):
            return None, f"Travel date must be between today and {MAX_DAYS_AHEAD} days ahead."
        key = form.get("idempotency_key", "")
        if not key.isalnum() or len(key) > 64:
            return None, "Invalid booking request, please reload the page."

        existing = Ticket.query.filter_by(user_id=g.user.id, idempotency_key=key).first()
        if existing:
            return existing, None

        # Row lock on the route serialises concurrent bookings for it (PostgreSQL),
        # so two buyers can never take the last seat at the same time.
        route = db.session.query(Route).filter_by(id=route_id).with_for_update().first()
        if route is None:
            return None, "That route does not exist."
        if PASS_TYPES[pass_type]["single_use"] and seats_sold(route.id, start) >= route.capacity:
            db.session.rollback()
            return None, "Sorry, this trip is sold out for that date."

        # Price comes only from the server-side fare table; any price sent by the browser is ignored.
        price = quote_cents(route.base_fare_cents, pass_type)
        ticket = issue_ticket(g.user.id, route, pass_type, start, price, key)
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            return Ticket.query.filter_by(user_id=g.user.id, idempotency_key=key).first(), None
        return ticket, None

    @app.get("/tickets")
    @login_required
    def my_tickets():
        rows = g.user.tickets.order_by(Ticket.created_at.desc()).all()
        return render_template("tickets.html", tickets=rows, today=today())

    @app.get("/tickets/<ticket_id>")
    @login_required
    def ticket_detail(ticket_id):
        ticket = own_ticket_or_404(ticket_id)
        qr_svg = None
        if ticket.status == "active":
            qr_svg = segno.make(tickets.encode(ticket), error="m").svg_inline(scale=6, dark="#111827")
        return render_template("ticket.html", ticket=ticket, qr_svg=qr_svg, code=tickets.encode(ticket),
                               today=today())

    @app.post("/tickets/<ticket_id>/report-lost")
    @login_required
    def report_lost(ticket_id):
        check_csrf()
        old = own_ticket_or_404(ticket_id)
        if old.status != "active" or old.valid_until < today():
            flash("Only active tickets can be replaced.", "error")
            return redirect(url_for("ticket_detail", ticket_id=old.id))
        # The old QR code stops working immediately; the passenger gets a fresh one at no charge.
        old.status = "revoked"
        new = issue_ticket(old.user_id, old.route, old.pass_type, old.valid_from, old.price_cents,
                           uuid.uuid4().hex, replaces_id=old.id)
        db.session.commit()
        flash("The old ticket was blocked. This is your replacement ticket.", "ok")
        return redirect(url_for("ticket_detail", ticket_id=new.id))

    @app.get("/conductor")
    def conductor():
        return render_template("conductor.html")

    # ---- JSON API ----

    @app.get("/api/routes")
    def api_routes():
        return jsonify([r.to_dict() for r in Route.query.order_by(Route.code)])

    @app.get("/api/quote")
    def api_quote():
        route = db.session.get(Route, request.args.get("route_id", type=int) or 0)
        pass_type = request.args.get("pass_type")
        if route is None or pass_type not in PASS_TYPES:
            return jsonify(error="unknown route or pass type"), 400
        cents = quote_cents(route.base_fare_cents, pass_type)
        day = request.args.get("date")
        left = None
        if PASS_TYPES[pass_type]["single_use"] and day:
            try:
                left = max(route.capacity - seats_sold(route.id, date.fromisoformat(day)), 0)
            except ValueError:
                pass
        return jsonify(price_cents=cents, display=format_money(cents, app.config["CURRENCY"]), seats_left=left)

    @app.post("/api/validate")
    def api_validate():
        key = request.headers.get("X-Conductor-Key", "")
        if not hmac.compare_digest(key, app.config["CONDUCTOR_KEY"]):
            return jsonify(valid=False, reason="unauthorised scanner"), 401
        body = request.get_json(silent=True) or {}
        parsed = tickets.decode(body.get("code"))
        if parsed is None:
            return jsonify(valid=False, reason="unreadable code"), 400
        ticket_id, signature = parsed

        ticket = db.session.query(Ticket).filter_by(id=ticket_id).with_for_update().first()
        if ticket is None or not tickets.verify(ticket, signature, app.config["SECRET_KEY"]):
            return jsonify(valid=False, reason="counterfeit or unknown ticket"), 200
        if ticket.status == "revoked":
            return jsonify(valid=False, reason="ticket was reported lost/stolen"), 200
        if ticket.status == "used":
            return jsonify(valid=False, reason=f"already used at {ticket.used_at:%Y-%m-%d %H:%M} UTC"), 200
        if not ticket.valid_from <= today() <= ticket.valid_until:
            return jsonify(valid=False, reason=f"valid {ticket.valid_from} to {ticket.valid_until} only"), 200
        route_code = body.get("route_code")
        if route_code and route_code != ticket.route.code:
            return jsonify(valid=False, reason=f"ticket is for route {ticket.route.code}"), 200

        ticket.scan_count += 1
        if PASS_TYPES[ticket.pass_type]["single_use"]:
            ticket.status = "used"
            ticket.used_at = utcnow()
        db.session.commit()
        return jsonify(valid=True, passenger=ticket.user.name, route=ticket.route.code,
                       pass_type=PASS_TYPES[ticket.pass_type]["label"],
                       valid_until=ticket.valid_until.isoformat(), scans=ticket.scan_count)

    @app.get("/healthz")
    def healthz():
        # Load balancers / auto-scaling groups use this to decide if an instance is healthy.
        try:
            db.session.execute(text("SELECT 1"))
        except Exception:
            return jsonify(status="db-unavailable"), 503
        return jsonify(status="ok", instance=os.environ.get("HOSTNAME", "local"))

    @app.errorhandler(404)
    def not_found(e):
        if request.path.startswith("/api/"):
            return jsonify(error="not found"), 404
        return render_template("message.html", title="Not found", message="That page does not exist."), 404


if __name__ == "__main__":
    create_app().run(debug=True)
