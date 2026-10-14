"""Documents, evidence, policies, audit, notifications, dashboard, health."""
from datetime import date, datetime, time, timezone

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.api.cases import list_evidence
from app.api.common import PageParams, page_out, paginate
from app.audit.service import audit_dict, record
from app.auth.deps import Ctx, get_ctx, require
from app.auth.permissions import Perm
from app.core.errors import AppError
from app.database.session import get_db
from app.models import AuditEvent, Case, Document, Evidence, Finding, Notification, Policy, Rule, User
from app.models.enums import CaseStatus, FindingStatus, PolicyStatus, ReviewerStatus
from app.repositories.scoped import get_document, get_evidence, get_notification, get_policy, parse_uuid
from app.schemas.inputs import PolicyCreateIn, PolicyPatchIn, RuleIn
from app.services.notify import notification_dict
from app.services.serializers import case_counts, case_dict, document_dict, evidence_dict
from app.storage import get_storage
from app.websocket import manager as ws
from app.websocket.manager import Outbox, hub, make_event

router = APIRouter()


@router.get("/documents/{document_id}", tags=["documents"])
def get_document_detail(document_id: str, ctx: Ctx = Depends(require(Perm.CASE_VIEW)), db: Session = Depends(get_db)):
    from app.services.text_extraction import paragraphs

    doc = get_document(db, ctx.org_id, document_id)
    return {**document_dict(doc), "pages": [{"number": p.page_number, "heading": (paragraphs(p.text) or [""])[0][:120], "lines": paragraphs(p.text)[1:] if len(paragraphs(p.text)) > 1 else paragraphs(p.text)} for p in doc.pages]}


@router.get("/documents/{document_id}/download", tags=["documents"])
def download_document(document_id: str, ctx: Ctx = Depends(require(Perm.CASE_VIEW)), db: Session = Depends(get_db)):
    doc = get_document(db, ctx.org_id, document_id)
    storage = get_storage()
    if not storage.exists(doc.storage_path):
        raise AppError(404, "The stored file is unavailable.", "file_missing")
    record(db, action="Document downloaded", org_id=ctx.org_id, ctx=ctx, case_id=doc.case_id, entity_type="document", entity_id=doc.id, target=doc.filename)
    db.commit()
    safe = doc.filename.replace('"', "")
    return Response(storage.read(doc.storage_path), media_type=doc.file_type, headers={"Content-Disposition": f'attachment; filename="{safe}"', "X-Content-Type-Options": "nosniff"})


@router.get("/evidence", tags=["evidence"])
def search_evidence(search: str | None = Query(None, max_length=100), verified: bool | None = None, document_id: str | None = Query(None, alias="documentId"),
                    evidence_type: str | None = Query(None, alias="evidenceType"), p: PageParams = Depends(), ctx: Ctx = Depends(require(Perm.EVIDENCE_VIEW)), db: Session = Depends(get_db)):
    return list_evidence(db, ctx, p, case=None, search=search, verified=verified, document_id=document_id, evidence_type=evidence_type)


@router.get("/evidence/{evidence_id}", tags=["evidence"])
def get_evidence_detail(evidence_id: str, ctx: Ctx = Depends(require(Perm.EVIDENCE_VIEW)), db: Session = Depends(get_db)):
    e = get_evidence(db, ctx.org_id, evidence_id)
    return evidence_dict(e, [], [str(f) for f in db.execute(select(Finding.id).join(Finding.links).where(Finding.links.any(evidence_id=e.id))).scalars()])


