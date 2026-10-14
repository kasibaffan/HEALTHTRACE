from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.service import audit_dict, record
from app.auth.deps import Ctx, require
from app.auth.permissions import Perm
from app.core.errors import AppError, conflict
from app.database.session import get_db
from app.models import Case, Evidence, Finding
from app.models.enums import CaseStatus, ReviewerStatus
from app.repositories.scoped import get_finding
from app.schemas.inputs import ReviewIn
from app.services.ai import get_ai_service
from app.services.chain import build_chain
from app.services.notify import notify
from app.services.serializers import case_with_counts, finding_dict
from app.websocket import manager as ws
from app.websocket.manager import Outbox, make_event

router = APIRouter(prefix="/findings", tags=["findings"])

ACTIONS = {
    "accept": (ReviewerStatus.ACCEPTED, "Accepted finding"),
    "override": (ReviewerStatus.OVERRIDDEN, "Overrode finding"),
    "request-evidence": (ReviewerStatus.REQUESTED_EVIDENCE, "Requested additional evidence"),
}


def _evidence_map(db: Session, f: Finding) -> dict:
    ids = {l.evidence_id for l in f.links}
    return {e.id: e for e in db.execute(select(Evidence).where(Evidence.id.in_(ids))).unique().scalars()} if ids else {}


@router.get("/{finding_id}")
def get_one(finding_id: str, ctx: Ctx = Depends(require(Perm.CASE_VIEW)), db: Session = Depends(get_db)):
    f = get_finding(db, ctx.org_id, finding_id)
    return finding_dict(f, _evidence_map(db, f))


@router.get("/{finding_id}/evidence-chain")
def evidence_chain(finding_id: str, ctx: Ctx = Depends(require(Perm.EVIDENCE_VIEW)), db: Session = Depends(get_db)):
    return build_chain(db, get_finding(db, ctx.org_id, finding_id), get_ai_service().name)


@router.post("/{finding_id}/opened", status_code=204)
def passport_opened(finding_id: str, ctx: Ctx = Depends(require(Perm.EVIDENCE_VIEW)), db: Session = Depends(get_db)):
    f = get_finding(db, ctx.org_id, finding_id)
    ev = record(db, action="Opened Evidence Passport", org_id=ctx.org_id, ctx=ctx, case_id=f.case_id, entity_type="finding", entity_id=f.id, target=f"{f.rule.code} {f.rule.finding_title or f.rule.name}")
    db.commit()
    outbox = Outbox()
    outbox.org(ctx.org_id, make_event(ws.AUDIT_EVENT, case_id=str(f.case_id), actor={"id": str(ctx.user.id), "fullName": ctx.user.full_name}, payload=audit_dict(ev)))
    outbox.flush()


