"""Browser end-to-end tests (Playwright). They drive the real UI against a live server.

    pip install -r requirements-dev.txt && python -m playwright install chromium
    python -m pytest tests/e2e -v

Skipped automatically when Playwright isn't installed.
"""

import threading
import uuid

import pytest
from werkzeug.serving import make_server

pw = pytest.importorskip("playwright.sync_api")

from buspass import create_app  # noqa: E402
from buspass.extensions import db  # noqa: E402
from buspass.seed import DEMO_PASSWORD, seed_demo  # noqa: E402


@pytest.fixture(scope="module")
def base_url(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("e2e")
    app = create_app(
        {
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp / 'e2e.db'}",
            "SECRET_KEY": "e2e-secret-0123456789abcdef0123456789",
            "RATELIMIT_ENABLED": False,
            "DEMO_MODE": True,
            "PAYMENT_PROVIDER": "mock",
            "UPLOAD_DIR": str(tmp / "uploads"),
        }
    )
    with app.app_context():
        db.create_all()
        seed_demo(n_riders=4, days=3)
    server = make_server("127.0.0.1", 0, app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


@pytest.fixture()
def page(base_url):
    with pw.sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(viewport={"width": 390, "height": 844}, base_url=base_url)
        pg = context.new_page()
        errors = []
        pg.on("pageerror", lambda e: errors.append(str(e)))
        yield pg
        browser.close()
        assert not errors, f"JavaScript errors: {errors}"


def test_signup_topup_buy_and_scan(page, base_url):
    """Critical path: new rider signs up -> tops up by card -> buys a pass -> conductor scans the live QR."""
    email = f"e2e-{uuid.uuid4().hex[:6]}@example.test"
    page.goto("/app#/register")
    page.fill("input[name=name]", "E2E Rider")
    page.fill("input[name=email]", email)
    page.fill("input[name=password]", "secret123")
    page.click("button[type=submit]")
    code = page.locator(".alert.info").inner_text().split()[-1]  # demo mode shows the OTP
    page.fill("input[name=code]", code)
    page.click("button[type=submit]")
    page.wait_for_url("**/app#/")
    page.get_by_text("No active pass").wait_for()

    # Top up 100 EGP through the (test) hosted checkout.
    page.goto("/app#/wallet/topup")
    page.get_by_role("button", name="100.00 EGP").click()
    page.click("button[type=submit]")
    page.wait_for_url("**/pay/mock/**")
    page.get_by_role("button", name="Pay 100.00 EGP").click()
    page.get_by_text("Payment successful").wait_for()

    # Buy a day pass on R5 with the wallet.
    page.goto("/app#/buy")
    page.select_option("select[name=route_id]", label="R5 · Maadi – Ramses")
    page.get_by_role("button", name="Day pass").click()
    pay = page.get_by_role("button", name="Pay 25.00 EGP")
    pay.wait_for()
    pay.click()
    page.get_by_text("Pass ready!").wait_for()

    # Pass tab: live QR code, ≤ 3 taps from the home screen.
    page.goto("/app#/")
    page.get_by_role("link", name="Pass").click()
    token = page.locator(".qr-wrap .mono").first.inner_text()
    assert token.startswith("CB1.P.")

    # Conductor validates it through the API.
    api = page.request
    login = api.post(
        f"{base_url}/api/v1/auth/login", data={"identifier": "validator@cloudbus.test", "password": DEMO_PASSWORD}
    ).json()
    headers = {"Authorization": f"Bearer {login['access_token']}"}
    bus = next(
        b
        for b in api.get(f"{base_url}/api/v1/validator/buses", headers=headers).json()["items"]
        if b["route_code"] == "R5"
    )
    result = api.post(
        f"{base_url}/api/v1/validator/scan", data={"token": token, "bus_id": bus["id"]}, headers=headers
    ).json()
    assert result["result"] == "valid" and result["passenger"] == "E2E Rider"


def test_arabic_rtl_and_dark_mode(page):
    page.goto("/app#/login")
    page.fill("input[name=identifier]", "rider@cloudbus.test")
    page.fill("input[name=password]", DEMO_PASSWORD)
    page.click("button[type=submit]")
    page.wait_for_url("**/app#/")
    page.goto("/app#/profile")
    page.get_by_role("button", name="العربية").click()
    page.get_by_role("button", name="داكن").click()
    assert page.evaluate("document.documentElement.dir") == "rtl"
    assert page.evaluate("document.documentElement.dataset.theme") == "dark"
    page.goto("/app#/routes")
    page.get_by_text("رمسيس – جامعة القاهرة").wait_for()
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")


def test_validator_shows_fraud_for_screenshot(page, base_url):
    page.goto("/validator")
    page.fill("input[name=identifier]", "validator@cloudbus.test")
    page.fill("input[name=password]", DEMO_PASSWORD)
    page.click("button[type=submit]")
    page.locator(".list li").first.click()
    page.fill("input[name=token]", "CB1.P." + "a" * 32 + ".1." + "0" * 20)
    page.get_by_role("button", name="Validate").click()
    page.locator(".scan-result.fraud").wait_for()


def test_admin_dashboard_renders_charts(page):
    page.goto("/admin")
    page.fill("input[name=identifier]", "admin@cloudbus.test")
    page.fill("input[name=password]", DEMO_PASSWORD)
    page.click("button[type=submit]")
    page.locator(".kpis .card").first.wait_for()
    assert page.locator("canvas").count() == 4
    page.goto("/admin#/users")
    page.locator("table tbody tr").first.wait_for()
