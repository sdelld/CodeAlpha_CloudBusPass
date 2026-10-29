"""University / company sponsorship: buy seats in bulk, members redeem an invite code for a free pass."""

import secrets

from .. import repositories as repo
from ..errors import Conflict, Forbidden, NotFound, ValidationFailed
from ..extensions import db
from ..models import SponsorBlock
from . import audit, passes, pricing

SPONSOR_MULTIPLIER = 30  # seat price = 30 x base fare (vs 40 x for a rider monthly pass)
MIN_SEATS, MAX_SEATS = 10, 5000


def _org_of(user):
    if user.role != "sponsor" or not user.organization_id:
        raise Forbidden("Only sponsor accounts linked to an organisation can do this.")
    return user.organization


def prepare_purchase(user, route_id=None, pass_type="monthly", seats=None, **_):
    org = _org_of(user)
    route, pass_type_obj = passes.load_product(route_id, pass_type)
    if seats is None or not MIN_SEATS <= seats <= MAX_SEATS:
        raise ValidationFailed(f"Seats must be between {MIN_SEATS} and {MAX_SEATS}.", details={"field": "seats"})
    unit = (
        pricing.base_price(route, pass_type_obj) * SPONSOR_MULTIPLIER // 40
        if pass_type == "monthly"
        else pricing.base_price(route, pass_type_obj)
    )
    meta = {"organization_id": org.id, "route_id": route.id, "pass_type": pass_type, "seats": seats, "unit_cents": unit}
    return meta, unit * seats, f"{seats} sponsored {pass_type_obj.name_en}s — {route.code} for {org.name}"


def fulfill_purchase(payment):
    m = payment.meta
    route, pass_type = passes.load_product(m["route_id"], m["pass_type"])
    block = repo.add(
        SponsorBlock(
            organization_id=m["organization_id"],
            route_id=route.id,
            pass_type_id=pass_type.id,
            seats_total=m["seats"],
            invite_code=_new_code(),
            status="active",
            payment_id=payment.id,
        )
    )
    db.session.flush()
    from . import wallet

    wallet.create_receipt(
        payment.user_id,
        f"{m['seats']} sponsored seats — {route.code}",
        payment.amount_cents,
        "card",
        payment_id=payment.id,
    )
    return block


def _new_code():
    return secrets.token_urlsafe(6).replace("-", "").replace("_", "").upper()[:8] or "CB" + secrets.token_hex(3).upper()


def redeem(user, code, start_date=None):
    block = repo.Sponsors.block_by_code(code.strip())
    if block is None or block.status != "active":
        raise NotFound("This invite code doesn't exist or is no longer active.")
    domain = block.organization.email_domain
    if domain and not (user.email or "").endswith("@" + domain.lower()):
        raise Forbidden(
            f"This code is only for {block.organization.name} members (@{domain} email).", code="domain_mismatch"
        )
    if block.seats_used >= block.seats_total:
        raise Conflict("All sponsored seats have been used.", code="no_seats")
    if repo.Passes.by_idempotency(user.id, f"sponsor:{block.id}"):
        raise Conflict("You already redeemed this code.", code="already_redeemed")
    start = passes.parse_start(start_date)
    p = passes.create_pass(
        user,
        block.route,
        block.pass_type,
        start,
        0,
        0,
        source="sponsor",
        idempotency_key=f"sponsor:{block.id}",
        sponsor_block_id=block.id,
    )
    block.seats_used += 1
    if not user.organization_id:
        user.organization_id = block.organization_id
    audit.record("sponsor.redeemed", "sponsor_block", block.id, actor=user)
    db.session.commit()
    return p


def dashboard(user):
    org = _org_of(user)
    blocks = repo.Sponsors.blocks_of(org.id)
    from ..models import Pass, Ride

    block_ids = [b.id for b in blocks]
    rides = 0
    if block_ids:
        rides = (
            db.session.query(Ride)
            .join(Pass, Ride.pass_id == Pass.id)
            .filter(Pass.sponsor_block_id.in_(block_ids), Ride.result == "valid")
            .count()
        )
    return {
        "organization": {"id": org.id, "name": org.name, "kind": org.kind, "email_domain": org.email_domain},
        "blocks": [b.to_dict() for b in blocks],
        "totals": {
            "seats_total": sum(b.seats_total for b in blocks if b.status == "active"),
            "seats_used": sum(b.seats_used for b in blocks if b.status == "active"),
            "rides": rides,
        },
    }
