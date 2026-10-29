"""Generic, audited create/update/delete for operator-managed reference data."""

from sqlalchemy.exc import IntegrityError

from .. import repositories as repo
from ..errors import Conflict, NotFound
from ..extensions import db
from ..models import Bus, Departure, DiscountRule, PassType, PromoCode, Route, RouteStop, Stop
from . import audit

MODELS = {
    "routes": Route,
    "stops": Stop,
    "buses": Bus,
    "pass_types": PassType,
    "promo_codes": PromoCode,
    "discounts": DiscountRule,
}


def create(admin, kind, data):
    model = MODELS[kind]
    obj = model(**{k: v for k, v in data.items() if k not in ("stops", "departures")})
    repo.add(obj)
    if kind == "routes":
        _set_route_children(obj, data)
    _commit(f"{kind}.created", obj, data, admin)
    return obj


def update(admin, kind, pk, data):
    obj = repo.get(MODELS[kind], pk)
    if obj is None:
        raise NotFound("Not found.")
    before = {k: getattr(obj, k) for k in data if hasattr(obj, k) and k not in ("stops", "departures")}
    for k, v in data.items():
        if k in ("stops", "departures", "id") or (kind == "discounts" and k == "code"):
            continue  # children are handled below; primary keys never change
        setattr(obj, k, v)
    if kind == "routes":
        _set_route_children(obj, data)
    _commit(f"{kind}.updated", obj, {"before": _jsonable(before), "after": _jsonable(data)}, admin)
    return obj


def delete(admin, kind, pk):
    obj = repo.get(MODELS[kind], pk)
    if obj is None:
        raise NotFound("Not found.")
    if hasattr(obj, "active"):
        obj.active = False  # soft delete keeps history (passes, rides) intact
    elif kind == "buses":
        obj.status = "maintenance"
    else:
        db.session.delete(obj)
    _commit(f"{kind}.deactivated", obj, None, admin)


def _set_route_children(route, data):
    if "stops" in data:
        route.stops = [
            RouteStop(stop_id=s["stop_id"], seq=i, minutes_from_start=s["minutes_from_start"])
            for i, s in enumerate(data["stops"])
        ]
    if "departures" in data:
        route.departures = [Departure(time=t) for t in sorted(set(data["departures"]))]


def _commit(action, obj, details, admin):
    try:
        db.session.flush()
    except IntegrityError:
        db.session.rollback()
        raise Conflict("That conflicts with an existing record (duplicate code/plate?).") from None
    pk = getattr(obj, "id", None) or getattr(obj, "code", None)
    audit.record(action, action.split(".")[0], pk, _jsonable(details), actor=admin)
    db.session.commit()


def _jsonable(d):
    if d is None:
        return None
    return {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in d.items()}


def serialize(kind, obj):
    if kind == "routes":
        return obj.to_dict(detail=True)
    return obj.to_dict()


def list_all(kind):
    model = MODELS[kind]
    order = {
        "routes": Route.code,
        "stops": Stop.name_en,
        "buses": Bus.plate,
        "pass_types": PassType.sort,
        "promo_codes": PromoCode.created_at.desc(),
        "discounts": DiscountRule.code,
    }[kind]
    return [serialize(kind, o) for o in db.session.query(model).order_by(order).all()]