@router.post("/evidence/{evidence_id}/verify", tags=["evidence"])
def verify_evidence(evidence_id: str, ctx: Ctx = Depends(require(Perm.EVIDENCE_VERIFY)), db: Session = Depends(get_db)):
    e = get_evidence(db, ctx.org_id, evidence_id)
    if not e.verified:
        e.verified, e.verified_by, e.verified_at = True, ctx.user.id, datetime.now(timezone.utc)
        ev = record(db, action="Evidence verified", org_id=ctx.org_id, ctx=ctx, case_id=e.case_id, entity_type="evidence", entity_id=e.id, target=f"{e.code} ({e.document.filename}, p.{e.page})")
        db.commit()
        outbox = Outbox()
        outbox.org(ctx.org_id, make_event(ws.AUDIT_EVENT, case_id=str(e.case_id), payload=audit_dict(ev)))
        outbox.flush()
    return evidence_dict(e, verifier=ctx.user if e.verified_by == ctx.user.id else None)


def _policy_dict(p: Policy) -> dict:
    return {"id": str(p.id), "name": p.name, "version": p.version, "description": p.description, "status": p.status.value, "createdAt": p.created_at.isoformat() if p.created_at else None,
            "updatedAt": p.updated_at.isoformat() if p.updated_at else None,
            "rules": [{"id": str(r.id), "code": r.code, "name": r.name, "findingTitle": r.finding_title, "requirement": r.requirement, "description": r.description, "expression": r.expression,
                       "factName": r.fact_name, "operator": r.operator, "threshold": r.threshold, "unit": r.unit, "expectedEvidence": r.expected_evidence, "suggestedAction": r.suggested_action,
                       "sourceDocumentName": r.source_document_name, "sourcePage": r.source_page, "sourceText": r.source_text} for r in p.rules]}


def _build_rule(r: RuleIn, i: int) -> Rule:
    expr = {"consistent": f"distinct({r.fact_name} across sources) == 1", "contains": f"{r.fact_name} contains '{r.threshold}'"}.get(r.operator, f"{r.fact_name} {r.operator} {r.threshold}{(' ' + r.unit) if r.unit else ''}")
    if r.operator not in ("consistent",) and r.threshold in (None, ""):
        raise AppError(422, f"Rule {r.code} needs a threshold.", "validation_error")
    return Rule(code=r.code, name=r.name, finding_title=r.finding_title or r.name, requirement=r.requirement, description=r.description, expression=expr, fact_name=r.fact_name,
                operator=r.operator, threshold=r.threshold, unit=r.unit, expected_evidence=r.expected_evidence, suggested_action=r.suggested_action, sort_order=i)


@router.get("/policies", tags=["policies"])
def list_policies(ctx: Ctx = Depends(require(Perm.POLICY_VIEW)), db: Session = Depends(get_db)):
    rows = db.execute(select(Policy).where(Policy.organization_id == ctx.org_id).order_by(Policy.created_at.desc())).unique().scalars().all()
    return [_policy_dict(p) for p in rows]


@router.post("/policies", status_code=201, tags=["policies"])
def create_policy(body: PolicyCreateIn, ctx: Ctx = Depends(require(Perm.POLICY_MANAGE)), db: Session = Depends(get_db)):
    p = Policy(organization_id=ctx.org_id, name=body.name, version=body.version, description=body.description, status=body.status, created_by=ctx.user.id)
    p.rules = [_build_rule(r, i) for i, r in enumerate(body.rules)]
    db.add(p)
    db.flush()
    record(db, action="Policy created", org_id=ctx.org_id, ctx=ctx, entity_type="policy", entity_id=p.id, target=f"{p.name} {p.version}", new={"rules": len(p.rules)})
    db.commit()
    return _policy_dict(p)


@router.get("/policies/{policy_id}", tags=["policies"])
def get_policy_detail(policy_id: str, ctx: Ctx = Depends(require(Perm.POLICY_VIEW)), db: Session = Depends(get_db)):
    return _policy_dict(get_policy(db, ctx.org_id, policy_id))


