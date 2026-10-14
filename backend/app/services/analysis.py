"""Deterministic findings engine: policy rules evaluated over persisted facts and evidence. No AI decides anything here."""
import uuid
from dataclasses import dataclass

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.audit.service import RULES_ACTOR, record
from app.models import Case, Document, Evidence, Fact, Finding, FindingEvidence, Rule
from app.models.enums import CaseStatus, EvidenceLinkRole, FindingStatus, ReviewerStatus
from app.services import rules as rules_engine
from app.services.ai import get_ai_service
from app.services.ai.base import FactView

SEVERITY = {"MATCH": "low", "CONFLICT": "medium", "INCONCLUSIVE": "medium", "MISSING": "high"}


@dataclass
class Change:
    finding: Finding
    old_status: str | None
    new_status: str
    created: bool


def _fmt(value, unit=None) -> str:
    return f"{value} {unit}".strip() if unit else str(value)


def _num(v: str):
    try:
        f = float(v)
        return int(f) if f.is_integer() else f
    except ValueError:
        return v


def _lock_case(db: Session, case_id: uuid.UUID) -> None:
    if db.bind.dialect.name == "postgresql":
        db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": str(case_id)})


def evaluate_case(db: Session, case: Case) -> list[Change]:
    """Re-evaluates every rule of the case's policy. Returns what changed so callers can audit and notify."""
    _lock_case(db, case.id)
    if not case.policy:
        return []
    ai = get_ai_service()
    docs = list(db.execute(select(Document).where(Document.case_id == case.id).order_by(Document.created_at)).scalars())
    doc_order = {d.id: i for i, d in enumerate(docs)}
    doc_names = [d.filename for d in docs]
    all_facts = list(db.execute(select(Fact).where(Fact.case_id == case.id)).scalars())
    all_evidence = list(db.execute(select(Evidence).where(Evidence.case_id == case.id)).unique().scalars())
    ev_by_fact: dict[uuid.UUID, list[Evidence]] = {}
    for e in all_evidence:
        if e.fact_id:
            ev_by_fact.setdefault(e.fact_id, []).append(e)
    conflicts = {c.fact_name: c for c in ai.detect_conflicts([FactView(str(f.id), f.name, f.label, f.value) for f in all_facts])}
    existing = {f.rule_id: f for f in db.execute(select(Finding).where(Finding.case_id == case.id)).scalars()}

    def ordered(evs: list[Evidence]) -> list[Evidence]:
        return sorted(evs, key=lambda e: (doc_order.get(e.document_id, 0), e.page))

    changes: list[Change] = []
    for rule in case.policy.rules:
        facts = [f for f in all_facts if f.name == rule.fact_name]
        supporting_ev: list[Evidence] = []
        primary: Fact | None = None
        actual_display, result, status, explanation = "", None, FindingStatus.MISSING, ""

        if rule.operator == "consistent":
            distinct = {f.value for f in facts}
            supporting_ev = ordered([e for f in facts for e in ev_by_fact.get(f.id, [])])
            if not facts:
                status = FindingStatus.MISSING
                actual_display, explanation = "no evidence found", "No documents contain this information. No evidence has been inferred or fabricated."
            elif len(distinct) == 1:
                result, status = True, FindingStatus.MATCH
                primary = facts[0]
                actual_display = "1 == 1"
                explanation = f"All sources agree: {_fmt(primary.value, primary.unit)}."
            else:
                result, status = False, FindingStatus.CONFLICT
                conflict = conflicts.get(rule.fact_name)
                fact_order = sorted(conflict.fact_ids if conflict else [str(f.id) for f in facts],
                                    key=lambda fid: doc_order.get(next(e.document_id for e in all_evidence if str(e.fact_id) == fid), 0))
                primary = next(f for f in facts if str(f.id) == fact_order[0])
                actual_display = f"{len(distinct)} == 1"
                by_id = {str(f.id): f for f in facts}
                explanation = (f"{facts[0].label} differs between sources: " + " vs ".join(_fmt(by_id[i].value, by_id[i].unit) for i in fact_order)
                               + ". The system does not choose which source is correct; a reviewer must resolve it.")
        else:
            if not facts:
                status = FindingStatus.MISSING
                actual_display = "no qualifying evidence found"
                explanation = f"{len(doc_names)} documents were searched and no qualifying evidence was found. No evidence has been inferred or fabricated."
            else:
                trusted = [f for f in facts if all(e.verified for e in ev_by_fact.get(f.id, []))] or facts
                primary = max(trusted, key=lambda f: f.confidence)
                supporting_ev = ordered(ev_by_fact.get(primary.id, []))
                threshold = _num(rule.threshold) if rule.threshold is not None else None
                result = rules_engine.evaluate(rule.operator, _num(primary.value), threshold)
                actual_display = rules_engine.describe(rule.operator, _num(primary.value), threshold)
                if result:
                    status = FindingStatus.MATCH
                    explanation = f"Rule evaluated deterministically: {actual_display} is TRUE, supported by extracted evidence."
                else:
                    status = FindingStatus.INCONCLUSIVE
                    explanation = f"Evidence was found but the rule is not satisfied: {actual_display} is FALSE. A reviewer should confirm."

        near = ordered([e for e in all_evidence if e.topic == rule.fact_name and e.fact_id is None])
        prev = existing.get(rule.id)
        finding = prev or Finding(case_id=case.id, organization_id=case.organization_id, policy_id=case.policy_id, rule_id=rule.id)
        old_status = prev.status.value if prev else None
        old_links = {(l.evidence_id, l.role) for l in prev.links} if prev else set()

        finding.status, finding.severity, finding.explanation = status, SEVERITY[status.value], explanation
        finding.fact_id = primary.id if primary else None
        finding.evaluation, finding.rule_result = actual_display, result
        finding.searched_documents = doc_names
        finding.expected_evidence = rule.expected_evidence if status == FindingStatus.MISSING else None
        finding.suggested_action = (rule.suggested_action if status in (FindingStatus.MISSING, FindingStatus.CONFLICT) else None) or (
            "Confirm the correct value with the treating clinician or request a corrected document." if status == FindingStatus.CONFLICT else None)

        new_links = [(e.id, EvidenceLinkRole.SUPPORTING, i) for i, e in enumerate(supporting_ev)] + [(e.id, EvidenceLinkRole.REVIEWED, i) for i, e in enumerate(near)]
        status_changed = prev is None or prev.status != status
        if prev is None:
            db.add(finding)
            db.flush()
        if {(a, b) for a, b, _ in new_links} != old_links:
            finding.links[:] = [FindingEvidence(finding_id=finding.id, evidence_id=a, role=b, position=c) for a, b, c in new_links]
            if not status_changed:
                finding.version += 1
        if status_changed:
            if prev is not None:
                finding.version += 1
            finding.reviewer_status = ReviewerStatus.PENDING
            finding.reviewed_by = finding.reviewed_at = finding.review_reason = None
            changes.append(Change(finding, old_status, status.value, prev is None))
        db.flush()
    _refresh_case(db, case)
    return changes


