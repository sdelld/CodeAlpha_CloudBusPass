"""Server-side fare rules. Prices are always computed here, never taken from the client."""
from datetime import timedelta

# multiplier is (numerator, denominator) so all money math stays in integer cents.
PASS_TYPES = {
    "single": {"label": "Single ride", "multiplier": (1, 1), "days": 1, "single_use": True},
    "day": {"label": "Day pass", "multiplier": (5, 2), "days": 1, "single_use": False},
    "weekly": {"label": "Weekly pass", "multiplier": (12, 1), "days": 7, "single_use": False},
    "monthly": {"label": "Monthly pass", "multiplier": (40, 1), "days": 30, "single_use": False},
}


def quote_cents(base_fare_cents, pass_type):
    num, den = PASS_TYPES[pass_type]["multiplier"]
    return base_fare_cents * num // den


def validity(pass_type, start):
    return start, start + timedelta(days=PASS_TYPES[pass_type]["days"] - 1)


def format_money(cents, currency):
    return f"{cents // 100}.{cents % 100:02d} {currency}"
