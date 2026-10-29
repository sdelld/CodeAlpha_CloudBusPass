"""Routes, stops, schedules, favourites, service alerts and the (simulated) live bus feed."""

from datetime import datetime

from .. import repositories as repo
from ..errors import NotFound
from ..extensions import db
from ..models import FavoriteRoute, Route, ServiceAlert
from ..timeutil import local_now
from . import audit, notify


def list_routes(user=None):
    favorites = repo.Routes.favorites_of(user.id) if user else set()
    out = []
    for r in repo.Routes.all():
        d = r.to_dict()
        d["favorite"] = r.id in favorites
        d["stops_count"] = len(r.stops)
        d["origin_en"], d["origin_ar"] = (r.stops[0].stop.name_en, r.stops[0].stop.name_ar) if r.stops else ("", "")
        d["destination_en"], d["destination_ar"] = (
            (r.stops[-1].stop.name_en, r.stops[-1].stop.name_ar) if r.stops else ("", "")
        )
        d["next_departures"] = next_departures(r, 3)
        out.append(d)
    return out


def route_detail(route_id, user=None):
    r = repo.get(Route, route_id)
    if r is None or not r.active:
        raise NotFound("Route not found.")
    d = r.to_dict(detail=True)
    d["favorite"] = bool(user) and r.id in repo.Routes.favorites_of(user.id)
    d["next_departures"] = next_departures(r, 5)
    d["alerts"] = [
        a.to_dict()
        for a in db.session.query(ServiceAlert)
        .filter_by(route_id=r.id)
        .order_by(ServiceAlert.created_at.desc())
        .limit(3)
    ]
    return d


def next_departures(route, n):
    now = local_now().strftime("%H:%M")
    times = [d.time for d in route.departures]
    upcoming = [t for t in times if t >= now]
    return (upcoming + times)[:n] if times else []


def live_positions(route_id, now=None):
    """Simulated GPS: each active bus loops the route; positions are deterministic from the clock.

    Replace with a GTFS-Realtime / telematics feed by implementing the same return shape.
    """
    r = repo.get(Route, route_id)
    if r is None:
        raise NotFound("Route not found.")
    stops = r.stops
    if len(stops) < 2:
        return {"route_id": r.id, "buses": [], "simulated": True}
    trip_minutes = stops[-1].minutes_from_start
    now = now or local_now()
    minute_of_day = now.hour * 60 + now.minute + now.second / 60
    buses = repo.Buses.on_route(r.id)
    out = []
    for i, bus in enumerate(buses):
        offset = (minute_of_day + i * trip_minutes / max(len(buses), 1)) % (2 * trip_minutes)
        outbound = offset < trip_minutes
        t = offset if outbound else 2 * trip_minutes - offset
        seg = next(k for k in range(len(stops) - 1) if stops[k + 1].minutes_from_start >= t)
        a, b = stops[seg], stops[seg + 1]
        span = max(b.minutes_from_start - a.minutes_from_start, 1)
        frac = (t - a.minutes_from_start) / span
        nxt = b if outbound else a
        eta = (b.minutes_from_start - t) if outbound else (t - a.minutes_from_start)
        out.append(
            {
                "bus_id": bus.id,
                "plate": bus.plate,
                "direction": "outbound" if outbound else "inbound",
                "lat": a.stop.lat + (b.stop.lat - a.stop.lat) * frac,
                "lng": a.stop.lng + (b.stop.lng - a.stop.lng) * frac,
                "progress": round(t / trip_minutes, 4),
                "next_stop_id": nxt.stop.id,
                "next_stop_en": nxt.stop.name_en,
                "next_stop_ar": nxt.stop.name_ar,
                "eta_minutes": max(1, round(eta)),
                "occupancy": ["low", "medium", "high"][(bus.id + now.hour) % 3],
            }
        )
    return {"route_id": r.id, "buses": out, "simulated": True, "updated_at": datetime.now().isoformat()}


def set_favorite(user, route_id, favorite):
    if repo.get(Route, route_id) is None:
        raise NotFound("Route not found.")
    existing = db.session.get(FavoriteRoute, (user.id, route_id))
    if favorite and not existing:
        repo.add(FavoriteRoute(user_id=user.id, route_id=route_id))
    elif not favorite and existing:
        db.session.delete(existing)
    db.session.commit()


def post_alert(admin, route_id, severity, message_en, message_ar):
    r = repo.get(Route, route_id)
    if r is None:
        raise NotFound("Route not found.")
    alert = repo.add(
        ServiceAlert(
            route_id=r.id, severity=severity, message_en=message_en, message_ar=message_ar, created_by=admin.id
        )
    )
    from ..models import User

    for uid in repo.Routes.users_following(r.id):
        notify.notify(repo.get(User, uid), "delay", "delay", route=r.code, message={"en": message_en, "ar": message_ar})
    audit.record("alert.posted", "route", r.id, {"severity": severity, "message": message_en}, actor=admin)
    db.session.commit()
    return alert
