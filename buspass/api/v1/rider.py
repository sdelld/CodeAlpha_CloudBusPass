"""Rider endpoints: profile, wallet, passes, routes, trips, notifications, support."""

from flask import current_app, request
from flask_smorest import Blueprint

from ... import repositories as repo
from ...errors import ValidationFailed
from ...extensions import db
from ...models import PartnerOffer, Route
from ...security import auth_required, current_user
from ...services import accounts, auth, catalog, passes, pricing, sponsors
from . import schemas as s

BEARER = [{"bearer": []}]
me = Blueprint("me", __name__, url_prefix="/api/v1/me", description="The logged-in rider")
catalog_blp = Blueprint("catalog", __name__, url_prefix="/api/v1", description="Routes, stops, schedules, live buses")
passes_blp = Blueprint("passes", __name__, url_prefix="/api/v1/passes", description="Buy and manage passes")


# ---------- me ----------


@me.route("", methods=["GET"])
@me.doc(security=BEARER)
@auth_required()
def get_me():
    return current_user().to_dict()


@me.route("", methods=["PATCH"])
@me.doc(security=BEARER)
@auth_required()
@me.arguments(s.ProfileUpdate)
def update_me(data):
    return accounts.update_profile(current_user(), **data).to_dict()


@me.route("/password", methods=["POST"])
@me.doc(security=BEARER)
@auth_required()
@me.arguments(s.PasswordChange)
def change_password(data):
    auth.change_password(current_user(), data["current_password"], data["new_password"])
    return {"ok": True}


@me.route("/wallet", methods=["GET"])
@me.doc(security=BEARER)
@auth_required()
def wallet():
    user = current_user()
    return {
        "balance_cents": user.balance_cents,
        "currency": current_app.config["CURRENCY"],
        "transactions": [t.to_dict() for t in repo.Wallet.history(user.id)],
        "qr": {
            "kind": "W",
            "id": str(user.id),
            "secret": user.wallet_qr_secret,
            "window_seconds": current_app.config["QR_WINDOW_SECONDS"],
        },
    }


@me.route("/wallet/rotate-key", methods=["POST"])
@me.doc(security=BEARER)
@auth_required()
def rotate_wallet_key():
    """Phone lost: invalidate pay-per-ride codes on the old device."""
    passes.rotate_wallet_secret(current_user())
    return {"ok": True}


@me.route("/trips", methods=["GET"])
@me.doc(security=BEARER)
@auth_required()
def trips():
    return {
        "items": [
            dict(
                r.to_dict(),
                route_code=r.route.code if r.route else None,
                route_name_en=r.route.name_en if r.route else None,
                route_name_ar=r.route.name_ar if r.route else None,
                bus_plate=r.bus.plate if r.bus else None,
            )
            for r in repo.Rides.of_user(current_user().id)
        ]
    }


@me.route("/receipts", methods=["GET"])
@me.doc(security=BEARER)
@auth_required()
def receipts():
    return {
        "items": [r.to_dict() for r in repo.Receipts.of_user(current_user().id)],
        "currency": current_app.config["CURRENCY"],
    }


@me.route("/notifications", methods=["GET"])
@me.doc(security=BEARER)
@auth_required()
def notifications():
    return accounts.notifications(current_user())


@me.route("/notifications/read", methods=["POST"])
@me.doc(security=BEARER)
@auth_required()
@me.arguments(s.NotificationIds)
def read_notifications(data):
    accounts.mark_read(current_user(), data.get("ids"))
    return {"ok": True}


@me.route("/verification", methods=["POST"])
@me.doc(security=BEARER)
@auth_required()
@me.arguments(s.VerificationForm, location="form")
def upload_verification(data):
    """Upload a student or senior ID (multipart field `file`, JPG/PNG/PDF up to 5 MB)."""
    f = request.files.get("file")
    if f is None:
        raise ValidationFailed("Choose a file to upload.", details={"field": "file"})
    return accounts.upload_verification(current_user(), data["kind"], f).to_dict(), 201


@me.route("/support", methods=["POST"])
@me.doc(security=BEARER)
@auth_required()
@me.arguments(s.SupportForm)
def support(data):
    return accounts.open_ticket(current_user(), data["category"], data["message"]).to_dict(), 201