def _review(finding_id: str, action: str, body: ReviewIn, ctx: Ctx, db: Session) -> dict:
    new_status, label = ACTIONS[action]
    f = get_finding(db, ctx.org_id, finding_id)
    case = db.get(Case, f.case_id)
    reason = (body.reason or "").strip() or None
    if action == "override" and not reason:
        raise AppError(422, "An override requires a written reason.", "reason_required")
    if body.expected_version is not None and body.expected_version != f.version:
        who = f.reviewer.full_name if f.reviewer else "another user"
        raise conflict(f"This finding was updated by {who} while you were viewing it. Review the latest state and try again.")
    if action == "request-evidence" and not reason:
        reason = f.suggested_action or "Additional documentation requested."

    old = {"reviewerStatus": f.reviewer_status.value, "reason": f.review_reason}
    f.reviewer_status, f.reviewed_by, f.reviewed_at, f.review_reason = new_status, ctx.user.id, datetime.now(timezone.utc), reason
    f.version += 1
    db.flush()
    db.refresh(f)
    outbox = Outbox()
    target = f"{f.rule.code} {f.rule.finding_title or f.rule.name}"
    audit_ev = record(db, action=label, org_id=ctx.org_id, ctx=ctx, case_id=f.case_id, entity_type="finding", entity_id=f.id, target=target,
                      old=old, new={"reviewerStatus": new_status.value, "reason": reason}, reason=reason)

    # Case status follows the review state (all inside this transaction).
    pending = db.execute(select(Finding).where(Finding.case_id == case.id, Finding.reviewer_status == ReviewerStatus.PENDING)).scalars().all()
    requested = db.execute(select(Finding).where(Finding.case_id == case.id, Finding.reviewer_status == ReviewerStatus.REQUESTED_EVIDENCE)).scalars().all()
    old_case_status = case.status
    if case.status != CaseStatus.ARCHIVED:
        if pending:
            case.status = CaseStatus.IN_REVIEW
        else:
            case.status = CaseStatus.WAITING_FOR_EVIDENCE if requested else CaseStatus.COMPLETED
    if case.status != old_case_status:
        record(db, action="Case status changed", org_id=ctx.org_id, ctx=ctx, case_id=case.id, entity_type="case", entity_id=case.id, target=case.case_number,
               old={"status": old_case_status.value}, new={"status": case.status.value})

    notify_type = "EVIDENCE_REQUESTED" if action == "request-evidence" else "FINDING_UPDATED"
    title = f"Additional evidence requested on {case.case_number}" if action == "request-evidence" else f"{ctx.user.full_name} updated a finding on {case.case_number}"
    message = f"{f.rule.finding_title or f.rule.name}: {label.lower()}" + (f" - {reason}" if reason else "")
    notify(db, outbox, org_id=ctx.org_id, user_ids=[case.assigned_to, case.created_by], type_=notify_type, title=title, message=message[:500], case_id=case.id, exclude=ctx.user.id)
    db.commit()

    actor = {"id": str(ctx.user.id), "fullName": ctx.user.full_name}
    payload = {"findingId": str(f.id), "criterion": f.rule.finding_title or f.rule.name, "reviewerStatus": new_status.value, "action": action, "reason": reason, "version": f.version}
    outbox.org(ctx.org_id, make_event(ws.FINDING_UPDATED, case_id=str(case.id), actor=actor, payload=payload))
    outbox.org(ctx.org_id, make_event(ws.REVIEW_ACTION, case_id=str(case.id), actor=actor, payload=payload))
    if action == "request-evidence":
        outbox.org(ctx.org_id, make_event(ws.EVIDENCE_REQUESTED, case_id=str(case.id), actor=actor, payload=payload))
    if case.status != old_case_status:
        outbox.org(ctx.org_id, make_event(ws.CASE_UPDATED, case_id=str(case.id), actor=actor, payload={"status": case.status.value, "previousStatus": old_case_status.value}))
    outbox.org(ctx.org_id, make_event(ws.AUDIT_EVENT, case_id=str(case.id), actor=actor, payload=audit_dict(audit_ev)))
    outbox.flush()
    return finding_dict(f, _evidence_map(db, f))


@router.post("/{finding_id}/accept")
def accept(finding_id: str, body: ReviewIn | None = None, ctx: Ctx = Depends(require(Perm.FINDING_REVIEW)), db: Session = Depends(get_db)):
    return _review(finding_id, "accept", body or ReviewIn(), ctx, db)


@router.post("/{finding_id}/override")
def override(finding_id: str, body: ReviewIn, ctx: Ctx = Depends(require(Perm.FINDING_REVIEW)), db: Session = Depends(get_db)):
    return _review(finding_id, "override", body, ctx, db)


@router.post("/{finding_id}/request-evidence")
def request_evidence(finding_id: str, body: ReviewIn | None = None, ctx: Ctx = Depends(require(Perm.FINDING_REVIEW)), db: Session = Depends(get_db)):
    return _review(finding_id, "request-evidence", body or ReviewIn(), ctx, db)
