import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.auth.deps import Ctx
from app.models import AuditEvent

AI_ACTOR = "HealthTrace AI"
RULES_ACTOR = "Rules Engine"
SYSTEM_ACTOR = "System"


def record(
    db: Session, *, action: str, org_id: uuid.UUID | None, ctx: Ctx | None = None, user: Any = None,
    actor_label: str | None = None, actor_kind: str | None = None, case_id: uuid.UUID | None = None,
    entity_type: str | None = None, entity_id: Any = None, target: str | None = None,
    old: dict | None = None, new: dict | None = None, reason: str | None = None, ip: str | None = None,
) -> AuditEvent:
    """Append an audit event to the current transaction. Never logs secrets or document content."""
    actor_user = ctx.user if ctx else user
    event = AuditEvent(
        organization_id=org_id,
        user_id=actor_user.id if actor_user else None,
        actor_label=actor_label or (actor_user.full_name if actor_user else SYSTEM_ACTOR),
        actor_kind=actor_kind or ("HUMAN" if actor_user else "SYSTEM"),
        case_id=case_id, action=action, entity_type=entity_type,
        entity_id=str(entity_id) if entity_id is not None else None,
        target=target, old_value=old, new_value=new, reason=reason,
        ip_address=ip or (ctx.ip if ctx else None),
    )
    db.add(event)
    db.flush()
    return event


def audit_dict(e: AuditEvent) -> dict:
    return {
        "id": str(e.id), "caseId": str(e.case_id) if e.case_id else None, "timestamp": e.created_at.isoformat(),
        "actor": e.actor_label, "actorKind": e.actor_kind, "action": e.action, "entityType": e.entity_type,
        "entityId": e.entity_id, "target": e.target or "", "reason": e.reason, "oldValue": e.old_value, "newValue": e.new_value,
    }
