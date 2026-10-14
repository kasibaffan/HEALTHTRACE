import hashlib
import uuid
from datetime import date, datetime, time, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, File, Query, UploadFile
from sqlalchemy import func, or_, select, text
from sqlalchemy.orm import Session

from app.api.common import PageParams, page_out, paginate
from app.audit.service import audit_dict, record
from app.auth.deps import Ctx, require
from app.auth.permissions import Perm
from app.core.config import settings
from app.core.errors import AppError, conflict
from app.database.session import get_db
from app.models import Case, Document, Evidence, Finding, FindingEvidence, Policy, ProcessingJob, Rule, TimelineEvent, User
from app.models.accounts import OrganizationMember
from app.models.enums import CaseStatus, DocumentStatus, EvidenceLinkRole, FindingStatus, PolicyStatus, Priority, Role
from app.repositories.scoped import get_case, parse_uuid
from app.schemas.inputs import AssignIn, CaseCreateIn, CaseUpdateIn
from app.services import files as filesvc
from app.services.demo import DEMO_CASE_NUMBER, create_demo_case
from app.services.notify import notify
from app.services.processing import process_document
from app.services.serializers import (
    case_counts, case_dict, case_with_counts, document_dict, evidence_dict, finding_dict, timeline_dict,
)
from app.storage import get_storage
from app.websocket import manager as ws
from app.websocket.manager import Outbox, make_event

router = APIRouter(prefix="/cases", tags=["cases"])


def _actor(ctx: Ctx) -> dict:
    return {"id": str(ctx.user.id), "fullName": ctx.user.full_name}


def _next_case_number(db: Session, org_id: uuid.UUID) -> str:
    if db.bind.dialect.name == "postgresql":
        db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": f"case-number:{org_id}"})
    nums = [int(n[3:]) for n in db.execute(select(Case.case_number).where(Case.organization_id == org_id)).scalars() if n.startswith("HT-") and n[3:].isdigit()]
    return f"HT-{max(nums, default=10482) + 1}"


@router.get("")
def list_cases(
    search: str | None = Query(None, max_length=100), status: CaseStatus | None = None, priority: Priority | None = None,
    assigned_to: str | None = Query(None, alias="assignedTo"), date_from: date | None = Query(None, alias="dateFrom"), date_to: date | None = Query(None, alias="dateTo"),
    p: PageParams = Depends(), ctx: Ctx = Depends(require(Perm.CASE_VIEW)), db: Session = Depends(get_db),
):
    stmt = select(Case).outerjoin(User, Case.assigned_to == User.id).where(Case.organization_id == ctx.org_id)
    if search:
        like = f"%{search.lower()}%"
        stmt = stmt.where(or_(func.lower(Case.case_number).like(like), func.lower(Case.patient_reference).like(like), func.lower(Case.condition).like(like),
                              func.lower(User.full_name).like(like), func.lower(func.replace(Case.status, "_", " ")).like(like)))
    if status:
        stmt = stmt.where(Case.status == status)
    if priority:
        stmt = stmt.where(Case.priority == priority)
    if assigned_to == "me":
        stmt = stmt.where(Case.assigned_to == ctx.user.id)
    elif assigned_to == "unassigned":
        stmt = stmt.where(Case.assigned_to.is_(None))
    elif assigned_to:
        stmt = stmt.where(Case.assigned_to == parse_uuid(assigned_to, "User"))
    if date_from:
        stmt = stmt.where(Case.created_at >= datetime.combine(date_from, time.min, tzinfo=timezone.utc))
    if date_to:
        stmt = stmt.where(Case.created_at <= datetime.combine(date_to, time.max, tzinfo=timezone.utc))
    rows, total = paginate(db, stmt.order_by(Case.updated_at.desc()), p)
    cases = [r[0] for r in rows]
    counts = case_counts(db, [c.id for c in cases])
    return page_out([case_dict(c, counts[c.id]["missing"], counts[c.id]["conflicts"], counts[c.id]["documents"]) for c in cases], total, p)


@router.post("", status_code=201)
def create_case(body: CaseCreateIn, ctx: Ctx = Depends(require(Perm.CASE_CREATE)), db: Session = Depends(get_db)):
    policy = db.execute(select(Policy).where(Policy.organization_id == ctx.org_id, Policy.status == PolicyStatus.ACTIVE).order_by(Policy.created_at)).scalars().first()
    case = Case(case_number=_next_case_number(db, ctx.org_id), organization_id=ctx.org_id, created_by=ctx.user.id, policy_id=policy.id if policy else None,
                patient_reference=body.patient_reference, member_reference=body.member_reference, condition=body.condition, requested_procedure=body.requested_procedure,
                priority=body.priority, requested_on=body.requested_on, status=CaseStatus.NEW)
    db.add(case)
    db.flush()
    db.refresh(case)
    record(db, action="Case created", org_id=ctx.org_id, ctx=ctx, case_id=case.id, entity_type="case", entity_id=case.id, target=case.case_number, new={"status": "NEW", "priority": case.priority.value})
    db.commit()
    outbox = Outbox()
    outbox.org(ctx.org_id, make_event(ws.CASE_UPDATED, case_id=str(case.id), actor=_actor(ctx), payload={"status": "NEW", "reason": "created", "caseNumber": case.case_number}))
    outbox.flush()
    return case_with_counts(db, case)


