"""Local-time helpers. Validity dates follow the operator's timezone (Africa/Cairo by default), not UTC."""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from flask import current_app


def tz():
    return ZoneInfo(current_app.config["TIMEZONE"])


def local_now():
    return datetime.now(UTC).astimezone(tz())


def local_today():
    return local_now().date()


def to_local(naive_utc):
    return naive_utc.replace(tzinfo=UTC).astimezone(tz())


def format_money(cents, currency):
    return f"{cents / 100:,.2f} {currency}"
