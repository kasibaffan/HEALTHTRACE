"""Synthetic demo case HT-10482. Documents are real generated PDFs that go through the same processing pipeline as user uploads."""
import hashlib
import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.service import record
from app.models import Case, Document, Evidence, Policy, ProcessingJob, TimelineEvent, User
from app.models.enums import CaseStatus, DocumentStatus, PolicyStatus, Priority
from app.services import files as filesvc
from app.services.pdfgen import make_pdf
from app.services.policy_templates import create_default_policy
from app.services.processing import next_evidence_code, process_document
from app.storage import get_storage

DEMO_CASE_NUMBER = "HT-10482"

DEMO_DOCUMENTS: list[tuple[str, list[tuple[str, list[str]]]]] = [
    ("Patient_Referral.pdf", [("Referral for Specialist Orthopaedic Review", [
        "Northfield Family Medicine | Referral ID REF-2291 | Synthetic document",
        "Patient: John Anderson | DOB: 14 Jul 1968 | Member ID: SYN-4471-0982",
        "Reason for referral: Persistent right knee pain with functional limitation.",
        "Patient completed four weeks of physiotherapy.",
        "Request for Advanced Knee Intervention submitted 02 Apr 2026.",
        "Referring clinician: Dr. M. Okafor"])]),
    ("Clinical_Notes.pdf", [
        ("Presenting History", [
            "Riverside Orthopaedic Clinic | Clinical Notes | Synthetic document",
            "05 Jan 2026 - Patient reports progressive right knee pain and stiffness over three months.",
            "Pain is worse on stairs and after prolonged standing. No history of acute trauma."]),
        ("Examination and Assessment", [
            "20 Jan 2026 - Examination: joint-line tenderness, crepitus, reduced flexion to 110 degrees.",
            "Assessment: Primary osteoarthritis of the right knee, Kellgren-Lawrence grade 3, confirmed on examination and radiograph.",
            "Plan: Begin structured conservative management."]),
        ("Conservative Treatment Review", [
            "Review dated 29 Mar 2026.",
            "Structured physiotherapy programme commenced 01 Feb 2026.",
            "Patient has completed eight weeks of physiotherapy with limited improvement.",
            "NSAIDs and activity modification continued throughout; pain score 6/10 at review."]),
        ("Treatment Plan", [
            "Conservative measures have not achieved adequate symptom control.",
            "Recommend escalation to Advanced Knee Intervention pending payer authorization."]),
        ("Sign-off", [
            "Electronically signed: Dr. A. Lindqvist, Consultant Orthopaedic Surgeon.",
            "Notes reviewed and finalised 29 Mar 2026."])]),
    ("Insurance_Policy.pdf", [
        ("Knee Intervention Policy v2.4 - Overview", [
            "Northwind Health Plan (synthetic) | Effective 01 Jan 2026",
            "This policy sets the medical-necessity criteria for advanced knee interventions.",
            "All criteria below must be met and documented before authorization."]),
        ("Criteria PR-001 and PR-002", [
            "PR-001 - A diagnosis of knee osteoarthritis must be confirmed by a treating clinician.",
            "PR-002 - Conservative treatment must be completed for a minimum of six weeks."]),
        ("Criteria PR-003 and PR-004", [
            "PR-003 - Recent MRI report required.",
            "PR-004 - The clinical indication, including treatment history, must be documented consistently across submitted documents."])]),
    ("Imaging_Report.pdf", [("Radiology Report - Plain Radiograph", [
        "Riverside Imaging | Synthetic document",
        "Examination: Weight-bearing radiograph, right knee, AP and lateral views. Date: 14 Nov 2024.",
        "Findings: Joint-space narrowing medial compartment with marginal osteophytes.",
        "Impression: Changes consistent with osteoarthritis. No MRI performed."])]),
]

