import uuid

from sqlalchemy.orm import Session

from app.models import Policy, Rule
from app.models.enums import PolicyStatus

KNEE_POLICY = {
    "name": "Knee Intervention Policy", "version": "v2.4", "description": "Medical-necessity criteria for advanced knee interventions (synthetic).",
    "rules": [
        dict(code="PR-001", name="Diagnosis confirmed", finding_title="Diagnosis confirmed",
             requirement="A diagnosis of knee osteoarthritis must be confirmed by a treating clinician.", fact_name="diagnosis", operator="contains", threshold="osteoarthritis",
             expression="diagnosis contains 'osteoarthritis'", expected_evidence="Clinical diagnosis note", suggested_action="Request the treating clinician's assessment.",
             source_document_name="Insurance_Policy.pdf", source_page=2, source_text="PR-001 - A diagnosis of knee osteoarthritis must be confirmed by a treating clinician."),
        dict(code="PR-002", name="Conservative treatment >= 6 weeks", finding_title="Conservative treatment ≥ 6 weeks",
             requirement="Conservative treatment must be completed for a minimum of six weeks.", fact_name="physiotherapy_duration", operator=">=", threshold="6", unit="weeks",
             expression="physiotherapy_duration >= 6 weeks", expected_evidence="Physiotherapy record", suggested_action="Request physiotherapy records.",
             source_document_name="Insurance_Policy.pdf", source_page=2, source_text="PR-002 - Conservative treatment must be completed for a minimum of six weeks."),
        dict(code="PR-003", name="Recent MRI required", finding_title="Recent MRI required", requirement="Recent MRI report required.", fact_name="mri_report_age_months",
             operator="<=", threshold="12", unit="months", expression="mri_report_age_months <= 12 months", expected_evidence="MRI / imaging report",
             suggested_action="Request imaging documentation.", source_document_name="Insurance_Policy.pdf", source_page=3, source_text="PR-003 - Recent MRI report required."),
        dict(code="PR-004", name="Clinical indication documented", finding_title="Physiotherapy duration",
             requirement="The clinical indication, including treatment history, must be documented consistently across submitted documents.", fact_name="physiotherapy_duration",
             operator="consistent", threshold=None, expression="distinct(physiotherapy_duration across sources) == 1", expected_evidence="Consistent treatment history",
             suggested_action="Confirm the correct value with the treating clinician or request a corrected document.",
             source_document_name="Insurance_Policy.pdf", source_page=3,
             source_text="PR-004 - The clinical indication, including treatment history, must be documented consistently across submitted documents."),
    ],
}


def create_default_policy(db: Session, org_id: uuid.UUID, created_by: uuid.UUID | None) -> Policy:
    policy = Policy(organization_id=org_id, name=KNEE_POLICY["name"], version=KNEE_POLICY["version"], description=KNEE_POLICY["description"],
                    status=PolicyStatus.ACTIVE, created_by=created_by)
    for i, r in enumerate(KNEE_POLICY["rules"]):
        policy.rules.append(Rule(sort_order=i, **r))
    db.add(policy)
    db.flush()
    return policy
