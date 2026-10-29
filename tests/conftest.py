import os
import uuid

import pytest

os.environ.setdefault("APP_ENV", "test")

from buspass import create_app  # noqa: E402
from buspass.extensions import db  # noqa: E402
from buspass.models import Bus, Pass, Route, User  # noqa: E402
from buspass.seed import DEMO_PASSWORD, seed_demo  # noqa: E402
from buspass.services import qr  # noqa: E402


@pytest.fixture()
def app(tmp_path):
    app = create_app(
        {
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'test.db'}",
            "SECRET_KEY": "test-secret-0123456789abcdef0123456789",
            "JWT_SECRET": "test-jwt-0123456789abcdef0123456789abcd",
            "MOCK_WEBHOOK_SECRET": "test-webhook",
            "UPLOAD_DIR": str(tmp_path / "uploads"),
            "RATELIMIT_ENABLED": False,
            "DEMO_MODE": True,
            "PAYMENT_PROVIDER": "mock",
        }
    )
    with app.app_context():
        db.create_all()
        seed_demo(n_riders=6, days=5)
        yield app
        db.session.remove()


@pytest.fixture()
def client(app):
    return app.test_client()


def login(client, email, password=DEMO_PASSWORD):
    r = client.post("/api/v1/auth/login", json={"identifier": email, "password": password})
    assert r.status_code == 200, r.get_json()
    return {"Authorization": f"Bearer {r.get_json()['access_token']}"}


@pytest.fixture()
def rider_h(client):
    return login(client, "rider@cloudbus.test")


@pytest.fixture()
def admin_h(client):
    return login(client, "admin@cloudbus.test")


@pytest.fixture()
def validator_h(client):
    return login(client, "validator@cloudbus.test")


def user(email):
    return db.session.query(User).filter_by(email=email).one()


def route(code):
    return db.session.query(Route).filter_by(code=code).one()


def bus_on(code):
    return db.session.query(Bus).filter_by(route_id=route(code).id).first()


def token_for(p: Pass, window=None):
    """What the rider app shows: a fresh rotating code for this pass."""
    return qr.make_token(p.qr_secret, "P", p.id, window)


def wallet_token(u: User, window=None):
    return qr.make_token(u.wallet_qr_secret, "W", str(u.id), window)


def key():
    return uuid.uuid4().hex
