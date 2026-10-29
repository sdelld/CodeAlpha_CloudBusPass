"""Sign-up, OTP verification, password/OTP login, refresh-token rotation, logout."""

import hashlib
import hmac
import secrets
from datetime import timedelta

from flask import current_app
from sqlalchemy.exc import IntegrityError

from .. import repositories as repo
from ..errors import Conflict, Forbidden, Unauthorized, ValidationFailed
from ..extensions import db
from ..models import OtpCode, RefreshToken, User, new_id, utcnow
from ..security import decode_token, hash_password, make_access_token, make_refresh_token, verify_password
from . import audit, notify

OTP_TTL = timedelta(minutes=5)
OTP_MAX_ATTEMPTS = 5


def normalize_target(email=None, phone=None):
    if email:
        return email.strip().lower()
    if phone:
        digits = "".join(c for c in phone if c.isdigit() or c == "+")
        if digits.startswith("01") and len(digits) == 11:  # Egyptian mobile -> E.164
            digits = "+2" + digits
        return digits
    raise ValidationFailed("Enter an email address or a phone number.")


def norm_any(identifier):
    identifier = (identifier or "").strip()
    return normalize_target(email=identifier) if "@" in identifier else normalize_target(phone=identifier)


def _otp_hash(code, target):
    return hmac.new(current_app.config["SECRET_KEY"].encode(), f"{target}:{code}".encode(), hashlib.sha256).hexdigest()


def issue_otp(target, purpose):
    code = f"{secrets.randbelow(10**6):06d}"
    repo.add(OtpCode(target=target, purpose=purpose, code_hash=_otp_hash(code, target), expires_at=utcnow() + OTP_TTL))
    db.session.commit()
    notify.send_otp(target, code, purpose)
    return {
        "target": target,
        "sent_to": notify._mask(target),
        "expires_in": int(OTP_TTL.total_seconds()),
        **({"dev_code": code} if current_app.config["DEMO_MODE"] else {}),
    }


def check_otp(target, purpose, code):
    otp = repo.Otps.latest_active(target, purpose)
    if otp is None or otp.expires_at < utcnow():
        raise ValidationFailed("This code has expired. Request a new one.", code="otp_expired")
    if otp.attempts >= OTP_MAX_ATTEMPTS:
        raise ValidationFailed("Too many wrong attempts. Request a new code.", code="otp_locked")
    if not hmac.compare_digest(otp.code_hash, _otp_hash(code, target)):
        otp.attempts += 1
        db.session.commit()
        raise ValidationFailed(
            "That code is not correct.", code="otp_invalid", details={"attempts_left": OTP_MAX_ATTEMPTS - otp.attempts}
        )
    otp.consumed_at = utcnow()


def register(name, password, email=None, phone=None, language="en"):
    target = normalize_target(email, phone)
    existing = repo.Users.by_identifier(target)
    if existing and existing.status != "pending":
        raise Conflict("An account with this email or phone already exists.", code="account_exists")
    user = existing or User()
    user.name, user.language = name.strip(), language
    user.email = target if email else None
    user.phone = target if phone and not email else None
    user.password_hash = hash_password(password)
    user.status = "pending"
    repo.add(user)
    try:
        db.session.flush()
    except IntegrityError:
        db.session.rollback()
        raise Conflict("An account with this email or phone already exists.", code="account_exists") from None
    return issue_otp(target, "verify")


def verify_signup(target, code):
    target = norm_any(target)
    user = repo.Users.by_identifier(target)
    if user is None:
        raise ValidationFailed("No sign-up found for this email or phone.")
    check_otp(target, "verify", code)
    if user.status == "pending":
        user.status = "active"
        notify.notify(user, "account", "welcome")
        audit.record("user.registered", "user", user.id, actor=user)
    return issue_tokens(user)


def request_login_otp(target):
    target = norm_any(target)
    user = repo.Users.by_identifier(target)
    if user is None or user.status != "active":
        # Same response either way so the endpoint can't be used to discover accounts.
        return {"target": target, "sent_to": notify._mask(target), "expires_in": int(OTP_TTL.total_seconds())}
    return issue_otp(target, "login")


def login_with_otp(target, code):
    target = norm_any(target)
    user = repo.Users.by_identifier(target)
    if user is None:
        raise Unauthorized("That code is not correct.")
    check_otp(target, "login", code)
    _ensure_can_login(user)
    return issue_tokens(user)


def login_with_password(identifier, password):
    user = repo.Users.by_identifier(norm_any(identifier))
    if user is None or not verify_password(user.password_hash, password):
        raise Unauthorized("Wrong email/phone or password.", code="invalid_credentials")
    _ensure_can_login(user)
    return issue_tokens(user)


def _ensure_can_login(user):
    if user.status == "pending":
        raise Forbidden("Verify your account with the code we sent first.", code="account_unverified")
    if user.status == "suspended":
        raise Forbidden("This account is suspended. Contact support.", code="account_suspended")


def issue_tokens(user, replaces=None):
    token = repo.add(
        RefreshToken(id=new_id(), user_id=user.id, expires_at=utcnow() + current_app.config["REFRESH_TOKEN_TTL"])
    )
    if replaces is not None:
        replaces.revoked_at, replaces.replaced_by = utcnow(), token.id
    user.last_login_at = utcnow()
    db.session.commit()
    return {
        "access_token": make_access_token(user),
        "refresh_token": make_refresh_token(user.id, token.id),
        "token_type": "Bearer",
        "expires_in": int(current_app.config["ACCESS_TOKEN_TTL"].total_seconds()),
        "user": user.to_dict(),
    }


def refresh(refresh_jwt):
    payload = decode_token(refresh_jwt, "refresh")
    stored = repo.get(RefreshToken, payload["jti"])
    if stored is None or stored.expires_at < utcnow():
        raise Unauthorized("Session expired. Log in again.", code="token_expired")
    if stored.revoked_at is not None:
        # A rotated token was used again: likely stolen. Revoke the whole session family.
        repo.RefreshTokens.revoke_all_for(stored.user_id, utcnow())
        db.session.commit()
        raise Unauthorized("Session expired. Log in again.", code="token_reused")
    user = repo.get(User, stored.user_id)
    _ensure_can_login(user)
    return issue_tokens(user, replaces=stored)


def logout(refresh_jwt):
    try:
        payload = decode_token(refresh_jwt, "refresh")
    except Unauthorized:
        return
    stored = repo.get(RefreshToken, payload["jti"])
    if stored and stored.revoked_at is None:
        stored.revoked_at = utcnow()
        db.session.commit()


def change_password(user, current, new):
    if user.password_hash and not verify_password(user.password_hash, current):
        raise Unauthorized("Current password is wrong.", code="invalid_credentials")
    user.password_hash = hash_password(new)
    repo.RefreshTokens.revoke_all_for(user.id, utcnow())
    audit.record("user.password_changed", "user", user.id)
    db.session.commit()