def _refresh_case(db: Session, case: Case) -> None:
    findings = list(db.execute(select(Finding).where(Finding.case_id == case.id)).scalars())
    missing = sum(f.status == FindingStatus.MISSING for f in findings)
    conflict = sum(f.status == FindingStatus.CONFLICT for f in findings)
    docs = db.execute(select(Document).where(Document.case_id == case.id)).scalars().all()
    case.review_complexity = min(100, 28 + 20 * missing + 22 * conflict + 3 * len(docs))
    counts: dict[str, int] = {}
    titles: dict[str, list[str]] = {}
    for f in findings:
        counts[f.status.value] = counts.get(f.status.value, 0) + 1
        titles.setdefault(f.status.value, []).append(f.rule.finding_title or f.rule.name)
    case.summary = get_ai_service().summarize_case(counts, titles)
    if findings and case.status in (CaseStatus.NEW, CaseStatus.PROCESSING):
        case.status = CaseStatus.NEEDS_REVIEW


def log_changes(db: Session, case: Case, changes: list[Change]) -> None:
    for c in changes:
        f, rule = c.finding, c.finding.rule
        record(db, action="Rule evaluated", org_id=case.organization_id, case_id=case.id, actor_label=RULES_ACTOR, actor_kind="SYSTEM",
               entity_type="finding", entity_id=f.id, target=f"{rule.code}: {f.evaluation}", reason=f"Result: {str(f.rule_result).upper() if f.rule_result is not None else 'NO EVIDENCE'}")
        label = {"MATCH": "Criterion satisfied", "MISSING": "Evidence missing", "CONFLICT": "Potential conflict flagged", "INCONCLUSIVE": "Criterion inconclusive"}[c.new_status]
        record(db, action=label if c.created else f"Finding re-evaluated: {c.old_status} -> {c.new_status}", org_id=case.organization_id, case_id=case.id,
               actor_label=RULES_ACTOR, actor_kind="SYSTEM", entity_type="finding", entity_id=f.id, target=f"{rule.code} {rule.finding_title or rule.name}",
               old={"status": c.old_status} if c.old_status else None, new={"status": c.new_status},
               reason="Routed to human review." if c.new_status != "MATCH" else None)
