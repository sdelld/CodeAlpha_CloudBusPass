import re
import sys
from datetime import timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import create_app, today  # noqa: E402
from models import Route, Ticket, db  # noqa: E402

CONDUCTOR = {"X-Conductor-Key": "test-conductor"}


@pytest.fixture()
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    app = create_app({"TESTING": True, "SECRET_KEY": "test-secret", "CONDUCTOR_KEY": "test-conductor"})
    yield app


@pytest.fixture()
def client(app):
    return app.test_client()


def csrf(client, path="/register"):
    html = client.get(path).get_data(as_text=True)
    return re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)


def signup(client, email="a@example.com", name="Alice"):
    token = csrf(client)
    return client.post("/register", data={"csrf_token": token, "name": name, "email": email,
                                          "password": "password123"})


def book(client, route_id=1, pass_type="single", day=None, key="k1", **extra):
    token = csrf(client, "/book")
    data = {"csrf_token": token, "route_id": route_id, "pass_type": pass_type,
            "travel_date": (day or today()).isoformat(), "idempotency_key": key, **extra}
    return client.post("/book", data=data)


def latest_ticket(app):
    with app.app_context():
        t = Ticket.query.order_by(Ticket.created_at.desc()).first()
        return t.id, f"BP1.{t.id}.{t.signature}"


def test_routes_seeded_and_health(client):
    assert len(client.get("/api/routes").get_json()) == 6
    assert client.get("/healthz").get_json()["status"] == "ok"


def test_booking_requires_login(client):
    assert client.get("/book").status_code == 302


def test_post_without_csrf_is_rejected(client):
    signup(client)
    r = client.post("/book", data={"route_id": 1, "pass_type": "single",
                                   "travel_date": today().isoformat(), "idempotency_key": "x"})
    assert r.status_code == 400


def test_price_is_computed_server_side(app, client):
    signup(client)
    # Attacker adds a price field; it must be ignored.
    book(client, route_id=1, pass_type="weekly", price_cents=1)
    with app.app_context():
        t = Ticket.query.one()
        assert t.price_cents == db.session.get(Route, 1).base_fare_cents * 12
    q = client.get("/api/quote?route_id=1&pass_type=day").get_json()
    assert q["price_cents"] == 1500 * 5 // 2


def test_double_submit_creates_one_ticket(app, client):
    signup(client)
    book(client, key="same")
    book(client, key="same")
    with app.app_context():
        assert Ticket.query.count() == 1


def test_capacity_prevents_overbooking(app, client):
    signup(client)
    with app.app_context():
        db.session.get(Route, 1).capacity = 2
        db.session.commit()
    book(client, key="a")
    book(client, key="b")
    assert b"sold out" in book(client, key="c").data
    with app.app_context():
        assert Ticket.query.count() == 2


def test_dates_out_of_range_rejected(app, client):
    signup(client)
    book(client, day=today() - timedelta(days=1), key="past")
    book(client, day=today() + timedelta(days=60), key="far")
    with app.app_context():
        assert Ticket.query.count() == 0


def test_single_ticket_is_single_use(app, client):
    signup(client)
    book(client)
    _, code = latest_ticket(app)
    first = client.post("/api/validate", json={"code": code}, headers=CONDUCTOR).get_json()
    second = client.post("/api/validate", json={"code": code}, headers=CONDUCTOR).get_json()
    assert first["valid"] is True and first["passenger"] == "Alice"
    assert second["valid"] is False and "already used" in second["reason"]


def test_pass_can_be_scanned_many_times(app, client):
    signup(client)
    book(client, pass_type="day")
    _, code = latest_ticket(app)
    for _ in range(3):
        assert client.post("/api/validate", json={"code": code}, headers=CONDUCTOR).get_json()["valid"]


def test_forged_or_tampered_codes_rejected(app, client):
    signup(client)
    book(client)
    tid, code = latest_ticket(app)
    forged = f"BP1.{tid}.{'0' * 64}"
    assert client.post("/api/validate", json={"code": forged}, headers=CONDUCTOR).get_json()["valid"] is False
    # Someone edits the price directly in the database: the signature no longer matches.
    with app.app_context():
        db.session.get(Ticket, tid).price_cents = 1
        db.session.commit()
    r = client.post("/api/validate", json={"code": code}, headers=CONDUCTOR).get_json()
    assert r["valid"] is False and "counterfeit" in r["reason"]


def test_scanner_needs_key(app, client):
    signup(client)
    book(client)
    _, code = latest_ticket(app)
    assert client.post("/api/validate", json={"code": code}).status_code == 401


def test_wrong_route_rejected(app, client):
    signup(client)
    book(client, route_id=1)
    _, code = latest_ticket(app)
    r = client.post("/api/validate", json={"code": code, "route_code": "R2"}, headers=CONDUCTOR).get_json()
    assert r["valid"] is False


def test_report_lost_blocks_old_code_and_issues_new(app, client):
    signup(client)
    book(client)
    old_id, old_code = latest_ticket(app)
    token = csrf(client, f"/tickets/{old_id}")
    r = client.post(f"/tickets/{old_id}/report-lost", data={"csrf_token": token})
    new_id = r.headers["Location"].rsplit("/", 1)[-1]
    assert new_id != old_id
    with app.app_context():
        new = db.session.get(Ticket, new_id)
        new_code = f"BP1.{new.id}.{new.signature}"
        assert new.replaces_id == old_id
    old = client.post("/api/validate", json={"code": old_code}, headers=CONDUCTOR).get_json()
    assert old["valid"] is False and "lost" in old["reason"]
    assert client.post("/api/validate", json={"code": new_code}, headers=CONDUCTOR).get_json()["valid"]


def test_users_cannot_see_each_others_tickets(app):
    alice, bob = app.test_client(), app.test_client()
    signup(alice, "alice@example.com", "Alice")
    book(alice)
    tid, _ = latest_ticket(app)
    signup(bob, "bob@example.com", "Bob")
    assert bob.get(f"/tickets/{tid}").status_code == 404
    assert alice.get(f"/tickets/{tid}").status_code == 200