@router.patch("/policies/{policy_id}", tags=["policies"])
def patch_policy(policy_id: str, body: PolicyPatchIn, ctx: Ctx = Depends(require(Perm.POLICY_MANAGE)), db: Session = Depends(get_db)):
    p = get_policy(db, ctx.org_id, policy_id)
    old = {"name": p.name, "version": p.version, "status": p.status.value, "rules": len(p.rules)}
    for field in ("name", "version", "description", "status"):
        val = getattr(body, field)
        if val is not None:
            setattr(p, field, val)
    if body.rules is not None:
        in_use = db.execute(select(func.count()).select_from(Finding).where(Finding.policy_id == p.id)).scalar_one()
        if in_use:
            raise AppError(409, "This policy is already used by cases. Create a new version instead of replacing its rules.", "conflict")
        p.rules = [_build_rule(r, i) for i, r in enumerate(body.rules)]
    record(db, action="Policy updated", org_id=ctx.org_id, ctx=ctx, entity_type="policy", entity_id=p.id, target=f"{p.name} {p.version}", old=old,
           new={"name": p.name, "version": p.version, "status": p.status.value, "rules": len(p.rules)})
    db.commit()
    return _policy_dict(p)


@router.get("/audit", tags=["audit"])
def org_audit(user_id: str | None = Query(None, alias="userId"), action: str | None = Query(None, max_length=100), case_id: str | None = Query(None, alias="caseId"),
              date_from: date | None = Query(None, alias="dateFrom"), date_to: date | None = Query(None, alias="dateTo"), actor_kind: str | None = Query(None, alias="actorKind"),
              p: PageParams = Depends(), ctx: Ctx = Depends(require(Perm.AUDIT_VIEW)), db: Session = Depends(get_db)):
    stmt = select(AuditEvent).where(AuditEvent.organization_id == ctx.org_id)
    if user_id:
        stmt = stmt.where(AuditEvent.user_id == parse_uuid(user_id, "User"))
    if action:
        stmt = stmt.where(func.lower(AuditEvent.action).like(f"%{action.lower()}%"))
    if case_id:
        stmt = stmt.where(AuditEvent.case_id == parse_uuid(case_id, "Case"))
    if actor_kind:
        stmt = stmt.where(AuditEvent.actor_kind == actor_kind.upper())
    if date_from:
        stmt = stmt.where(AuditEvent.created_at >= datetime.combine(date_from, time.min, tzinfo=timezone.utc))
    if date_to:
        stmt = stmt.where(AuditEvent.created_at <= datetime.combine(date_to, time.max, tzinfo=timezone.utc))
    rows, total = paginate(db, stmt.order_by(AuditEvent.created_at.desc(), AuditEvent.id), p)
    events = [r[0] for r in rows]
    cases = {c.id: c.case_number for c in db.execute(select(Case).where(Case.id.in_({e.case_id for e in events if e.case_id}))).unique().scalars()} if events else {}
    return page_out([{**audit_dict(e), "caseNumber": cases.get(e.case_id)} for e in events], total, p)


@router.get("/notifications", tags=["notifications"])
def list_notifications(unread_only: bool = Query(False, alias="unreadOnly"), p: PageParams = Depends(), ctx: Ctx = Depends(get_ctx), db: Session = Depends(get_db)):
    base = select(Notification).where(Notification.user_id == ctx.user.id, Notification.organization_id == ctx.org_id)
    if unread_only:
        base = base.where(Notification.read.is_(False))
    rows, total = paginate(db, base.order_by(Notification.created_at.desc(), Notification.id), p)
    unread = db.execute(select(func.count()).select_from(Notification).where(Notification.user_id == ctx.user.id, Notification.read.is_(False))).scalar_one()
    return {**page_out([notification_dict(r[0]) for r in rows], total, p), "unread": unread}


@router.post("/notifications/read-all", tags=["notifications"])
def read_all(ctx: Ctx = Depends(get_ctx), db: Session = Depends(get_db)):
    db.query(Notification).filter(Notification.user_id == ctx.user.id, Notification.read.is_(False)).update({"read": True})
    db.commit()
    return {"ok": True}


@router.post("/notifications/{notification_id}/read", tags=["notifications"])
def mark_read(notification_id: str, ctx: Ctx = Depends(get_ctx), db: Session = Depends(get_db)):
    n = get_notification(db, ctx.user.id, notification_id)
    n.read = True
    db.commit()
    return notification_dict(n)


