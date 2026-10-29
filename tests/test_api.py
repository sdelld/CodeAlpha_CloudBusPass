"""Integration tests through the HTTP API."""

import io
import json

from buspass.extensions import db
from buspass.models import AuditLog, Pass, Payment
from buspass.payments.mock import MockProvider

from .conftest import bus_on, key, login, route, token_for, user


def err(resp):
    return resp.get_json()["error"]


# ---------- auth ----------


def test_register_verify_and_me(client):
    r = client.post(
        "/api/v1/auth/register", json={"name": "Nour", "email": "nour@example.test", "password": "secret123"}
    )
    assert r.status_code == 201
    code = r.get_json()["dev_code"]
    r = client.post("/api/v1/auth/verify", json={"target": "nour@example.test", "code": code})
    assert r.status_code == 200 and "cb_refresh" in r.headers.get("Set-Cookie", "")
    h = {"Authorization": f"Bearer {r.get_json()['access_token']}"}
    me = client.get("/api/v1/me", headers=h).get_json()
    assert me["name"] == "Nour" and me["status"] == "active" and me["role"] == "rider"


def test_validation_errors_have_consistent_shape(client):
    r = client.post("/api/v1/auth/register", json={"name": "N", "password": "x", "extra": 1})
    e = err(r)
    assert r.status_code == 422 and e["code"] == "validation_error"
    assert {"name", "password", "extra"} <= set(e["details"]["json"])


def test_wrong_password(client):
    r = client.post("/api/v1/auth/login", json={"identifier": "rider@cloudbus.test", "password": "nope"})
    assert r.status_code == 401 and err(r)["code"] == "invalid_credentials"


def test_otp_login(client):
    code = client.post("/api/v1/auth/otp/request", json={"target": "rider@cloudbus.test"}).get_json()["dev_code"]
    r = client.post("/api/v1/auth/otp/login", json={"target": "rider@cloudbus.test", "code": code})
    assert r.status_code == 200 and r.get_json()["user"]["email"] == "rider@cloudbus.test"


def test_otp_request_does_not_reveal_accounts(client):
    r = client.post("/api/v1/auth/otp/request", json={"target": "ghost@example.test"})
    assert r.status_code == 200 and "dev_code" not in r.get_json()


def test_refresh_rotation_and_reuse_detection(client):
    tokens = client.post(
        "/api/v1/auth/login", json={"identifier": "rider@cloudbus.test", "password": "Demo@12345"}
    ).get_json()
    first = tokens["refresh_token"]
    r = client.post("/api/v1/auth/refresh", json={"refresh_token": first})
    assert r.status_code == 200
    second = r.get_json()["refresh_token"]
    # Re-using the rotated token looks like theft: the whole session family is revoked.
    assert client.post("/api/v1/auth/refresh", json={"refresh_token": first}).status_code == 401
    assert client.post("/api/v1/auth/refresh", json={"refresh_token": second}).status_code == 401


def test_refresh_from_cookie(client):
    login(client, "rider@cloudbus.test")
    r = client.post("/api/v1/auth/refresh", json={})
    assert r.status_code == 200


def test_suspended_user_is_locked_out(client, admin_h, rider_h):
    rider_id = user("rider@cloudbus.test").id
    client.patch(f"/api/v1/admin/users/{rider_id}", json={"status": "suspended", "reason": "fraud"}, headers=admin_h)
    r = client.get("/api/v1/me", headers=rider_h)
    assert r.status_code == 403 and err(r)["code"] == "account_suspended"


# ---------- RBAC ----------


def test_role_based_access(client, rider_h, validator_h):
    assert client.get("/api/v1/admin/overview", headers=rider_h).status_code == 403
    assert client.get("/api/v1/admin/overview", headers=validator_h).status_code == 403
    assert client.post("/api/v1/validator/scan", json={"token": "x", "bus_id": 1}, headers=rider_h).status_code == 403
    assert client.get("/api/v1/me").status_code == 401


# ---------- catalog ----------


def test_routes_schedules_and_live(client, rider_h):
    routes = client.get("/api/v1/routes", headers=rider_h).get_json()["items"]
    assert len(routes) == 6 and routes[0]["next_departures"]
    assert any(r["favorite"] for r in routes)
    detail = client.get(f"/api/v1/routes/{routes[0]['id']}").get_json()
    assert len(detail["stops"]) >= 2 and detail["stops"][0]["name_ar"]
    live = client.get(f"/api/v1/routes/{routes[0]['id']}/live").get_json()
    assert live["simulated"] and len(live["buses"]) == 3 and live["buses"][0]["eta_minutes"] >= 1