@router.post("/demo", status_code=201)
def load_demo_case(ctx: Ctx = Depends(require(Perm.CASE_CREATE, Perm.DOCUMENT_UPLOAD)), db: Session = Depends(get_db)):
    if db.execute(select(Case.id).where(Case.organization_id == ctx.org_id, Case.case_number == DEMO_CASE_NUMBER)).first():
        raise conflict(f"The demo case {DEMO_CASE_NUMBER} already exists in this workspace.")
    case = create_demo_case(db, ctx.org_id, ctx.user, assignee=None)
    db.commit()
    outbox = Outbox()
    outbox.org(ctx.org_id, make_event(ws.CASE_UPDATED, case_id=str(case.id), actor=_actor(ctx), payload={"status": case.status.value, "reason": "created", "caseNumber": case.case_number}))
    outbox.flush()
    return case_with_counts(db, case)


@router.get("/{case_id}")
def get_case_detail(case_id: str, ctx: Ctx = Depends(require(Perm.CASE_VIEW)), db: Session = Depends(get_db)):
    case = get_case(db, ctx.org_id, case_id)
    docs = db.execute(select(Document).where(Document.case_id == case.id).order_by(Document.created_at)).unique().scalars().all()
    jobs = {j.document_id: j for j in db.execute(select(ProcessingJob).where(ProcessingJob.document_id.in_([d.id for d in docs])).order_by(ProcessingJob.created_at)).scalars()} if docs else {}
    return {**case_with_counts(db, case), "documents": [document_dict(d, jobs.get(d.id)) for d in docs]}


@router.patch("/{case_id}")
def update_case(case_id: str, body: CaseUpdateIn, ctx: Ctx = Depends(require(Perm.CASE_UPDATE)), db: Session = Depends(get_db)):
    case = get_case(db, ctx.org_id, case_id)
    outbox = Outbox()
    changes: dict[str, list] = {}
    for field in ("patient_reference", "condition", "requested_procedure", "priority", "status"):
        new = getattr(body, field)
        if new is not None and new != getattr(case, field):
            old = getattr(case, field)
            changes[field] = [getattr(old, "value", old), getattr(new, "value", new)]
            setattr(case, field, new)
    if changes:
        status_change = "status" in changes
        record(db, action="Case status changed" if status_change and len(changes) == 1 else "Case updated", org_id=ctx.org_id, ctx=ctx, case_id=case.id, entity_type="case", entity_id=case.id,
               target=case.case_number, old={k: v[0] for k, v in changes.items()}, new={k: v[1] for k, v in changes.items()})
        if status_change:
            notify(db, outbox, org_id=ctx.org_id, user_ids=[case.assigned_to, case.created_by], type_="CASE_STATUS", title=f"{case.case_number} status changed",
                   message=f"{ctx.user.full_name} changed the status to {case.status.value.replace('_', ' ').title()}.", case_id=case.id, exclude=ctx.user.id)
        outbox.org(ctx.org_id, make_event(ws.CASE_UPDATED, case_id=str(case.id), actor=_actor(ctx), payload={"status": case.status.value, "changes": list(changes)}))
    db.commit()
    outbox.flush()
    return case_with_counts(db, case)


