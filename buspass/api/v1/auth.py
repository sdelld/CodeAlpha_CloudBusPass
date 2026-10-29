from flask import current_app, jsonify, request
from flask_smorest import Blueprint

from ...errors import Unauthorized
from ...extensions import limiter
from ...services import auth
from . import schemas as s

blp = Blueprint("auth", __name__, url_prefix="/api/v1/auth", description="Sign up, OTP, login and tokens")
REFRESH_COOKIE = "cb_refresh"


def _with_cookie(tokens):
    """Refresh token goes in an httpOnly cookie (browsers) and in the body (mobile/API clients)."""
    resp = jsonify(tokens)
    resp.set_cookie(
        REFRESH_COOKIE,
        tokens["refresh_token"],
        httponly=True,
        samesite="Strict",
        secure=current_app.config["COOKIE_SECURE"],
        path="/api/v1/auth",
        max_age=int(current_app.config["REFRESH_TOKEN_TTL"].total_seconds()),
    )
    return resp


@blp.route("/register", methods=["POST"])
@limiter.limit("5 per minute")
@blp.arguments(s.Register)
@blp.response(201)
def register(data):
    """Create an account; a 6-digit code is sent to the email/phone."""
    return auth.register(data["name"], data["password"], data.get("email"), data.get("phone"), data["language"]), 201


@blp.route("/verify", methods=["POST"])
@limiter.limit("10 per minute")
@blp.arguments(s.TargetCode)
def verify(data):
    """Confirm sign-up with the code; returns tokens."""
    return _with_cookie(auth.verify_signup(data["target"], data["code"]))


@blp.route("/otp/request", methods=["POST"])
@limiter.limit("5 per minute")
@blp.arguments(s.Target)
def otp_request(data):
    """Send a one-time login code."""
    return auth.request_login_otp(data["target"])


@blp.route("/otp/login", methods=["POST"])
@limiter.limit("10 per minute")
@blp.arguments(s.TargetCode)
def otp_login(data):
    """Log in with a one-time code."""
    return _with_cookie(auth.login_with_otp(data["target"], data["code"]))


@blp.route("/login", methods=["POST"])
@limiter.limit("10 per minute")
@blp.arguments(s.Login)
def login(data):
    """Log in with email/phone and password."""
    return _with_cookie(auth.login_with_password(data["identifier"], data["password"]))


@blp.route("/refresh", methods=["POST"])
@limiter.limit("30 per minute")
@blp.arguments(s.RefreshBody)
def refresh(data):
    """Exchange a refresh token for a new access token (the refresh token is rotated)."""
    token = data.get("refresh_token") or request.cookies.get(REFRESH_COOKIE)
    if not token:
        raise Unauthorized("Log in to continue.", code="no_session")
    return _with_cookie(auth.refresh(token))


@blp.route("/logout", methods=["POST"])
@blp.arguments(s.RefreshBody)
def logout(data):
    auth.logout(data.get("refresh_token") or request.cookies.get(REFRESH_COOKIE, ""))
    resp = jsonify(ok=True)
    resp.delete_cookie(REFRESH_COOKIE, path="/api/v1/auth")
    return resp