def test_favorites(client, rider_h):
    rid = route("R1").id
    client.put(f"/api/v1/me/favorites/{rid}", headers=rider_h)
    routes = {r["id"]: r for r in client.get("/api/v1/routes", headers=rider_h).get_json()["items"]}
    assert routes[rid]["favorite"]
    client.delete(f"/api/v1/me/favorites/{rid}", headers=rider_h)
    routes = {r["id"]: r for r in client.get("/api/v1/routes", headers=rider_h).get_json()["items"]}
    assert not routes[rid]["favorite"]


# ---------- passes & payments ----------


def test_quote_with_promo(client):
    r = client.get(f"/api/v1/passes/quote?route_id={route('R1').id}&pass_type=weekly&promo_code=WELCOME20")
    q = r.get_json()
    assert q["total_cents"] == 1200 * 12 * 80 // 100 and q["currency"] == "EGP"
    bad = client.get(f"/api/v1/passes/quote?route_id={route('R1').id}&pass_type=weekly&promo_code=NOPE")
    assert bad.status_code == 422 and err(bad)["code"] == "promo_invalid"


def test_buy_pass_with_wallet_ignores_client_price(client, rider_h):
    body = {"route_id": route("R2").id, "pass_type": "daily", "idempotency_key": key()}
    r = client.post("/api/v1/passes", json={**body, "price_cents": 1}, headers=rider_h)
    assert r.status_code == 422  # unknown field rejected outright
    r = client.post("/api/v1/passes", json=body, headers=rider_h)
    assert r.status_code == 201 and r.get_json()["price_cents"] == 3500 * 5 // 2
    assert r.get_json()["qr"]["secret"]


def test_insufficient_wallet_balance(client, rider_h):
    r = client.post(
        "/api/v1/passes",
        json={"route_id": route("R2").id, "pass_type": "semester", "idempotency_key": key()},
        headers=rider_h,
    )
    assert r.status_code == 402 and err(r)["code"] == "insufficient_funds"


def _complete_mock(client, payment_id, outcome="pay"):
    return client.post(f"/pay/mock/{payment_id}", data={"outcome": outcome})


def test_topup_via_mock_checkout(client, rider_h):
    r = client.post(
        "/api/v1/payments/checkout",
        json={"purpose": "topup", "amount_cents": 10000, "idempotency_key": key()},
        headers=rider_h,
    )
    pay = r.get_json()
    assert r.status_code == 201 and pay["checkout_url"] == f"/pay/mock/{pay['id']}" and pay["status"] == "pending"
    assert _complete_mock(client, pay["id"]).status_code == 302
    assert client.get(f"/api/v1/payments/{pay['id']}", headers=rider_h).get_json()["status"] == "succeeded"
    assert client.get("/api/v1/me/wallet", headers=rider_h).get_json()["balance_cents"] == 35000
    receipts = client.get("/api/v1/me/receipts", headers=rider_h).get_json()["items"]
    assert receipts[0]["description"] == "Wallet top-up"


def test_topup_limits(client, rider_h):
    r = client.post(
        "/api/v1/payments/checkout",
        json={"purpose": "topup", "amount_cents": 100, "idempotency_key": key()},
        headers=rider_h,
    )
    assert r.status_code == 422


def test_card_pass_purchase(client, rider_h):
    r = client.post(
        "/api/v1/payments/checkout",
        json={
            "purpose": "pass",
            "route_id": route("R4").id,
            "pass_type": "weekly",
            "promo_code": "WELCOME20",
            "idempotency_key": key(),
        },
        headers=rider_h,
    )
    pay = r.get_json()
    assert pay["amount_cents"] == 2000 * 12 * 80 // 100
    _complete_mock(client, pay["id"])
    mine = client.get("/api/v1/passes", headers=rider_h).get_json()["items"]
    assert any(p["route"]["code"] == "R4" and p["pass_type"]["code"] == "weekly" for p in mine)


def test_failed_payment_creates_nothing(client, rider_h):
    pay = client.post(
        "/api/v1/payments/checkout",
        json={"purpose": "topup", "amount_cents": 5000, "idempotency_key": key()},
        headers=rider_h,
    ).get_json()
    _complete_mock(client, pay["id"], outcome="fail")
    assert client.get(f"/api/v1/payments/{pay['id']}", headers=rider_h).get_json()["status"] == "failed"
    assert client.get("/api/v1/me/wallet", headers=rider_h).get_json()["balance_cents"] == 25000


