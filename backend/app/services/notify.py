import uuid
from typing import Iterable

from sqlalchemy.orm import Session

from app.models import Notification
from app.websocket.manager import NOTIFICATION, Outbox, make_event


def notification_dict(n: Notification) -> dict:
    return {"id": str(n.id), "type": n.type, "title": n.title, "message": n.message, "caseId": str(n.case_id) if n.case_id else None,
            "read": n.read, "createdAt": n.created_at.isoformat() if n.created_at else None}


def notify(db: Session, outbox: Outbox, *, org_id: uuid.UUID, user_ids: Iterable[uuid.UUID | None], type_: str, title: str,
           message: str, case_id: uuid.UUID | None = None, exclude: uuid.UUID | None = None) -> None:
    for uid in {u for u in user_ids if u and u != exclude}:
        n = Notification(user_id=uid, organization_id=org_id, type=type_, title=title, message=message, case_id=case_id)
        db.add(n)
        db.flush()
        db.refresh(n)
        outbox.user(org_id, uid, make_event(NOTIFICATION, case_id=str(case_id) if case_id else None, payload=notification_dict(n)))
