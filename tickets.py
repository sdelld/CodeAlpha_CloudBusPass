"""Tamper-proof ticket codes.

The QR code holds "BP1.<ticket id>.<HMAC signature>". The signature covers every field that
matters (owner, route, dates, price), keyed with the server secret, so a forged or edited
ticket fails verification even if someone copies the format.
"""
import hashlib
import hmac

PREFIX = "BP1"


def sign(ticket, secret):
    payload = "|".join(
        str(v)
        for v in (
            ticket.id,
            ticket.user_id,
            ticket.route_id,
            ticket.pass_type,
            ticket.price_cents,
            ticket.valid_from.isoformat(),
            ticket.valid_until.isoformat(),
        )
    )
    return hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()


def encode(ticket):
    return f"{PREFIX}.{ticket.id}.{ticket.signature}"


def decode(code):
    """Return (ticket_id, signature) or None if the code is malformed."""
    parts = (code or "").strip().split(".")
    if len(parts) != 3 or parts[0] != PREFIX or not parts[1].isalnum() or not parts[2].isalnum():
        return None
    return parts[1], parts[2]


def verify(ticket, signature, secret):
    expected = sign(ticket, secret)
    # Both checks: the presented code matches the stored one, and the stored row was not edited.
    return hmac.compare_digest(signature, ticket.signature) and hmac.compare_digest(expected, ticket.signature)
