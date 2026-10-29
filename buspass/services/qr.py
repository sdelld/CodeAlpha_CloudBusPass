"""Rotating QR tokens.

Token: ``CB1.<kind>.<id>.<window>.<sig>``
  kind   P = pass, W = pay-per-ride wallet
  window floor(unix_time / 30): the code changes every 30 seconds
  sig    first 20 hex chars of HMAC-SHA256(key=<per-pass secret>, "CB1.<kind>.<id>.<window>")

The rider app receives the per-pass secret once and computes codes itself (Web Crypto), so the pass
keeps working offline. A screenshot stops working within ~1 minute, and replaying a code that is older
than the last accepted one is rejected as fraud.
"""

import hashlib
import hmac
import re
import time

from flask import current_app

PREFIX = "CB1"
SIG_LEN = 20
_TOKEN = re.compile(r"^CB1\.([PW])\.([0-9a-f]{1,32})\.(\d{1,12})\.([0-9a-f]{20})$")


def current_window(now=None):
    return int((now if now is not None else time.time()) // current_app.config["QR_WINDOW_SECONDS"])


def signature(secret, kind, ident, window):
    msg = f"{PREFIX}.{kind}.{ident}.{window}".encode()
    return hmac.new(secret.encode(), msg, hashlib.sha256).hexdigest()[:SIG_LEN]


def make_token(secret, kind, ident, window=None):
    window = current_window() if window is None else window
    return f"{PREFIX}.{kind}.{ident}.{window}.{signature(secret, kind, ident, window)}"


def parse(token):
    m = _TOKEN.match((token or "").strip())
    if not m:
        return None
    kind, ident, window, sig = m.groups()
    return {"kind": kind, "id": ident, "window": int(window), "sig": sig}


def signature_ok(secret, parsed):
    return hmac.compare_digest(parsed["sig"], signature(secret, parsed["kind"], parsed["id"], parsed["window"]))


def window_fresh(window, reference_window):
    return abs(reference_window - window) <= current_app.config["QR_ALLOWED_DRIFT_WINDOWS"]
