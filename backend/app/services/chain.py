"""Builds the Evidence Passport chain from persisted records: Finding -> Rule/Policy -> Fact -> Evidence -> Document -> Page -> Text."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Document, Evidence, Fact, Finding
from app.models.enums import FindingStatus
from app.services.serializers import evidence_dict, finding_dict


def _fmt(value, unit=None) -> str:
    return f"{value} {unit}".strip() if unit else str(value)


def _node(id_, kind, title, subtitle=None, tone="neutral", lane=None, metadata=None, document_id=None, page=None, evidence_id=None, quote=None):
    return {"id": id_, "kind": kind, "title": title, "subtitle": subtitle, "tone": tone, "lane": lane, "metadata": metadata or {},
            "documentId": document_id, "page": page, "evidenceId": evidence_id, "quote": quote}


def build_chain(db: Session, finding: Finding, ai_name: str) -> dict:
    rule, policy = finding.rule, finding.rule.policy
    ev_ids = {l.evidence_id for l in finding.links}
    evidence = {e.id: e for e in db.execute(select(Evidence).where(Evidence.id.in_(ev_ids))).unique().scalars()} if ev_ids else {}
    supporting = [evidence[l.evidence_id] for l in sorted(finding.links, key=lambda l: l.position) if l.role.value == "SUPPORTING" and l.evidence_id in evidence]
    reviewed = [evidence[l.evidence_id] for l in sorted(finding.links, key=lambda l: l.position) if l.role.value == "REVIEWED" and l.evidence_id in evidence]
    facts_by_id = {f.id: f for f in db.execute(select(Fact).where(Fact.id.in_({e.fact_id for e in supporting if e.fact_id} | ({finding.fact_id} if finding.fact_id else set())))).scalars()} if (supporting or finding.fact_id) else {}
    ordered_facts: list[Fact] = []
    for e in supporting:
        f = facts_by_id.get(e.fact_id)
        if f and f not in ordered_facts:
            ordered_facts.append(f)
    if finding.status == FindingStatus.MATCH and finding.fact_id in facts_by_id:
        ordered_facts = [facts_by_id[finding.fact_id]]
        supporting = [e for e in supporting if e.fact_id == finding.fact_id] or supporting

    source_doc = None
    if rule.source_document_name:
        source_doc = db.execute(select(Document).where(Document.case_id == finding.case_id, Document.filename == rule.source_document_name)).scalar_one_or_none()
    tone = {"MATCH": "match", "MISSING": "missing", "CONFLICT": "conflict", "INCONCLUSIVE": "conflict"}[finding.status.value]

    chain = [
        _node("n-policy", "policy", rule.code, rule.requirement, "neutral", document_id=str(source_doc.id) if source_doc else None, page=rule.source_page, quote=rule.source_text,
              metadata={"Policy": f"{policy.name} {policy.version}", "Criterion": rule.name,
                        **({"Source": f"{rule.source_document_name}, page {rule.source_page}"} if rule.source_document_name else {}),
                        **({"Policy text": f'"{rule.source_text}"'} if rule.source_text else {})}),
        _node("n-rule", "rule", rule.expression, f"Evaluated: {finding.evaluation}" + (f" = {str(finding.rule_result).upper()}" if finding.rule_result is not None else ""), tone,
              metadata={"Rule": rule.code, "Operator": rule.operator, "Threshold": _fmt(rule.threshold, rule.unit) if rule.threshold else "n/a",
                        "Evaluation": finding.evaluation or "", "Result": str(finding.rule_result).upper() if finding.rule_result is not None else "NO EVIDENCE", "Evaluated by": "Deterministic rules engine"}),
    ]
    lane_labels: dict[str, str] = {}
    if finding.status == FindingStatus.MISSING:
        chain[1]["kind"], chain[1]["title"], chain[1]["subtitle"] = "requirement", "Requirement", rule.requirement
        chain[1]["metadata"] = {"Requirement": rule.requirement, "Rule": rule.expression, "Evaluated": finding.evaluation or ""}
        chain.append(_node("n-search", "search", "Document search", f"{len(finding.searched_documents or [])} documents searched", "missing",
                           metadata={"Searched": ", ".join(finding.searched_documents or []), "Expected evidence": finding.expected_evidence or "", "Searched by": f"AI ({ai_name})"}))
        chain.append(_node("n-none", "evidence", "No supporting evidence", "Nothing qualifying was found", "missing",
                           metadata={"Evidence found": "None", "Reviewed but non-qualifying": "; ".join(f"{e.document.filename} p{e.page}: {e.note or e.text}" for e in reviewed) or "None"}))
        chain.append(_node("n-outcome", "outcome", "MISSING", finding.suggested_action, "missing", metadata={"Status": "Missing evidence", "Suggested action": finding.suggested_action or ""}))
    else:
        lanes = ("A", "B") if finding.status == FindingStatus.CONFLICT else (None,)
        if lanes[0]:
            lane_labels = {"A": "Source A", "B": "Source B"}
        pairs = [(e, e.fact) for e in supporting if e.fact] if lanes[0] else [(supporting[0], supporting[0].fact)] if supporting and supporting[0].fact else []
        if lanes[0]:
            firsts: dict = {}
            for e, f in pairs:
                firsts.setdefault(str(f.id), (e, f))
            pairs = list(firsts.values())[:2]
        for idx, (e, f) in enumerate(pairs):
            lane = lanes[idx] if lanes[0] else None
            chain.append(_node(f"n-{f.id}", "fact", _fmt(f.value, f.unit), f.label, tone, lane,
                               {"Fact": f.name, "Value": _fmt(f.value, f.unit), "Extraction confidence": f"{f.confidence:.0%}", "Extracted by": f"AI ({f.source})"}))
            chain.append(_node(f"n-{e.id}", "evidence", e.code, f'"{e.text}"', tone, lane, document_id=str(e.document_id), page=e.page, evidence_id=str(e.id),
                               metadata={"Evidence ID": e.code, "Type": e.evidence_type, "Status": "Verified" if e.verified else "Not verified", "Exact text": f'"{e.text}"'}))
            chain.append(_node(f"n-doc-{e.id}", "document", e.document.filename, f"Page {e.page}", tone, lane, document_id=str(e.document_id), page=e.page, evidence_id=str(e.id),
                               metadata={"Document": e.document.filename, "Page": str(e.page), "Action": "Open Source Document to see the highlighted passage"}))
        if finding.status in (FindingStatus.CONFLICT, FindingStatus.INCONCLUSIVE):
            chain.append(_node("n-outcome", "outcome", "Requires human review", "Not resolved automatically", "conflict", metadata={"Status": finding.status.value.title(), "Note": "The system does not pick a winner"}))

    facts_out = [{"id": str(f.id), "name": f.name, "label": f.label, "value": f.value, "unit": f.unit, "confidence": f.confidence,
                  "sourceEvidenceIds": [str(e.id) for e in supporting if e.fact_id == f.id]} for f in ordered_facts]
    evidence_full = {e.id: e for e in supporting + reviewed}
    return {
        "finding": finding_dict(finding, evidence_full),
        "criterion": {"id": rule.code, "title": rule.name, "requirement": rule.requirement, "ruleId": str(rule.id), "sourceEvidenceId": ""},
        "rule": {"id": str(rule.id), "criterionId": rule.code, "expression": rule.expression, "operator": rule.operator, "threshold": rule.threshold, "unit": rule.unit,
                 "actual": finding.evaluation, "result": finding.rule_result, "evaluation": finding.evaluation or ""},
        "facts": facts_out, "evidence": [evidence_dict(e) for e in supporting], "reviewedEvidence": [evidence_dict(e) for e in reviewed],
        "chain": chain, "laneLabels": lane_labels,
    }
