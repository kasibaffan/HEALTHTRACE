"""Asynchronous document processing: extract text -> AI facts (validated) -> evidence -> rules -> notify."""
import logging
import time
import uuid
from datetime import date, datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit.service import AI_ACTOR, audit_dict, record
from app.core.config import settings
from app.database.session import SessionLocal
from app.models import Case, Document, DocumentPage, Evidence, Fact, ProcessingJob
from app.models.enums import DocumentStatus, JobStatus
from app.services import analysis
from app.services.classification import classify_document
from app.services.ai import get_ai_service
from app.services.notify import notify
from app.services.text_extraction import extract_pages, normalize
from app.storage import get_storage
from app.websocket import manager as ws
from app.websocket.manager import Outbox, make_event

log = logging.getLogger("healthtrace.processing")
ALLOWED_FACTS = {"physiotherapy_duration", "diagnosis", "mri_report_age_months"}


def next_evidence_code(db: Session, org_id: uuid.UUID) -> int:
    codes = db.execute(select(Evidence.code).where(Evidence.organization_id == org_id)).scalars().all()
    nums = [int(c[3:]) for c in codes if c.startswith("EV-") and c[3:].isdigit()]
    return max(nums, default=82930) + 1


def _progress(db: Session, job: ProcessingJob, doc: Document, pct: int, outbox: Outbox, actor: dict | None, delay_ms: int = 0) -> None:
    job.progress = pct
    db.commit()
    outbox.org(doc.organization_id, make_event(ws.DOCUMENT_PROCESSING, case_id=str(doc.case_id), actor=actor,
                                               payload={"documentId": str(doc.id), "filename": doc.filename, "status": "PROCESSING", "progress": pct}))
    outbox.flush()
    if delay_ms:
        time.sleep(delay_ms / 1000)


def process_document(job_id: uuid.UUID, delay_ms: int | None = None) -> None:
    db = SessionLocal()
    try:
        _run(db, job_id, settings.processing_step_delay_ms if delay_ms is None else delay_ms)
    except Exception as exc:  # noqa: BLE001 - job failure must never crash the worker thread
        db.rollback()
        log.exception("document processing failed")
        _fail(db, job_id, exc)
    finally:
        db.close()


def _fail(db: Session, job_id: uuid.UUID, exc: Exception) -> None:
    job = db.get(ProcessingJob, job_id)
    if not job:
        return
    doc = db.get(Document, job.document_id)
    job.status, job.progress, job.completed_at = JobStatus.FAILED, 0, datetime.now(timezone.utc)
    job.error_message = "The document could not be processed. It may be corrupted, encrypted, or unreadable."
    doc.status = DocumentStatus.FAILED
    record(db, action="Document processing failed", org_id=doc.organization_id, case_id=doc.case_id, actor_label=AI_ACTOR, actor_kind="AI",
           entity_type="document", entity_id=doc.id, target=doc.filename, reason=type(exc).__name__)
    db.commit()
    Outbox_ = Outbox()
    Outbox_.org(doc.organization_id, make_event(ws.DOCUMENT_PROCESSED, case_id=str(doc.case_id), payload={"documentId": str(doc.id), "filename": doc.filename, "status": "FAILED"}))
    Outbox_.flush()


