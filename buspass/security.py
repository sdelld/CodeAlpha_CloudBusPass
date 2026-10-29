"""Password hashing, JWT access/refresh tokens and role-based access control."""

from datetime import UTC, datetime
from functools import wraps

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from flask import current_app, g, request

from .errors import Forbidden, Unauthorized
from .extensions import db
from .models import User

_hasher = PasswordHasher()


def hash_password(password):
    return _hasher.hash(password)


def verify_password(password_hash, password):
    if not password_hash:
        return False
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def _now():
    return datetime.now(UTC)


def make_access_token(user):
    cfg = current_app.config
    payload = {
        "sub": str(user.id),
        "role": user.role,
        "type": "access",
        "iat": _now(),
        "exp": _now() + cfg["ACCESS_TOKEN_TTL"],
    }
    return jwt.encode(payload, cfg["JWT_SECRET"], algorithm="HS256")


def make_refresh_token(user_id, jti):
    cfg = current_app.config
    payload = {
        "sub": str(user_id),
        "jti": jti,
        "type": "refresh",
        "iat": _now(),
        "exp": _now() + cfg["REFRESH_TOKEN_TTL"],
    }
    return jwt.encode(payload, cfg["JWT_SECRET"], algorithm="HS256")


def decode_token(token, expected_type):
    try:
        payload = jwt.decode(token, current_app.config["JWT_SECRET"], algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        raise Unauthorized("Your session has expired.", code="token_expired") from None
    except jwt.InvalidTokenError:
        raise Unauthorized("Invalid authentication token.", code="token_invalid") from None
    if payload.get("type") != expected_type:
        raise Unauthorized("Wrong token type.", code="token_invalid")
    return payload


def current_user():
    return g.get("user")


def _load_user_from_header():
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        raise Unauthorized("Log in to continue.")
    payload = decode_token(header[7:], "access")
    user = db.session.get(User, int(payload["sub"]))
    if user is None:
        raise Unauthorized("Account not found.")
    if user.status == "suspended":
        raise Forbidden("This account is suspended. Contact support.", code="account_suspended")
    g.user = user
    return user


def auth_required(*roles):
    """@auth_required() any logged-in user; @auth_required("admin") only admins."""

    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            user = _load_user_from_header()
            if roles and user.role not in roles:
                raise Forbidden("You don't have permission to do this.")
            return view(*args, **kwargs)

        return wrapped

    return decorator


def client_ip():
    forwarded = request.headers.get("X-Forwarded-For", "")
    return forwarded.split(",")[0].strip() or request.remote_addr