@router.post("/{case_id}/assign")
def assign_case(case_id: str, body: AssignIn, ctx: Ctx = Depends(require(Perm.CASE_ASSIGN)), db: Session = Depends(get_db)):
    case = get_case(db, ctx.org_id, case_id)
    outbox, assignee = Outbox(), None
    if body.user_id:
        uid = parse_uuid(body.user_id, "User")
        row = db.execute(select(User, OrganizationMember).join(OrganizationMember, OrganizationMember.user_id == User.id)
                         .where(User.id == uid, OrganizationMember.organization_id == ctx.org_id, User.is_active.is_(True))).unique().first()
        if not row:
            raise AppError(404, "User not found in this organization.", "not_found")
        assignee, member = row
        if member.role not in (Role.OWNER, Role.REVIEWER):
            raise AppError(422, "Cases can only be assigned to reviewers or owners.", "invalid_assignee")
    old = case.assignee
    if (old.id if old else None) == (assignee.id if assignee else None):
        return case_with_counts(db, case)
    case.assigned_to = assignee.id if assignee else None
    db.flush()
    db.refresh(case)
    action = "Case unassigned" if not assignee else ("Case reassigned" if old else "Case assigned")
    record(db, action=action, org_id=ctx.org_id, ctx=ctx, case_id=case.id, entity_type="case", entity_id=case.id, target=f"{case.case_number} -> {assignee.full_name if assignee else 'Unassigned'}",
           old={"assignedTo": old.full_name if old else None}, new={"assignedTo": assignee.full_name if assignee else None})
    if assignee:
        notify(db, outbox, org_id=ctx.org_id, user_ids=[assignee.id], type_="CASE_ASSIGNED", title=f"Case {case.case_number} assigned to you",
               message=f"{ctx.user.full_name} assigned you to review {case.patient_reference}.", case_id=case.id, exclude=ctx.user.id)
    if old:
        notify(db, outbox, org_id=ctx.org_id, user_ids=[old.id], type_="CASE_UNASSIGNED", title=f"Case {case.case_number} was reassigned",
               message=f"{ctx.user.full_name} moved this case to {assignee.full_name if assignee else 'no one'}.", case_id=case.id, exclude=ctx.user.id)
    outbox.org(ctx.org_id, make_event(ws.CASE_ASSIGNED, case_id=str(case.id), actor=_actor(ctx), payload={"assignedTo": {"id": str(assignee.id), "fullName": assignee.full_name} if assignee else None}))
    db.commit()
    outbox.flush()
    return case_with_counts(db, case)


@router.get("/{case_id}/findings")
def case_findings(case_id: str, ctx: Ctx = Depends(require(Perm.CASE_VIEW)), db: Session = Depends(get_db)):
    case = get_case(db, ctx.org_id, case_id)
    findings = db.execute(select(Finding).join(Rule, Finding.rule_id == Rule.id).where(Finding.case_id == case.id).order_by(Rule.sort_order)).unique().scalars().all()
    ev_ids = {l.evidence_id for f in findings for l in f.links}
    ev = {e.id: e for e in db.execute(select(Evidence).where(Evidence.id.in_(ev_ids))).unique().scalars()} if ev_ids else {}
    order = ["PR-002", "PR-001", "PR-003", "PR-004"]
    findings.sort(key=lambda f: (order.index(f.rule.code) if f.rule.code in order else 99, f.rule.sort_order))
    return [finding_dict(f, ev) for f in findings]


@router.get("/{case_id}/evidence")
def case_evidence(case_id: str, search: str | None = Query(None, max_length=100), verified: bool | None = None, document_id: str | None = Query(None, alias="documentId"),
                  evidence_type: str | None = Query(None, alias="evidenceType"), p: PageParams = Depends(), ctx: Ctx = Depends(require(Perm.EVIDENCE_VIEW)), db: Session = Depends(get_db)):
    case = get_case(db, ctx.org_id, case_id)
    return list_evidence(db, ctx, p, case=case, search=search, verified=verified, document_id=document_id, evidence_type=evidence_type)


def list_evidence(db: Session, ctx: Ctx, p: PageParams, *, case: Case | None, search=None, verified=None, document_id=None, evidence_type=None) -> dict:
    stmt = select(Evidence).join(Document, Evidence.document_id == Document.id).outerjoin(Case, Case.id == Evidence.case_id).where(Evidence.organization_id == ctx.org_id)
    if case:
        stmt = stmt.where(Evidence.case_id == case.id)
    if search:
        like = f"%{search.lower()}%"
        from app.models import Fact
        stmt = stmt.outerjoin(Fact, Fact.id == Evidence.fact_id).where(or_(func.lower(Evidence.text).like(like), func.lower(Evidence.code).like(like), func.lower(Document.filename).like(like),
                                                                            func.lower(Fact.label).like(like), func.lower(Fact.value).like(like)))
    if verified is not None:
        stmt = stmt.where(Evidence.verified == verified)
    if document_id:
        stmt = stmt.where(Evidence.document_id == parse_uuid(document_id, "Document"))
    if evidence_type:
        stmt = stmt.where(Evidence.evidence_type == evidence_type)
    rows, total = paginate(db, stmt.order_by(Evidence.created_at, Evidence.code), p)
    evs = [r[0] for r in rows]
    ids = [e.id for e in evs]
    used: dict[uuid.UUID, list[str]] = {i: [] for i in ids}
    fids: dict[uuid.UUID, list[str]] = {i: [] for i in ids}
    if ids:
        for eid, fid, code in db.execute(select(FindingEvidence.evidence_id, Finding.id, Rule.code).join(Finding, Finding.id == FindingEvidence.finding_id).join(Rule, Rule.id == Finding.rule_id)
                                         .where(FindingEvidence.evidence_id.in_(ids))):
            if code not in used[eid]:
                used[eid].append(code)
            fids[eid].append(str(fid))
        for (eid,) in db.execute(select(TimelineEvent.evidence_id).where(TimelineEvent.evidence_id.in_(ids))):
            used[eid].append("Case Timeline")
    verifiers = {u.id: u for u in db.execute(select(User).where(User.id.in_([e.verified_by for e in evs if e.verified_by]))).unique().scalars()} if any(e.verified_by for e in evs) else {}
    items = [{**evidence_dict(e, sorted(set(used[e.id])), fids[e.id], verifiers.get(e.verified_by)), "caseNumber": None} for e in evs]
    case_numbers = {c.id: c.case_number for c in db.execute(select(Case).where(Case.id.in_({e.case_id for e in evs}))).unique().scalars()} if evs else {}
    for item, e in zip(items, evs):
        item["caseNumber"] = case_numbers.get(e.case_id)
    return page_out(items, total, p)