@me.route("/favorites/<int:route_id>", methods=["PUT", "DELETE"])
@me.doc(security=BEARER)
@auth_required()
def favorite(route_id):
    catalog.set_favorite(current_user(), route_id, request.method == "PUT")
    return {"ok": True}


@me.route("/offers", methods=["GET"])
@me.doc(security=BEARER)
@auth_required()
def offers():
    return {"items": [o.to_dict() for o in db.session.query(PartnerOffer).filter_by(active=True).all()]}


# ---------- catalog ----------


def _optional_user():
    try:
        from ...security import _load_user_from_header

        return _load_user_from_header() if request.headers.get("Authorization") else None
    except Exception:
        return None


@catalog_blp.route("/routes", methods=["GET"])
def routes():
    return {"items": catalog.list_routes(_optional_user()), "currency": current_app.config["CURRENCY"]}


@catalog_blp.route("/routes/<int:route_id>", methods=["GET"])
def route(route_id):
    return catalog.route_detail(route_id, _optional_user())


@catalog_blp.route("/routes/<int:route_id>/live", methods=["GET"])
def live(route_id):
    """Live bus positions (simulated feed)."""
    return catalog.live_positions(route_id)


@catalog_blp.route("/pass-types", methods=["GET"])
def pass_types():
    return {"items": passes.pass_types(), "discounts": [d.to_dict() for d in repo.Discounts.all() if d.active]}


@catalog_blp.route("/health", methods=["GET"])
def health():
    db.session.execute(db.text("SELECT 1"))
    return {"status": "ok"}


# ---------- passes ----------


@passes_blp.route("/quote", methods=["GET"])
@passes_blp.arguments(s.QuoteArgs, location="query")
def quote(args):
    """Price breakdown incl. the rider's discount and an optional promo code."""
    user = _optional_user()
    q = pricing.quote(
        user, repo.get(Route, args["route_id"]), repo.PassTypes.by_code(args["pass_type"]), args.get("promo_code")
    )
    q.pop("promo", None)
    return {**q, "currency": current_app.config["CURRENCY"]}


@passes_blp.route("", methods=["GET"])
@passes_blp.doc(security=BEARER)
@auth_required()
def my_passes():
    return {"items": [passes.serialize(p) for p in repo.Passes.of_user(current_user().id)]}


@passes_blp.route("", methods=["POST"])
@passes_blp.doc(security=BEARER)
@auth_required()
@passes_blp.arguments(s.BuyPass)
def buy(data):
    """Buy a pass with wallet balance (for card, use POST /payments/checkout with purpose=pass)."""
    p = passes.buy_with_wallet(
        current_user(),
        data["route_id"],
        data["pass_type"],
        data.get("start_date"),
        data.get("promo_code"),
        data["idempotency_key"],
        data["auto_renew"],
    )
    return passes.serialize(p), 201


@passes_blp.route("/<pass_id>", methods=["GET"])
@passes_blp.doc(security=BEARER)
@auth_required()
def get_pass(pass_id):
    return passes.serialize(passes.get_owned(current_user(), pass_id))


@passes_blp.route("/<pass_id>", methods=["PATCH"])
@passes_blp.doc(security=BEARER)
@auth_required()
@passes_blp.arguments(s.PassUpdate)
def update_pass(data, pass_id):
    return passes.serialize(passes.set_auto_renew(current_user(), pass_id, data["auto_renew"]))


@passes_blp.route("/<pass_id>/rotate-key", methods=["POST"])
@passes_blp.doc(security=BEARER)
@auth_required()
def rotate_key(pass_id):
    """Report phone lost/stolen: the old device's QR codes stop working immediately."""
    return passes.serialize(passes.rotate_secret(current_user(), pass_id))


@passes_blp.route("/redeem", methods=["POST"])
@passes_blp.doc(security=BEARER)
@auth_required()
@passes_blp.arguments(s.Redeem)
def redeem(data):
    """Redeem a university/company invite code for a sponsored pass."""
    return passes.serialize(sponsors.redeem(current_user(), data["code"], data.get("start_date"))), 201
