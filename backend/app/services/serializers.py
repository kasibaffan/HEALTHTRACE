from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth.permissions import permissions_for
from app.models import Case, Document, Evidence, Finding, Organization, TimelineEvent, User
from app.models.accounts import OrganizationMember
from app.models.enums import EvidenceLinkRole, FindingStatus


def iso(dt) -> str | None:
    return dt.isoformat() if dt else None


def user_dict(u: User | None) -> dict | None:
    if not u:
        return None
    return {"id": str(u.id), "fullName": u.full_name, "email": u.email, "avatarUrl": u.avatar_url, "isActive": u.is_active, "isVerified": u.is_verified,
            "createdAt": iso(u.created_at), "lastLoginAt": iso(u.last_login_at), "lastSeenAt": iso(u.last_seen_at)}


def person(u: User | None) -> dict | None:
    return {"id": str(u.id), "fullName": u.full_name, "avatarUrl": u.avatar_url} if u else None


def org_dict(o: Organization) -> dict:
    return {"id": str(o.id), "name": o.name, "slug": o.slug, "createdAt": iso(o.created_at)}


def me_dict(user: User, org: Organization, role) -> dict:
    return {"user": user_dict(user), "organization": org_dict(org), "role": role.value, "permissions": permissions_for(role)}


def member_dict(u: User, m: OrganizationMember) -> dict:
    return {**user_dict(u), "role": m.role.value, "joinedAt": iso(m.created_at), "status": "active" if u.is_active else "deactivated"}


def case_dict(c: Case, missing: int = 0, conflicts: int = 0, documents: int = 0) -> dict:
    return {
        "id": str(c.id), "caseNumber": c.case_number, "patientReference": c.patient_reference, "memberReference": c.member_reference,
        "condition": c.condition, "requestedProcedure": c.requested_procedure, "requestedOn": iso(c.requested_on), "status": c.status.value,
        "priority": c.priority.value, "reviewComplexity": c.review_complexity, "summary": c.summary,
        "assignedTo": person(c.assignee), "createdBy": person(c.creator), "policyName": f"{c.policy.name} {c.policy.version}" if c.policy else None,
        "missingEvidence": missing, "conflicts": conflicts, "documentCount": documents, "createdAt": iso(c.created_at), "updatedAt": iso(c.updated_at),
    }


def case_counts(db: Session, case_ids: list) -> dict:
    counts = {cid: {"missing": 0, "conflicts": 0, "documents": 0} for cid in case_ids}
    if not case_ids:
        return counts
    for cid, status, n in db.execute(select(Finding.case_id, Finding.status, func.count()).where(Finding.case_id.in_(case_ids)).group_by(Finding.case_id, Finding.status)):
        if status == FindingStatus.MISSING:
            counts[cid]["missing"] = n
        elif status == FindingStatus.CONFLICT:
            counts[cid]["conflicts"] = n
    for cid, n in db.execute(select(Document.case_id, func.count()).where(Document.case_id.in_(case_ids)).group_by(Document.case_id)):
        counts[cid]["documents"] = n
    return counts


def case_with_counts(db: Session, c: Case) -> dict:
    n = case_counts(db, [c.id])[c.id]
    return case_dict(c, n["missing"], n["conflicts"], n["documents"])


def classification_dict(d: Document) -> dict:
    """ML document-type suggestion plus any human correction. `score` is an uncalibrated model output: never show it as a percentage."""
    return {"status": d.ml_status or "NOT_RUN", "label": d.ml_label, "score": d.ml_score, "lowConfidence": bool(d.ml_low_confidence), "modelVersion": d.ml_model_version,
            "classifiedAt": iso(d.ml_classified_at), "reviewedLabel": d.reviewed_label, "reviewedBy": person(d.label_reviewer), "reviewedAt": iso(d.reviewed_label_at),
            "effectiveLabel": d.reviewed_label or d.ml_label}


def document_dict(d: Document, job=None) -> dict:
    return {"id": str(d.id), "caseId": str(d.case_id), "filename": d.filename, "fileType": d.file_type, "fileSize": d.file_size, "docType": d.doc_type,
            "status": d.status.value, "pageCount": d.page_count, "uploadedBy": person(d.uploader), "createdAt": iso(d.created_at),
            "progress": job.progress if job else (100 if d.status.value == "PROCESSED" else 0), "error": job.error_message if job else None,
            "classification": classification_dict(d)}


def fact_summary(e: Evidence) -> str | None:
    f = e.fact
    return f"{f.label}: {f.value}{(' ' + f.unit) if f.unit else ''}" if f else None


def evidence_dict(e: Evidence, used_by: list[str] | None = None, finding_ids: list[str] | None = None, verifier: User | None = None) -> dict:
    return {"id": str(e.id), "code": e.code, "caseId": str(e.case_id), "documentId": str(e.document_id), "documentName": e.document.filename, "page": e.page,
            "text": e.text, "highlight": e.highlight, "evidenceType": e.evidence_type, "verified": e.verified, "verifiedBy": person(verifier),
            "verifiedAt": iso(e.verified_at), "note": e.note, "factSummary": fact_summary(e), "confidence": e.confidence, "usedBy": used_by or [],
            "findingIds": finding_ids or [], "createdAt": iso(e.created_at)}


def finding_dict(f: Finding, evidence_by_id: dict | None = None) -> dict:
    supporting = sorted([l for l in f.links if l.role == EvidenceLinkRole.SUPPORTING], key=lambda l: l.position)
    reviewed = sorted([l for l in f.links if l.role == EvidenceLinkRole.REVIEWED], key=lambda l: l.position)
    fact_ids: list[str] = []
    if evidence_by_id:
        for l in supporting:
            ev = evidence_by_id.get(l.evidence_id)
            if ev and ev.fact_id and str(ev.fact_id) not in fact_ids:
                fact_ids.append(str(ev.fact_id))
    if f.fact_id and str(f.fact_id) not in fact_ids:
        fact_ids.insert(0, str(f.fact_id))
    review = None
    if f.reviewer_status.value != "PENDING":
        review = {"reviewer": f.reviewer.full_name if f.reviewer else "Unknown", "action": f.reviewer_status.value, "reason": f.review_reason, "timestamp": iso(f.reviewed_at)}
    r = f.rule
    return {
        "id": str(f.id), "caseId": str(f.case_id), "criterionId": r.code, "criterion": r.finding_title or r.name, "requirement": r.requirement,
        "status": f.status.value, "severity": f.severity, "factId": str(f.fact_id) if f.fact_id else None, "factIds": fact_ids, "ruleId": str(f.rule_id),
        "evidenceIds": [str(l.evidence_id) for l in supporting], "reviewedEvidenceIds": [str(l.evidence_id) for l in reviewed], "explanation": f.explanation,
        "searchedDocuments": f.searched_documents or [], "expectedEvidence": f.expected_evidence, "suggestedAction": f.suggested_action,
        "reviewerStatus": f.reviewer_status.value, "review": review, "version": f.version, "evaluation": f.evaluation, "ruleResult": f.rule_result, "updatedAt": iso(f.updated_at),
    }


def timeline_dict(t: TimelineEvent, ev: Evidence | None) -> dict:
    return {"id": str(t.id), "date": t.event_date.strftime("%b %d"), "isoDate": t.event_date.isoformat(), "label": t.label, "detail": t.detail or "",
            "evidence": {"id": str(ev.id), "code": ev.code, "documentId": str(ev.document_id), "documentName": ev.document.filename, "page": ev.page} if ev else None}
