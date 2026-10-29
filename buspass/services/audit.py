from flask import has_request_context

from .. import repositories as repo
from ..models import AuditLog
from ..security import client_ip, current_user


def record(action, entity=None, entity_id=None, details=None, actor=None):
    """Append to the audit log (committed together with the caller's transaction)."""
    actor = actor or (current_user() if has_request_context() else None)
    repo.add(
        AuditLog(
            actor_id=actor.id if actor else None,
            action=action,
            entity=entity,
            entity_id=str(entity_id) if entity_id is not None else None,
            details=details,
            ip=client_ip() if has_request_context() else None,
        )
    )
