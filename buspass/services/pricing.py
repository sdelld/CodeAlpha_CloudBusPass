"""Server-side price calculation. Prices are never accepted from the client."""

from .. import repositories as repo
from ..errors import NotFound, ValidationFailed
from ..models import utcnow


def base_price(route, pass_type):
    return route.base_fare_cents * pass_type.multiplier_num // pass_type.multiplier_den


def quote(user, route, pass_type, promo_code=None, lock_promo=False):
    """Return a price breakdown. Order: base -> rider discount (student/senior) -> promo code."""
    if route is None or not route.active:
        raise NotFound("Route not found.")
    if pass_type is None or not pass_type.active:
        raise NotFound("Pass type not found.")
    base = base_price(route, pass_type)
    lines = [{"label": "base", "amount_cents": base}]

    rider_discount = 0
    if pass_type.discountable and user and user.discount_status == "approved" and user.discount_type != "none":
        rule = repo.Discounts.rule(user.discount_type)
        if rule and rule.active:
            rider_discount = base * rule.percent // 100
            lines.append({"label": f"{rule.code}_discount", "percent": rule.percent, "amount_cents": -rider_discount})

    subtotal = base - rider_discount
    promo_discount, promo = 0, None
    if promo_code:
        promo = check_promo(promo_code)
        promo_discount = min(subtotal, subtotal * promo.value // 100 if promo.kind == "percent" else promo.value)
        lines.append({"label": "promo", "code": promo.code, "amount_cents": -promo_discount})

    total = subtotal - promo_discount
    return {
        "route_id": route.id,
        "pass_type": pass_type.code,
        "base_cents": base,
        "discount_cents": rider_discount + promo_discount,
        "total_cents": total,
        "lines": lines,
        "promo": promo if lock_promo else None,
    }


def check_promo(code):
    promo = repo.Discounts.promo(code.strip())
    if promo is None or not promo.active:
        raise ValidationFailed("This promo code doesn't exist.", code="promo_invalid", details={"field": "promo_code"})
    if promo.expires_at and promo.expires_at < utcnow():
        raise ValidationFailed("This promo code has expired.", code="promo_expired", details={"field": "promo_code"})
    if promo.max_uses is not None and promo.used_count >= promo.max_uses:
        raise ValidationFailed(
            "This promo code has been fully used.", code="promo_used_up", details={"field": "promo_code"}
        )
    return promo
