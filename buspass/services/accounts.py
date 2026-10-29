"""Rider account features: profile, discount verification uploads, support tickets, notifications."""

import os
import uuid

from flask import current_app

from .. import repositories as repo
from ..errors import Conflict, NotFound, ValidationFailed
from ..extensions import db
from ..models import Notification, SupportTicket, User, VerificationDocument, utcnow
from . import audit, notify

ALLOWED_UPLOADS = {"image/jpeg": ".jpg", "image/png": ".png", "application/pdf": ".pdf"}
MAGIC = {".jpg": [b"\xff\xd8\xff"], ".png": [b"\x89PNG"], ".pdf": [b"%PDF"]}


def update_profile(user, name=None, language=None):
    if name is not None:
        user.name = name.strip()
    if language is not None:
        user.language = language
    db.session.commit()
    return user


def upload_verification(user, kind, file_storage):
    if user.discount_status == "approved" and user.discount_type == kind:
        raise Conflict("Your discount is already approved.")
    ext = ALLOWED_UPLOADS.get(file_storage.mimetype)
    if ext is None:
        raise ValidationFailed("Upload a JPG, PNG or PDF file.", details={"field": "file"})
    head = file_storage.stream.read(8)
    file_storage.stream.seek(0)
    # Don't trust the browser's content type alone: check the file signature too.
    if not any(head.startswith(m) for m in MAGIC[ext]):
        raise ValidationFailed("The file content doesn't match its type.", details={"field": "file"})
    stored = uuid.uuid4().hex + ext
    os.makedirs(current_app.config["UPLOAD_DIR"], exist_ok=True)
    file_storage.save(os.path.join(current_app.config["UPLOAD_DIR"], stored))
    doc = repo.add(
        VerificationDocument(
            user_id=user.id,
            kind=kind,
            stored_name=stored,
            original_name=(file_storage.filename or "upload")[:200],
            content_type=file_storage.mimetype,
        )
    )
    user.discount_type, user.discount_status = kind, "pending"
    audit.record("verification.uploaded", "user", user.id, {"kind": kind})
    db.session.commit()
    return doc


def review_verification(admin, doc_id, approve, note=None):
    doc = repo.get(VerificationDocument, doc_id)
    if doc is None:
        raise NotFound("Document not found.")
    if doc.status != "pending":
        raise Conflict("This document was already reviewed.")
    doc.status = "approved" if approve else "rejected"
    doc.reviewed_by, doc.reviewed_at, doc.note = admin.id, utcnow(), note
    user = doc.user
    user.discount_type = doc.kind
    user.discount_status = doc.status
    notify.notify(
        user,
        "account",
        "verification",
        status={"en": doc.status, "ar": "قبول" if approve else "رفض"},
        kind={"en": doc.kind, "ar": "الطلاب" if doc.kind == "student" else "كبار السن"},
    )
    audit.record(f"verification.{doc.status}", "user", user.id, {"doc_id": doc.id, "note": note}, actor=admin)
    db.session.commit()
    return doc


def document_path(doc_id):
    doc = repo.get(VerificationDocument, doc_id)
    if doc is None:
        raise NotFound("Document not found.")
    return os.path.join(current_app.config["UPLOAD_DIR"], doc.stored_name), doc


def open_ticket(user, category, message):
    ticket = repo.add(SupportTicket(user_id=user.id, category=category, message=message.strip()))
    db.session.flush()
    notify.notify(user, "support", "support", id=ticket.id)
    db.session.commit()
    return ticket


def close_ticket(admin, ticket_id):
    t = repo.get(SupportTicket, ticket_id)
    if t is None:
        raise NotFound("Ticket not found.")
    t.status = "closed"
    audit.record("support.closed", "support_ticket", t.id, actor=admin)
    db.session.commit()
    return t


def notifications(user):
    return {
        "unread": repo.Notifications.unread_count(user.id),
        "items": [n.to_dict() for n in repo.Notifications.of_user(user.id)],
    }


def mark_read(user, ids=None):
    q = db.session.query(Notification).filter(Notification.user_id == user.id, Notification.read_at.is_(None))
    if ids:
        q = q.filter(Notification.id.in_(ids))
    q.update({"read_at": utcnow()}, synchronize_session=False)
    db.session.commit()


def set_status(admin, user_id, status, reason=""):
    user = repo.get(User, user_id)
    if user is None:
        raise NotFound("User not found.")
    if user.id == admin.id:
        raise Conflict("You can't change your own status.")
    user.status = status
    if status == "suspended":
        repo.RefreshTokens.revoke_all_for(user.id, utcnow())
    audit.record(f"user.{status}", "user", user.id, {"reason": reason}, actor=admin)
    db.session.commit()
    return user


def set_role(admin, user_id, role, organization_id=None):
    user = repo.get(User, user_id)
    if user is None:
        raise NotFound("User not found.")
    if user.id == admin.id:
        raise Conflict("You can't change your own role.")
    user.role = role
    if organization_id is not None:
        user.organization_id = organization_id
    audit.record("user.role_changed", "user", user.id, {"role": role}, actor=admin)
    db.session.commit()
    return user