@router.get("/dashboard", tags=["dashboard"])
def dashboard(ctx: Ctx = Depends(require(Perm.CASE_VIEW)), db: Session = Depends(get_db)):
    org = ctx.org_id
    total = db.execute(select(func.count()).select_from(Case).where(Case.organization_id == org, Case.status != CaseStatus.ARCHIVED)).scalar_one()
    needs = db.execute(select(func.count()).select_from(Case).where(Case.organization_id == org, Case.status.in_([CaseStatus.NEEDS_REVIEW, CaseStatus.IN_REVIEW]))).scalar_one()
    waiting = db.execute(select(func.count()).select_from(Case).where(Case.organization_id == org, Case.status == CaseStatus.WAITING_FOR_EVIDENCE)).scalar_one()
    open_states = [ReviewerStatus.PENDING, ReviewerStatus.REQUESTED_EVIDENCE]
    active_case = select(Case.id).where(Case.organization_id == org, Case.status != CaseStatus.ARCHIVED)
    missing = db.execute(select(func.count()).select_from(Finding).where(Finding.organization_id == org, Finding.status == FindingStatus.MISSING, Finding.reviewer_status.in_(open_states), Finding.case_id.in_(active_case))).scalar_one()
    conflicts = db.execute(select(func.count()).select_from(Finding).where(Finding.organization_id == org, Finding.status == FindingStatus.CONFLICT, Finding.reviewer_status.in_(open_states), Finding.case_id.in_(active_case))).scalar_one()
    pending = db.execute(select(func.count()).select_from(Finding).where(Finding.organization_id == org, Finding.reviewer_status == ReviewerStatus.PENDING, Finding.case_id.in_(active_case))).scalar_one()
    completed = db.execute(select(func.count()).select_from(Finding).where(Finding.organization_id == org, Finding.reviewer_status.in_([ReviewerStatus.ACCEPTED, ReviewerStatus.OVERRIDDEN]))).scalar_one()
    completed_cases = db.execute(select(func.count()).select_from(Case).where(Case.organization_id == org, Case.status == CaseStatus.COMPLETED)).scalar_one()
    today = datetime.combine(date.today(), time.min, tzinfo=timezone.utc)
    reviews_today = db.execute(select(func.count()).select_from(AuditEvent).where(AuditEvent.organization_id == org, AuditEvent.actor_kind == "HUMAN", AuditEvent.created_at >= today,
                                                                                   AuditEvent.action.in_(["Accepted finding", "Overrode finding", "Requested additional evidence"]))).scalar_one()
    recent = db.execute(select(Case).where(Case.organization_id == org).order_by(Case.updated_at.desc()).limit(5)).unique().scalars().all()
    counts = case_counts(db, [c.id for c in recent])
    activity = db.execute(select(AuditEvent).where(AuditEvent.organization_id == org).order_by(AuditEvent.created_at.desc(), AuditEvent.id).limit(8)).scalars().all() if ctx.can(Perm.AUDIT_VIEW) else []
    return {"totalCases": total, "casesNeedingReview": needs, "casesWaitingForEvidence": waiting, "missingEvidence": missing, "openConflicts": conflicts, "pendingFindings": pending,
            "completedReviews": completed, "completedCases": completed_cases, "humanReviewsToday": reviews_today,
            "recentCases": [case_dict(c, counts[c.id]["missing"], counts[c.id]["conflicts"], counts[c.id]["documents"]) for c in recent],
            "recentActivity": [audit_dict(a) for a in activity]}



@router.get("/health", tags=["health"])
def health(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
        database = "up"
    except Exception:  # noqa: BLE001
        database = "down"
    return {"status": "healthy" if database == "up" else "degraded", "api": "up", "database": database, "websocket": {"status": "up" if hub.loop else "starting", "connections": hub.connection_count()},
            "apiKeyRequired": False}