@router.get("/{case_id}/timeline")
def case_timeline(case_id: str, ctx: Ctx = Depends(require(Perm.CASE_VIEW)), db: Session = Depends(get_db)):
    case = get_case(db, ctx.org_id, case_id)
    rows = db.execute(select(TimelineEvent).where(TimelineEvent.case_id == case.id).order_by(TimelineEvent.event_date)).scalars().all()
    ev = {e.id: e for e in db.execute(select(Evidence).where(Evidence.id.in_([t.evidence_id for t in rows if t.evidence_id]))).unique().scalars()} if rows else {}
    return [timeline_dict(t, ev.get(t.evidence_id)) for t in rows]


@router.get("/{case_id}/documents")
def case_documents(case_id: str, p: PageParams = Depends(), ctx: Ctx = Depends(require(Perm.CASE_VIEW)), db: Session = Depends(get_db)):
    case = get_case(db, ctx.org_id, case_id)
    rows, total = paginate(db, select(Document).where(Document.case_id == case.id).order_by(Document.created_at), p)
    docs = [r[0] for r in rows]
    jobs = {j.document_id: j for j in db.execute(select(ProcessingJob).where(ProcessingJob.document_id.in_([d.id for d in docs]))).scalars()} if docs else {}
    return page_out([document_dict(d, jobs.get(d.id)) for d in docs], total, p)


@router.post("/{case_id}/documents", status_code=201)
def upload_document(case_id: str, background: BackgroundTasks, file: UploadFile = File(...), ctx: Ctx = Depends(require(Perm.DOCUMENT_UPLOAD)), db: Session = Depends(get_db)):
    case = get_case(db, ctx.org_id, case_id)
    data = file.file.read(settings.max_upload_mb * 1024 * 1024 + 1)
    ext, mime = filesvc.validate_upload(file.filename, data)
    name = filesvc.display_name(file.filename)
    path = get_storage().save(filesvc.storage_key(ctx.org_id, case.id, ext), data)
    doc = Document(case_id=case.id, organization_id=ctx.org_id, uploaded_by=ctx.user.id, filename=name, file_type=mime, file_size=len(data), storage_path=path,
                   sha256=hashlib.sha256(data).hexdigest(), doc_type=filesvc.classify_doc_type(name), status=DocumentStatus.UPLOADED)
    db.add(doc)
    db.flush()
    job = ProcessingJob(document_id=doc.id, organization_id=ctx.org_id, type="EXTRACTION")
    db.add(job)
    if case.status in (CaseStatus.NEW,):
        case.status = CaseStatus.PROCESSING
    record(db, action="Document uploaded", org_id=ctx.org_id, ctx=ctx, case_id=case.id, entity_type="document", entity_id=doc.id, target=name, new={"size": len(data), "type": mime})
    db.commit()
    db.refresh(doc)
    outbox = Outbox()
    outbox.org(ctx.org_id, make_event(ws.DOCUMENT_UPLOADED, case_id=str(case.id), actor=_actor(ctx), payload={"documentId": str(doc.id), "filename": name}))
    outbox.flush()
    background.add_task(process_document, job.id)
    return document_dict(doc, job)


@router.get("/{case_id}/audit")
def case_audit(case_id: str, p: PageParams = Depends(), ctx: Ctx = Depends(require(Perm.AUDIT_VIEW)), db: Session = Depends(get_db)):
    from app.models import AuditEvent

    case = get_case(db, ctx.org_id, case_id)
    rows, total = paginate(db, select(AuditEvent).where(AuditEvent.organization_id == ctx.org_id, AuditEvent.case_id == case.id).order_by(AuditEvent.created_at.desc(), AuditEvent.id), p)
    return page_out([audit_dict(r[0]) for r in rows], total, p)
