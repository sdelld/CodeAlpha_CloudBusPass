"""Payments, validator, sponsor and admin endpoints."""

from flask import Response, current_app, request, send_file
from flask_smorest import Blueprint

from ... import repositories as repo
from ...errors import NotFound
from ...extensions import db, limiter
from ...models import Organization, ServiceAlert
from ...security import auth_required, current_user
from ...services import accounts, admin, analytics, catalog, payments, sponsors, validation
from . import schemas as s

BEARER = [{"bearer": []}]
pay = Blueprint("payments", __name__, url_prefix="/api/v1/payments", description="Checkout and webhooks")
val = Blueprint("validator", __name__, url_prefix="/api/v1/validator", description="Ticket validation")
spo = Blueprint("sponsor", __name__, url_prefix="/api/v1/sponsor", description="University / company sponsors")
adm = Blueprint("admin", __name__, url_prefix="/api/v1/admin", description="Operator dashboard")


# ---------- payments ----------


def _payment_out(p):
    return {**p.to_dict(), "checkout_url": p.meta.get("checkout_url"), "description": p.meta.get("description")}


@pay.route("/checkout", methods=["POST"])
@pay.doc(security=BEARER)
@auth_required()
@pay.arguments(s.Checkout)
def checkout(data):
    """Start a card payment (wallet top-up, pass, or sponsor seats). Redirect the user to `checkout_url`."""
    purpose, key = data.pop("purpose"), data.pop("idempotency_key")
    if data.get("start_date"):
        data["start_date"] = data["start_date"].isoformat()
    return _payment_out(payments.start_checkout(current_user(), purpose, key, **data)), 201


@pay.route("/<payment_id>", methods=["GET"])
@pay.doc(security=BEARER)
@auth_required()
def get_payment(payment_id):
    return _payment_out(payments.get_owned(current_user(), payment_id))


@pay.route("/webhooks/<provider>", methods=["POST"])
@limiter.exempt
def webhook(provider):
    """Provider → server notification. Signature-verified and processed exactly once per event id."""
    from ...payments import PROVIDERS

    if provider not in PROVIDERS:
        raise NotFound("Unknown provider.")
    return payments.handle_webhook(provider, request.get_data(), request.headers)


# ---------- validator ----------


@val.route("/buses", methods=["GET"])
@val.doc(security=BEARER)
@auth_required("validator", "admin")
def buses():
    return {
        "items": [
            dict(b.to_dict(), route_code=b.route.code if b.route else None)
            for b in repo.Buses.all()
            if b.status == "active"
        ]
    }


@val.route("/scan", methods=["POST"])
@val.doc(security=BEARER)
@limiter.limit("120 per minute")
@auth_required("validator", "admin")
@val.arguments(s.Scan)
def scan(data):
    """Validate one QR code on a bus."""
    return validation.validate(
        current_user(), data["token"], data["bus_id"], data.get("scanned_at"), data.get("client_scan_id")
    )


@val.route("/sync", methods=["POST"])
@val.doc(security=BEARER)
@limiter.limit("30 per minute")
@auth_required("validator", "admin")
@val.arguments(s.SyncBatch)
def sync(data):
    """Upload scans recorded while offline (idempotent by client_scan_id)."""
    return {"results": validation.sync_batch(current_user(), data["scans"])}


@val.route("/recent", methods=["GET"])
@val.doc(security=BEARER)
@auth_required("validator", "admin")
def recent():
    return {"items": validation.recent_for(current_user())}


# ---------- sponsor ----------


@spo.route("/dashboard", methods=["GET"])
@spo.doc(security=BEARER)
@auth_required("sponsor")
def sponsor_dashboard():
    return sponsors.dashboard(current_user())


# ---------- admin ----------


@adm.route("/overview", methods=["GET"])
@adm.doc(security=BEARER)
@auth_required("admin")
@adm.arguments(s.Days, location="query")
def overview(args):
    return {**analytics.overview(args["days"]), "currency": current_app.config["CURRENCY"]}


CRUD = {
    "routes": s.RouteIn,
    "stops": s.StopIn,
    "buses": s.BusIn,
    "pass_types": s.PassTypeIn,
    "promo_codes": s.PromoIn,
    "discounts": s.DiscountIn,
}


def _patch_schema(schema):
    """A named partial schema, so the OpenAPI spec gets one clean component per PATCH body."""

    def __init__(self, *args, **kwargs):
        schema.__init__(self, *args, partial=True, **kwargs)

    return type(schema.__name__.replace("In", "Patch"), (schema,), {"__init__": __init__})


def _register_crud(kind, schema):
    pk = "<code>" if kind == "discounts" else "<int:pk>"
    patch_schema = _patch_schema(schema)

    @adm.route(f"/{kind}", methods=["GET"], endpoint=f"list_{kind}")
    @adm.doc(security=BEARER)
    @auth_required("admin")
    def list_view():
        return {"items": admin.list_all(kind)}

    @adm.route(f"/{kind}", methods=["POST"], endpoint=f"create_{kind}")
    @adm.doc(security=BEARER)
    @adm.arguments(schema)
    @auth_required("admin")
    def create_view(data):
        return admin.serialize(kind, admin.create(current_user(), kind, data)), 201

    @adm.route(f"/{kind}/{pk}", methods=["PATCH"], endpoint=f"update_{kind}")
    @adm.doc(security=BEARER)
    @adm.arguments(patch_schema)
    @auth_required("admin")
    def update_view(data, **kw):
        key = kw.get("pk", kw.get("code"))
        return admin.serialize(kind, admin.update(current_user(), kind, key, data))

    @adm.route(f"/{kind}/{pk}", methods=["DELETE"], endpoint=f"delete_{kind}")
    @adm.doc(security=BEARER)
    @auth_required("admin")
    def delete_view(**kw):
        admin.delete(current_user(), kind, kw.get("pk", kw.get("code")))
        return {"ok": True}


