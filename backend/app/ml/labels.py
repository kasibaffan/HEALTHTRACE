"""Document categories. Names are stable identifiers stored in the database; display text lives in LABEL_NAMES."""

CLINICAL_REPORT = "CLINICAL_REPORT"
IMAGING_REPORT = "IMAGING_REPORT"
LABORATORY_RESULT = "LABORATORY_RESULT"
REFERRAL_ORDER = "REFERRAL_ORDER"
CLAIM_BILLING = "CLAIM_BILLING"
POLICY_DOCUMENT = "POLICY_DOCUMENT"
OTHER = "OTHER"

LABELS: tuple[str, ...] = (CLINICAL_REPORT, IMAGING_REPORT, LABORATORY_RESULT, REFERRAL_ORDER, CLAIM_BILLING, POLICY_DOCUMENT, OTHER)

LABEL_NAMES: dict[str, str] = {
    CLINICAL_REPORT: "Clinical report",
    IMAGING_REPORT: "Imaging report",
    LABORATORY_RESULT: "Laboratory result",
    REFERRAL_ORDER: "Referral or order",
    CLAIM_BILLING: "Claim or billing document",
    POLICY_DOCUMENT: "Policy document",
    OTHER: "Other or unknown",
}


def is_valid_label(value: object) -> bool:
    return isinstance(value, str) and value in LABELS
