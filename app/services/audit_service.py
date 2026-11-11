import uuid
from enum import StrEnum
from typing import Any

from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog
from app.models.user import User


class AuditAction(StrEnum):
    USER_REGISTERED = "user.registered"
    DOMAIN_DELETED = "domain.deleted"


def record_audit(
    session: Session,
    action: AuditAction,
    *,
    actor: User,
    target_type: str,
    target_id: uuid.UUID,
    details: dict[str, Any],
) -> None:
    session.add(
        AuditLog(
            actor_id=actor.id,
            action=action.value,
            target_type=target_type,
            target_id=target_id,
            details=details,
        )
    )