TIMELINE = [
    (date(2026, 1, 5), "Symptoms reported", "Progressive right knee pain and stiffness.", "Clinical_Notes.pdf", 1, "05 Jan 2026 - Patient reports progressive right knee pain and stiffness over three months.", "progressive right knee pain and stiffness"),
    (date(2026, 1, 20), "Diagnosis established", "Primary osteoarthritis, KL grade 3.", "Clinical_Notes.pdf", 2, "Assessment: Primary osteoarthritis of the right knee, Kellgren-Lawrence grade 3, confirmed on examination and radiograph.", None),
    (date(2026, 2, 1), "Physiotherapy started", "Structured programme commenced.", "Clinical_Notes.pdf", 3, "Structured physiotherapy programme commenced 01 Feb 2026.", "commenced 01 Feb 2026"),
    (date(2026, 3, 29), "8 weeks completed", "Limited improvement documented at review.", "Clinical_Notes.pdf", 3, "Patient has completed eight weeks of physiotherapy with limited improvement.", None),
    (date(2026, 4, 2), "Procedure requested", "Advanced Knee Intervention submitted.", "Patient_Referral.pdf", 1, "Request for Advanced Knee Intervention submitted 02 Apr 2026.", "submitted 02 Apr 2026"),
]


def create_demo_case(db: Session, org_id: uuid.UUID, uploader: User, assignee: User | None, creator: User | None = None) -> Case:
    creator = creator or uploader
    policy = db.execute(select(Policy).where(Policy.organization_id == org_id, Policy.status == PolicyStatus.ACTIVE).order_by(Policy.created_at)).scalars().first()
    if not policy:
        policy = create_default_policy(db, org_id, creator.id)
    case = Case(case_number=DEMO_CASE_NUMBER, organization_id=org_id, created_by=creator.id, assigned_to=assignee.id if assignee else None, policy_id=policy.id,
                patient_reference="John Anderson", member_reference="SYN-4471-0982", condition="Knee Osteoarthritis", requested_procedure="Advanced Knee Intervention",
                requested_on=date(2026, 4, 2), status=CaseStatus.PROCESSING, priority=Priority.HIGH)
    db.add(case)
    db.flush()
    db.refresh(case)
    record(db, action="Case created", org_id=org_id, user=creator, case_id=case.id, entity_type="case", entity_id=case.id, target=case.case_number, new={"status": "NEW"})
    if assignee:
        record(db, action="Case assigned", org_id=org_id, user=creator, case_id=case.id, entity_type="case", entity_id=case.id, target=f"{case.case_number} -> {assignee.full_name}", new={"assignedTo": assignee.full_name})
    db.commit()

    storage, job_ids = get_storage(), []
    for name, pages in DEMO_DOCUMENTS:
        data = make_pdf(pages)
        path = storage.save(filesvc.storage_key(org_id, case.id, ".pdf"), data)
        doc = Document(case_id=case.id, organization_id=org_id, uploaded_by=uploader.id, filename=name, file_type="application/pdf", file_size=len(data), storage_path=path,
                       sha256=hashlib.sha256(data).hexdigest(), doc_type=filesvc.classify_doc_type(name), status=DocumentStatus.UPLOADED)
        db.add(doc)
        db.flush()
        job = ProcessingJob(document_id=doc.id, organization_id=org_id)
        db.add(job)
        record(db, action="Document uploaded", org_id=org_id, user=uploader, case_id=case.id, entity_type="document", entity_id=doc.id, target=name, new={"size": len(data)})
        db.commit()
        job_ids.append(job.id)
    for jid in job_ids:  # same pipeline as a real upload, run inline (no artificial delay) so the case is ready immediately
        process_document(jid, delay_ms=0)

    db.expire_all()
    case = db.get(Case, case.id)
    for when, label, detail, doc_name, page, sentence, highlight in TIMELINE:
        ev = db.execute(select(Evidence).join(Document, Evidence.document_id == Document.id)
                        .where(Evidence.case_id == case.id, Document.filename == doc_name, Evidence.page == page, Evidence.text == sentence)).unique().scalars().first()
        if ev is None:
            doc = db.execute(select(Document).where(Document.case_id == case.id, Document.filename == doc_name)).unique().scalar_one()
            ev = Evidence(code=f"EV-{next_evidence_code(db, org_id)}", case_id=case.id, document_id=doc.id, organization_id=org_id, evidence_type="Clinical Evidence" if "Clinical" in doc_name else "Referral Statement",
                          page=page, text=sentence, highlight=highlight, confidence=0.95, verified="Clinical" in doc_name)
            db.add(ev)
            db.flush()
        db.add(TimelineEvent(case_id=case.id, organization_id=org_id, event_date=when, label=label, detail=detail, evidence_id=ev.id))
    db.commit()
    return case
