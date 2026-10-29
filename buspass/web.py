"""HTML pages: landing site, the three web apps (rider, validator, admin + sponsor) and the test checkout."""

from flask import Blueprint, abort, current_app, jsonify, redirect, render_template, request, send_from_directory

from . import repositories as repo
from .extensions import db
from .models import Payment
from .payments import get_provider
from .services import payments
from .timeutil import format_money

bp = Blueprint("web", __name__)


def _lang():
    lang = request.args.get("lang") or request.cookies.get("cb_lang") or current_app.config["DEFAULT_LANGUAGE"]
    return lang if lang in ("en", "ar") else "en"


@bp.get("/")
def landing():
    lang = _lang()
    routes = repo.Routes.all()
    resp = current_app.make_response(
        render_template(
            "landing.html",
            lang=lang,
            routes=routes,
            pass_types=repo.PassTypes.all(),
            currency=current_app.config["CURRENCY"],
            min_fare=min((r.base_fare_cents for r in routes), default=1000),
        )
    )
    if request.args.get("lang") in ("en", "ar"):
        resp.set_cookie("cb_lang", lang, max_age=365 * 86400, samesite="Lax")
    return resp


@bp.get("/app")
def rider_app():
    return render_template("spa.html", app="rider", title="CloudBus Pass")


@bp.get("/app/sw.js")
def service_worker():
    # Served from /app/ so its scope covers the rider app; caches the shell for offline passes.
    resp = send_from_directory(current_app.static_folder, "js/sw.js", mimetype="application/javascript")
    resp.headers["Cache-Control"] = "no-cache"
    resp.headers["Service-Worker-Allowed"] = "/app"
    return resp


@bp.get("/validator")
def validator_app():
    return render_template("spa.html", app="validator", title="CloudBus Validator")


@bp.get("/admin")
def admin_app():
    return render_template("spa.html", app="admin", title="CloudBus Admin")


@bp.get("/sponsor")
def sponsor_app():
    return render_template("spa.html", app="sponsor", title="CloudBus for Organisations")


@bp.route("/pay/mock/<payment_id>", methods=["GET", "POST"])
def mock_checkout(payment_id):
    """Stand-in for a hosted payment page. Only available with the mock provider."""
    payment = repo.get(Payment, payment_id)
    if payment is None or payment.provider != "mock":
        abort(404)
    if request.method == "POST" and payment.status == "pending":
        outcome = "succeeded" if request.form.get("outcome") == "pay" else "failed"
        provider = get_provider("mock")
        body, signature = provider.build_event(payment, outcome)
        # Exactly what a real gateway does: a signed server-to-server webhook.
        payments.handle_webhook("mock", body, {"X-Mock-Signature": signature})
        db.session.refresh(payment)
        return redirect("/sponsor" if payment.purpose == "sponsor_seats" else f"/app#/payment/{payment.id}")
    return render_template(
        "mock_checkout.html", payment=payment, amount=format_money(payment.amount_cents, payment.currency)
    )


@bp.get("/healthz")
def healthz():
    try:
        db.session.execute(db.text("SELECT 1"))
    except Exception:
        return jsonify(status="db-unavailable"), 503
    import os

    return jsonify(status="ok", instance=os.environ.get("HOSTNAME", "local"))


# Old v0.1 URLs keep working.
@bp.get("/login")
@bp.get("/register")
@bp.get("/book")
@bp.get("/tickets")
def legacy_rider():
    return redirect("/app", code=301)


@bp.get("/conductor")
def legacy_conductor():
    return redirect("/validator", code=301)