for _kind, _schema in CRUD.items():
    _register_crud(_kind, _schema)


@adm.route("/users", methods=["GET"])
@adm.doc(security=BEARER)
@auth_required("admin")
@adm.arguments(s.UserSearch, location="query")
def users(args):
    return {"items": [u.to_dict() for u in repo.Users.search(**args)]}


@adm.route("/users/<int:user_id>", methods=["PATCH"])
@adm.doc(security=BEARER)
@auth_required("admin")
@adm.arguments(s.UserUpdate)
def update_user(data, user_id):
    user = None
    if "role" in data:
        user = accounts.set_role(current_user(), user_id, data["role"], data.get("organization_id"))
    if "status" in data:
        user = accounts.set_status(current_user(), user_id, data["status"], data.get("reason", ""))
    if user is None:
        raise NotFound("Nothing to update.")
    return user.to_dict()


@adm.route("/verifications", methods=["GET"])
@adm.doc(security=BEARER)
@auth_required("admin")
def verifications():
    return {"items": [d.to_dict() for d in repo.Verifications.pending()]}


@adm.route("/verifications/<int:doc_id>", methods=["POST"])
@adm.doc(security=BEARER)
@auth_required("admin")
@adm.arguments(s.Review)
def review(data, doc_id):
    return accounts.review_verification(current_user(), doc_id, data["approve"], data.get("note")).to_dict()


@adm.route("/verifications/<int:doc_id>/file", methods=["GET"])
@adm.doc(security=BEARER)
@auth_required("admin")
def verification_file(doc_id):
    path, doc = accounts.document_path(doc_id)
    return send_file(path, mimetype=doc.content_type, download_name=doc.original_name)


@adm.route("/payments", methods=["GET"])
@adm.doc(security=BEARER)
@auth_required("admin")
@adm.arguments(s.Paging, location="query")
def list_payments(args):
    return {
        "items": [
            dict(p.to_dict(), user_name=p.user.name, description=p.meta.get("description"))
            for p in repo.Payments.list(args.get("status"), args["limit"], args["offset"])
        ]
    }


@adm.route("/payments/<payment_id>/refund", methods=["POST"])
@adm.doc(security=BEARER)
@auth_required("admin")
@adm.arguments(s.RefundIn)
def refund_payment(data, payment_id):
    return payments.refund(current_user(), payment_id, data["target"], data["reason"]).to_dict()


@adm.route("/passes/<pass_id>/refund", methods=["POST"])
@adm.doc(security=BEARER)
@auth_required("admin")
@adm.arguments(s.RefundIn)
def refund_pass(data, pass_id):
    result = payments.refund_wallet_pass(current_user(), pass_id, data["reason"])
    return {"ok": True, "status": result.status}


@adm.route("/users/<int:user_id>/passes", methods=["GET"])
@adm.doc(security=BEARER)
@auth_required("admin")
def user_passes(user_id):
    from ...services import passes as passes_service

    return {"items": [passes_service.serialize(p, owner=False) for p in repo.Passes.of_user(user_id)]}


@adm.route("/audit", methods=["GET"])
@adm.doc(security=BEARER)
@auth_required("admin")
@adm.arguments(s.Paging, location="query")
def audit_log(args):
    return {"items": [a.to_dict() for a in repo.Audit.list(args["limit"], args["offset"], args.get("action"))]}


@adm.route("/export/<kind>.csv", methods=["GET"])
@adm.doc(security=BEARER)
@auth_required("admin")
def export(kind):
    if kind not in analytics.EXPORTS:
        raise NotFound("Unknown export.")
    from ...services import audit

    audit.record("export.downloaded", "export", kind)
    db.session.commit()
    return Response(
        analytics.export_csv(kind),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={kind}.csv"},
    )


@adm.route("/alerts", methods=["GET"])
@adm.doc(security=BEARER)
@auth_required("admin")
def alerts():
    return {
        "items": [
            a.to_dict() for a in db.session.query(ServiceAlert).order_by(ServiceAlert.created_at.desc()).limit(50)
        ]
    }


@adm.route("/alerts", methods=["POST"])
@adm.doc(security=BEARER)
@auth_required("admin")
@adm.arguments(s.AlertIn)
def post_alert(data):
    return catalog.post_alert(current_user(), **data).to_dict(), 201


@adm.route("/support", methods=["GET"])
@adm.doc(security=BEARER)
@auth_required("admin")
@adm.arguments(s.Paging, location="query")
def support_tickets(args):
    return {"items": [t.to_dict() for t in repo.Support.list(args.get("status"))]}


@adm.route("/support/<int:ticket_id>/close", methods=["POST"])
@adm.doc(security=BEARER)
@auth_required("admin")
def close_ticket(ticket_id):
    return accounts.close_ticket(current_user(), ticket_id).to_dict()


@adm.route("/organizations", methods=["GET"])
@adm.doc(security=BEARER)
@auth_required("admin")
def organizations():
    return {
        "items": [
            {"id": o.id, "name": o.name, "kind": o.kind, "email_domain": o.email_domain}
            for o in db.session.query(Organization).order_by(Organization.name)
        ]
    }


@adm.route("/organizations", methods=["POST"])
@adm.doc(security=BEARER)
@auth_required("admin")
@adm.arguments(s.OrganizationIn)
def create_organization(data):
    org = repo.add(Organization(**data))
    db.session.flush()
    from ...services import audit

    audit.record("organization.created", "organization", org.id, data)
    db.session.commit()
    return {"id": org.id, **data}, 201