def test_webhook_signature_and_idempotency(app, client, rider_h):
    pay = client.post(
        "/api/v1/payments/checkout",
        json={"purpose": "topup", "amount_cents": 5000, "idempotency_key": key()},
        headers=rider_h,
    ).get_json()
    payment = db.session.get(Payment, pay["id"])
    provider = MockProvider(app.config)
    body, sig = provider.build_event(payment, "succeeded")
    bad = client.post("/api/v1/payments/webhooks/mock", data=body, headers={"X-Mock-Signature": "0" * 64})
    assert bad.status_code == 400
    ok = client.post("/api/v1/payments/webhooks/mock", data=body, headers={"X-Mock-Signature": sig})
    dup = client.post("/api/v1/payments/webhooks/mock", data=body, headers={"X-Mock-Signature": sig})
    assert ok.get_json()["status"] == "succeeded" and dup.get_json()["status"] == "duplicate"
    assert client.get("/api/v1/me/wallet", headers=rider_h).get_json()["balance_cents"] == 30000


def test_webhook_amount_mismatch_is_not_fulfilled(app, client, rider_h):
    pay = client.post(
        "/api/v1/payments/checkout",
        json={"purpose": "topup", "amount_cents": 5000, "idempotency_key": key()},
        headers=rider_h,
    ).get_json()
    provider = MockProvider(app.config)
    body = json.dumps(
        {"id": "evt_x", "type": "payment.succeeded", "provider_ref": "r", "payment_id": pay["id"], "amount_cents": 1}
    ).encode()
    client.post("/api/v1/payments/webhooks/mock", data=body, headers={"X-Mock-Signature": provider.sign(body)})
    assert client.get("/api/v1/me/wallet", headers=rider_h).get_json()["balance_cents"] == 25000


def test_auto_renew_toggle_and_rotate(client, rider_h):
    p = client.get("/api/v1/passes", headers=rider_h).get_json()["items"][0]
    r = client.patch(f"/api/v1/passes/{p['id']}", json={"auto_renew": False}, headers=rider_h)
    assert r.get_json()["auto_renew"] is False
    rotated = client.post(f"/api/v1/passes/{p['id']}/rotate-key", headers=rider_h).get_json()
    assert rotated["qr"]["secret"] != p["qr"]["secret"]


def test_cannot_see_other_riders_pass(client, rider_h):
    other = login(client, "student@cu.test")
    pid = client.get("/api/v1/passes", headers=other).get_json()["items"][0]["id"]
    assert client.get(f"/api/v1/passes/{pid}", headers=rider_h).status_code == 404


def test_redeem_sponsor_code(client):
    h = login(client, "student@cu.test")
    r = client.post("/api/v1/passes/redeem", json={"code": "CUFALL26"}, headers=h)
    assert r.status_code == 201 and r.get_json()["source"] == "sponsor"


# ---------- account ----------


def test_verification_upload_and_admin_review(client, admin_h):
    h = login(client, "senior@cloudbus.test")
    fake = client.post(
        "/api/v1/me/verification",
        data={"kind": "senior", "file": (io.BytesIO(b"MZ..exe"), "id.png", "image/png")},
        headers=h,
        content_type="multipart/form-data",
    )
    assert fake.status_code == 422
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 100
    r = client.post(
        "/api/v1/me/verification",
        data={"kind": "senior", "file": (io.BytesIO(png), "id.png", "image/png")},
        headers=h,
        content_type="multipart/form-data",
    )
    assert r.status_code == 201
    pending = client.get("/api/v1/admin/verifications", headers=admin_h).get_json()["items"]
    doc = next(d for d in pending if d["user_name"] == "Mahmoud Senior")
    assert client.get(f"/api/v1/admin/verifications/{doc['id']}/file", headers=admin_h).data == png
    client.post(f"/api/v1/admin/verifications/{doc['id']}", json={"approve": True}, headers=admin_h)
    assert client.get("/api/v1/me", headers=h).get_json()["discount_status"] == "approved"
    q = client.get(f"/api/v1/passes/quote?route_id={route('R1').id}&pass_type=monthly", headers=h).get_json()
    assert q["discount_cents"] == 1200 * 40 // 2


def test_support_and_notifications(client, rider_h, admin_h):
    r = client.post(
        "/api/v1/me/support",
        json={"category": "bus", "message": "The 8am R3 bus was 30 minutes late."},
        headers=rider_h,
    )
    assert r.status_code == 201
    n = client.get("/api/v1/me/notifications", headers=rider_h).get_json()
    assert n["unread"] >= 1 and n["items"][0]["kind"] == "support"
    client.post("/api/v1/me/notifications/read", json={}, headers=rider_h)
    assert client.get("/api/v1/me/notifications", headers=rider_h).get_json()["unread"] == 0
    tickets = client.get("/api/v1/admin/support", headers=admin_h).get_json()["items"]
    assert tickets[0]["category"] == "bus"