def _run(db: Session, job_id: uuid.UUID, delay_ms: int) -> None:
    outbox = Outbox()
    job = db.get(ProcessingJob, job_id)
    doc = db.get(Document, job.document_id)
    case = db.get(Case, doc.case_id)
    uploader = doc.uploader
    actor = {"id": str(uploader.id), "fullName": uploader.full_name} if uploader else None

    job.status, job.started_at, doc.status = JobStatus.PROCESSING, datetime.now(timezone.utc), DocumentStatus.PROCESSING
    _progress(db, job, doc, 10, outbox, actor, delay_ms)

    ext = "." + doc.filename.rsplit(".", 1)[-1].lower()
    pages = extract_pages(get_storage().read(doc.storage_path), ext)
    db.query(DocumentPage).filter(DocumentPage.document_id == doc.id).delete()
    for i, text in enumerate(pages, start=1):
        db.add(DocumentPage(document_id=doc.id, page_number=i, text=text))
    doc.page_count = len(pages)
    classify_document(db, doc, pages)  # ML suggestion only; failures degrade to a status and never stop processing
    _progress(db, job, doc, 35, outbox, actor, delay_ms)

    ai = get_ai_service()
    reference = case.requested_on or date.today()
    items = ai.extract_facts(doc.doc_type, pages, reference)
    _progress(db, job, doc, 60, outbox, actor, delay_ms)

    page_norm = [normalize(p) for p in pages]
    code_no = next_evidence_code(db, doc.organization_id)
    added = 0
    for it in items:
        # Validation gate: never persist AI output that is not verbatim in the source page or is outside the allowed schema.
        if not (1 <= it.page <= len(pages)) or normalize(it.text) not in page_norm[it.page - 1]:
            log.warning("discarded AI item: quote not found in source page")
            continue
        if it.fact_name and it.fact_name not in ALLOWED_FACTS:
            continue
        fact = None
        if it.fact_name:
            fact = Fact(case_id=case.id, organization_id=case.organization_id, name=it.fact_name, label=it.fact_label or it.fact_name,
                        value=str(it.fact_value), unit=it.fact_unit, confidence=it.confidence, source=ai.name)
            db.add(fact)
            db.flush()
        db.add(Evidence(code=f"EV-{code_no}", case_id=case.id, document_id=doc.id, organization_id=case.organization_id, fact_id=fact.id if fact else None,
                        evidence_type=it.evidence_type, page=it.page, text=it.text, highlight=it.highlight, topic=it.topic,
                        confidence=it.confidence, verified=it.verified, note=it.note))
        code_no += 1
        added += 1
        db.flush()
        if fact:
            record(db, action="AI extracted", org_id=case.organization_id, case_id=case.id, actor_label=AI_ACTOR, actor_kind="AI", entity_type="fact",
                   entity_id=fact.id, target=f"{fact.label} = {(fact.value + ' ' + fact.unit) if fact.unit else fact.value}", reason=f"{doc.filename}, page {it.page}")
    _progress(db, job, doc, 80, outbox, actor, delay_ms)

    changes = analysis.evaluate_case(db, case)
    analysis.log_changes(db, case, changes)
    for c in changes:
        outbox.org(case.organization_id, make_event(ws.FINDING_UPDATED, case_id=str(case.id), payload={"findingId": str(c.finding.id), "status": c.new_status, "previousStatus": c.old_status, "reason": "reevaluated"}))
        if not c.created:
            notify(db, outbox, org_id=case.organization_id, user_ids=[case.assigned_to, case.created_by], type_="FINDING_CHANGED", title=f"Finding changed on {case.case_number}",
                   message=f"{c.finding.rule.finding_title or c.finding.rule.name}: {c.old_status} -> {c.new_status} after new evidence.", case_id=case.id)

    doc.status, job.status, job.progress, job.completed_at = DocumentStatus.PROCESSED, JobStatus.COMPLETED, 100, datetime.now(timezone.utc)
    ev = record(db, action="Document processed", org_id=case.organization_id, case_id=case.id, actor_label=AI_ACTOR, actor_kind="AI", entity_type="document",
                entity_id=doc.id, target=doc.filename, reason=f"{doc.page_count} page(s), {added} evidence item(s) extracted")
    notify(db, outbox, org_id=case.organization_id, user_ids=[case.assigned_to, case.created_by], type_="DOCUMENT_PROCESSED", title=f"New evidence on {case.case_number}",
           message=f"{doc.filename} was processed: {added} evidence item(s).", case_id=case.id, exclude=doc.uploaded_by)
    db.commit()
    total = db.execute(select(func.count()).select_from(Evidence).where(Evidence.case_id == case.id)).scalar_one()
    outbox.org(case.organization_id, make_event(ws.DOCUMENT_PROCESSED, case_id=str(case.id), actor=actor, payload={"documentId": str(doc.id), "filename": doc.filename, "status": "PROCESSED", "evidenceAdded": added}))
    if added:
        outbox.org(case.organization_id, make_event(ws.EVIDENCE_ADDED, case_id=str(case.id), actor=actor, payload={"count": added, "total": total, "documentId": str(doc.id)}))
    outbox.org(case.organization_id, make_event(ws.CASE_UPDATED, case_id=str(case.id), actor=actor, payload={"status": case.status.value, "reason": "processed"}))
    outbox.org(case.organization_id, make_event(ws.AUDIT_EVENT, case_id=str(case.id), payload=audit_dict(ev)))
    outbox.flush()