# ---------- admin ----------


def test_admin_crud_is_audited(client, admin_h):
    stop_ids = [s["id"] for s in client.get("/api/v1/admin/stops", headers=admin_h).get_json()["items"][:2]]
    body = {
        "code": "R9",
        "name_en": "Test Line",
        "name_ar": "خط تجريبي",
        "base_fare_cents": 1500,
        "stops": [
            {"stop_id": stop_ids[0], "minutes_from_start": 0},
            {"stop_id": stop_ids[1], "minutes_from_start": 12},
        ],
        "departures": ["08:00", "07:00"],
    }
    r = client.post("/api/v1/admin/routes", json=body, headers=admin_h)
    assert r.status_code == 201 and r.get_json()["departures"] == ["07:00", "08:00"]
    rid = r.get_json()["id"]
    assert client.post("/api/v1/admin/routes", json=body, headers=admin_h).status_code == 409
    r = client.patch(f"/api/v1/admin/routes/{rid}", json={"base_fare_cents": 1700}, headers=admin_h)
    assert r.get_json()["base_fare_cents"] == 1700
    assert client.patch(f"/api/v1/admin/routes/{rid}", json={"base_fare_cents": 5}, headers=admin_h).status_code == 422
    client.delete(f"/api/v1/admin/routes/{rid}", headers=admin_h)
    assert all(x["code"] != "R9" for x in client.get("/api/v1/routes").get_json()["items"])
    actions = [a.action for a in db.session.query(AuditLog).all()]
    assert {"routes.created", "routes.updated", "routes.deactivated"} <= set(actions)


def test_admin_promo_and_discount_edit(client, admin_h):
    r = client.post(
        "/api/v1/admin/promo_codes", json={"code": "EID30", "kind": "percent", "value": 30}, headers=admin_h
    )
    assert r.status_code == 201
    assert (
        client.post(
            "/api/v1/admin/promo_codes", json={"code": "BAD", "kind": "percent", "value": 300}, headers=admin_h
        ).status_code
        == 422
    )
    r = client.patch("/api/v1/admin/discounts/student", json={"percent": 35}, headers=admin_h)
    assert r.get_json()["percent"] == 35


def test_refund_wallet_pass(client, admin_h, rider_h):
    p = client.post(
        "/api/v1/passes",
        json={"route_id": route("R5").id, "pass_type": "weekly", "idempotency_key": key()},
        headers=rider_h,
    ).get_json()
    before = client.get("/api/v1/me/wallet", headers=rider_h).get_json()["balance_cents"]
    r = client.post(f"/api/v1/admin/passes/{p['id']}/refund", json={"reason": "bus cancelled"}, headers=admin_h)
    assert r.get_json()["status"] == "refunded"
    assert client.get("/api/v1/me/wallet", headers=rider_h).get_json()["balance_cents"] == before + p["price_cents"]
    assert client.post(f"/api/v1/admin/passes/{p['id']}/refund", json={}, headers=admin_h).status_code == 409


def test_refund_card_payment_to_wallet(client, admin_h, rider_h):
    pay = client.post(
        "/api/v1/payments/checkout",
        json={"purpose": "pass", "route_id": route("R4").id, "pass_type": "daily", "idempotency_key": key()},
        headers=rider_h,
    ).get_json()
    _complete_mock(client, pay["id"])
    r = client.post(f"/api/v1/admin/payments/{pay['id']}/refund", json={"target": "wallet"}, headers=admin_h)
    assert r.get_json()["status"] == "refunded"
    assert db.session.query(Pass).filter_by(payment_id=pay["id"]).one().status == "refunded"


def test_analytics_overview(client, admin_h):
    o = client.get("/api/v1/admin/overview?days=30", headers=admin_h).get_json()
    assert len(o["revenue_by_day"]) == 30 and len(o["rides_by_hour"]) == 24
    assert o["kpis"]["active_passes"] >= 2 and o["kpis"]["revenue_cents"] > 0
    assert sum(x["rides"] for x in o["rides_by_route"]) == o["kpis"]["rides"]


def test_csv_export_escapes_formulas(client, admin_h, rider_h):
    client.patch("/api/v1/me", json={"name": "=HYPERLINK(evil)"}, headers=rider_h)
    r = client.get("/api/v1/admin/export/users.csv", headers=admin_h)
    assert r.mimetype == "text/csv" and "'=HYPERLINK(evil)" in r.get_data(as_text=True)
    assert client.get("/api/v1/admin/export/secrets.csv", headers=admin_h).status_code == 404


def test_service_alert_notifies_followers(client, admin_h, rider_h):
    r = client.post(
        "/api/v1/admin/alerts",
        json={
            "route_id": route("R3").id,
            "severity": "delay",
            "message_en": "Traffic on the Ring Road: ~15 min delay.",
            "message_ar": "زحام على الطريق الدائري: تأخير 15 دقيقة تقريبًا.",
        },
        headers=admin_h,
    )
    assert r.status_code == 201
    assert client.get("/api/v1/me/notifications", headers=rider_h).get_json()["items"][0]["kind"] == "delay"


def test_sponsor_dashboard_and_seat_purchase(client):
    h = login(client, "sponsor@cu.test")
    d = client.get("/api/v1/sponsor/dashboard", headers=h).get_json()
    assert d["organization"]["name"] == "Cairo University" and d["blocks"][0]["invite_code"] == "CUFALL26"
    pay = client.post(
        "/api/v1/payments/checkout",
        json={
            "purpose": "sponsor_seats",
            "route_id": route("R6").id,
            "pass_type": "monthly",
            "seats": 50,
            "idempotency_key": key(),
        },
        headers=h,
    ).get_json()
    assert pay["amount_cents"] == 1800 * 30 * 50
    _complete_mock(client, pay["id"])
    assert len(client.get("/api/v1/sponsor/dashboard", headers=h).get_json()["blocks"]) == 2


# ---------- platform ----------


def test_openapi_and_health(client):
    spec = client.get("/api/v1/openapi.json").get_json()
    assert spec["info"]["title"] == "CloudBus Pass API" and "/api/v1/passes" in spec["paths"]
    assert client.get("/healthz").get_json()["status"] == "ok"
    assert client.get("/api/v1/health").get_json()["status"] == "ok"


def test_legacy_urls_redirect(client):
    assert client.get("/book").headers["Location"].endswith("/app")
    assert client.get("/conductor").headers["Location"].endswith("/validator")


def test_security_headers(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "default-src 'self'" in r.headers["Content-Security-Policy"] and r.headers["X-Frame-Options"] == "DENY"


def test_api_404_shape(client):
    r = client.get("/api/v1/nothing-here")
    assert r.status_code == 404 and err(r)["code"] == "not_found"


def test_rate_limit_on_login(app, tmp_path):
    from buspass import create_app

    limited = create_app(
        {
            **{k: app.config[k] for k in ("SECRET_KEY", "JWT_SECRET", "SQLALCHEMY_DATABASE_URI")},
            "TESTING": True,
            "RATELIMIT_ENABLED": True,
        }
    )
    c = limited.test_client()
    codes = [
        c.post("/api/v1/auth/login", json={"identifier": "x@example.test", "password": "y"}).status_code
        for _ in range(11)
    ]
    assert codes[:10] == [401] * 10 and codes[-1] == 429
    assert c.post("/api/v1/auth/login", json={}).get_json()["error"]["code"] == "rate_limited"


# ---------- end to end ----------


def test_e2e_signup_topup_buy_scan_history(client, validator_h):
    """The investor-demo path: new rider → top up by card → buy pass → conductor scans → trip in history."""
    code = client.post(
        "/api/v1/auth/register",
        json={"name": "Demo Rider", "phone": "01122334455", "password": "secret123", "language": "ar"},
    ).get_json()["dev_code"]
    tokens = client.post("/api/v1/auth/verify", json={"target": "01122334455", "code": code}).get_json()
    h = {"Authorization": f"Bearer {tokens['access_token']}"}
    pay = client.post(
        "/api/v1/payments/checkout",
        json={"purpose": "topup", "amount_cents": 20000, "idempotency_key": key()},
        headers=h,
    ).get_json()
    _complete_mock(client, pay["id"])
    p = client.post(
        "/api/v1/passes", json={"route_id": route("R3").id, "pass_type": "daily", "idempotency_key": key()}, headers=h
    ).get_json()
    pass_obj = db.session.get(Pass, p["id"])
    scan = client.post(
        "/api/v1/validator/scan", json={"token": token_for(pass_obj), "bus_id": bus_on("R3").id}, headers=validator_h
    ).get_json()
    assert scan["valid"] and scan["passenger"] == "Demo Rider"
    trips = client.get("/api/v1/me/trips", headers=h).get_json()["items"]
    assert trips[0]["route_code"] == "R3"
    notes = client.get("/api/v1/me/notifications", headers=h).get_json()["items"]
    assert any("اشتراك" in n["title"] for n in notes)  # Arabic notifications for an Arabic user
