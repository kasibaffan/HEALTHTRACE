"""Entirely synthetic demo data for case HT-10482. No real patient information."""

CASE_ID = "HT-10482"

CASE = {
    "id": CASE_ID,
    "patient": "John Anderson",
    "condition": "Knee Osteoarthritis",
    "procedure": "Advanced Knee Intervention",
    "complexity": 82,
    "date_of_birth": "1968-07-14",
    "member_id": "SYN-4471-0982",
    "requested_on": "2026-04-02",
    "policy_name": "Knee Intervention Policy",
    "payer": "Northwind Health Plan (synthetic)",
}

OTHER_CASES = [
    {"id": "HT-10467", "patient": "Maria Delgado", "condition": "Lumbar Radiculopathy", "procedure": "Epidural Steroid Injection",
     "status": "Needs Review", "complexity": 64, "missing_evidence": 2, "conflicts": 0, "updated": "Today"},
    {"id": "HT-10455", "patient": "Priya Raman", "condition": "Sleep Apnea", "procedure": "CPAP Authorization",
     "status": "In Progress", "complexity": 38, "missing_evidence": 0, "conflicts": 1, "updated": "Yesterday"},
    {"id": "HT-10431", "patient": "Robert Whitfield", "condition": "Chronic Migraine", "procedure": "CGRP Inhibitor Therapy",
     "status": "Ready for Decision", "complexity": 27, "missing_evidence": 0, "conflicts": 0, "updated": "2 days ago"},
]

POLICY = {
    "name": "Knee Intervention Policy",
    "version": "v2.4",
    "payer": "Northwind Health Plan (synthetic)",
    "criteria": [
        {"id": "PR-001", "title": "Diagnosis confirmed",
         "requirement": "A diagnosis of knee osteoarthritis must be confirmed by a treating clinician.",
         "rule_id": "RULE-002", "source_evidence_id": "EV-82940"},
        {"id": "PR-002", "title": "Conservative treatment >= 6 weeks",
         "requirement": "Conservative treatment must be completed for a minimum of six weeks.",
         "rule_id": "RULE-001", "source_evidence_id": "EV-82934"},
        {"id": "PR-003", "title": "Recent MRI required",
         "requirement": "Recent MRI report required.",
         "rule_id": "RULE-003", "source_evidence_id": "EV-82935"},
        {"id": "PR-004", "title": "Clinical indication documented",
         "requirement": "The clinical indication, including treatment history, must be documented consistently across submitted documents.",
         "rule_id": "RULE-004", "source_evidence_id": "EV-82941"},
    ],
}

DOCUMENTS = [
    {"id": "DOC-1", "name": "Patient_Referral.pdf", "type": "Referral", "pages": 1, "content": [
        {"number": 1, "heading": "Referral for Specialist Orthopaedic Review", "lines": [
            "Northfield Family Medicine  |  Referral ID REF-2291  |  Synthetic document",
            "Patient: John Anderson    DOB: 14 Jul 1968    Member ID: SYN-4471-0982",
            "Reason for referral: Persistent right knee pain with functional limitation.",
            "Patient completed four weeks of physiotherapy.",
            "Request for Advanced Knee Intervention submitted 02 Apr 2026.",
            "Referring clinician: Dr. M. Okafor",
        ]}]},
    {"id": "DOC-2", "name": "Clinical_Notes.pdf", "type": "Clinical", "pages": 5, "content": [
        {"number": 1, "heading": "Presenting History", "lines": [
            "Riverside Orthopaedic Clinic  |  Clinical Notes  |  Synthetic document",
            "05 Jan 2026 - Patient reports progressive right knee pain and stiffness over three months.",
            "Pain is worse on stairs and after prolonged standing. No history of acute trauma.",
        ]},
        {"number": 2, "heading": "Examination and Assessment", "lines": [
            "20 Jan 2026 - Examination: joint-line tenderness, crepitus, reduced flexion to 110 degrees.",
            "Assessment: Primary osteoarthritis of the right knee, Kellgren-Lawrence grade 3, confirmed on examination and radiograph.",
            "Plan: Begin structured conservative management.",
        ]},
        {"number": 3, "heading": "Conservative Treatment Review", "lines": [
            "Review dated 29 Mar 2026.",
            "Structured physiotherapy programme commenced 01 Feb 2026.",
            "Patient has completed eight weeks of physiotherapy with limited improvement.",
            "NSAIDs and activity modification continued throughout; pain score 6/10 at review.",
        ]},
        {"number": 4, "heading": "Treatment Plan", "lines": [
            "Conservative measures have not achieved adequate symptom control.",
            "Recommend escalation to Advanced Knee Intervention pending payer authorization.",
        ]},
        {"number": 5, "heading": "Sign-off", "lines": [
            "Electronically signed: Dr. A. Lindqvist, Consultant Orthopaedic Surgeon.",
            "Notes reviewed and finalised 29 Mar 2026.",
        ]}]},
    {"id": "DOC-3", "name": "Insurance_Policy.pdf", "type": "Policy", "pages": 3, "content": [
        {"number": 1, "heading": "Knee Intervention Policy v2.4 - Overview", "lines": [
            "Northwind Health Plan (synthetic)  |  Effective 01 Jan 2026",
            "This policy sets the medical-necessity criteria for advanced knee interventions.",
            "All criteria below must be met and documented before authorization.",
        ]},
        {"number": 2, "heading": "Criteria PR-001 and PR-002", "lines": [
            "PR-001 - A diagnosis of knee osteoarthritis must be confirmed by a treating clinician.",
            "PR-002 - Conservative treatment must be completed for a minimum of six weeks.",
        ]},
        {"number": 3, "heading": "Criteria PR-003 and PR-004", "lines": [
            "PR-003 - Recent MRI report required.",
            "PR-004 - The clinical indication, including treatment history, must be documented consistently across submitted documents.",
        ]}]},
    {"id": "DOC-4", "name": "Imaging_Report.pdf", "type": "Imaging", "pages": 1, "content": [
        {"number": 1, "heading": "Radiology Report - Plain Radiograph", "lines": [
            "Riverside Imaging  |  Synthetic document",
            "Examination: Weight-bearing radiograph, right knee, AP and lateral views. Date: 14 Nov 2024.",
            "Findings: Joint-space narrowing medial compartment with marginal osteophytes.",
            "Impression: Changes consistent with osteoarthritis. No MRI performed.",
        ]}]},
]

EVIDENCE = [
    {"id": "EV-82931", "document_id": "DOC-2", "document_name": "Clinical_Notes.pdf", "page": 3,
     "text": "Patient has completed eight weeks of physiotherapy with limited improvement.",
     "highlight": "eight weeks of physiotherapy", "evidence_type": "Clinical Evidence", "verified": True,
     "supports": ["PR-002", "PR-004"], "fact_summary": "Physiotherapy duration: 8 weeks"},
    {"id": "EV-82932", "document_id": "DOC-2", "document_name": "Clinical_Notes.pdf", "page": 2,
     "text": "Assessment: Primary osteoarthritis of the right knee, Kellgren-Lawrence grade 3, confirmed on examination and radiograph.",
     "highlight": "Primary osteoarthritis of the right knee", "evidence_type": "Clinical Evidence", "verified": True,
     "supports": ["PR-001"], "fact_summary": "Diagnosis: primary osteoarthritis, right knee"},
    {"id": "EV-82933", "document_id": "DOC-1", "document_name": "Patient_Referral.pdf", "page": 1,
     "text": "Patient completed four weeks of physiotherapy.",
     "highlight": "four weeks of physiotherapy", "evidence_type": "Referral Statement", "verified": False,
     "supports": ["PR-004"], "fact_summary": "Physiotherapy duration: 4 weeks",
     "note": "Disagrees with EV-82931. Not verified until a reviewer resolves the conflict."},
    {"id": "EV-82934", "document_id": "DOC-3", "document_name": "Insurance_Policy.pdf", "page": 2,
     "text": "PR-002 - Conservative treatment must be completed for a minimum of six weeks.",
     "highlight": "minimum of six weeks", "evidence_type": "Policy Text", "verified": True, "supports": []},
    {"id": "EV-82935", "document_id": "DOC-3", "document_name": "Insurance_Policy.pdf", "page": 3,
     "text": "PR-003 - Recent MRI report required.",
     "highlight": "Recent MRI report required.", "evidence_type": "Policy Text", "verified": True, "supports": []},
    {"id": "EV-82936", "document_id": "DOC-4", "document_name": "Imaging_Report.pdf", "page": 1,
     "text": "Impression: Changes consistent with osteoarthritis. No MRI performed.",
     "highlight": "No MRI performed.", "evidence_type": "Imaging Evidence", "verified": True, "supports": [],
     "near_miss_for": ["PR-003"],
     "note": "Plain radiograph from Nov 2024. It is not an MRI and is not recent, so it does not satisfy PR-003."},
    {"id": "EV-82937", "document_id": "DOC-2", "document_name": "Clinical_Notes.pdf", "page": 1,
     "text": "05 Jan 2026 - Patient reports progressive right knee pain and stiffness over three months.",
     "highlight": "progressive right knee pain and stiffness", "evidence_type": "Clinical Evidence", "verified": True, "supports": []},
    {"id": "EV-82938", "document_id": "DOC-2", "document_name": "Clinical_Notes.pdf", "page": 3,
     "text": "Structured physiotherapy programme commenced 01 Feb 2026.",
     "highlight": "commenced 01 Feb 2026", "evidence_type": "Clinical Evidence", "verified": True, "supports": []},
    {"id": "EV-82939", "document_id": "DOC-1", "document_name": "Patient_Referral.pdf", "page": 1,
     "text": "Request for Advanced Knee Intervention submitted 02 Apr 2026.",
     "highlight": "submitted 02 Apr 2026", "evidence_type": "Referral Statement", "verified": True, "supports": []},
    {"id": "EV-82940", "document_id": "DOC-3", "document_name": "Insurance_Policy.pdf", "page": 2,
     "text": "PR-001 - A diagnosis of knee osteoarthritis must be confirmed by a treating clinician.",
     "highlight": "confirmed by a treating clinician", "evidence_type": "Policy Text", "verified": True, "supports": []},
    {"id": "EV-82941", "document_id": "DOC-3", "document_name": "Insurance_Policy.pdf", "page": 3,
     "text": "PR-004 - The clinical indication, including treatment history, must be documented consistently across submitted documents.",
     "highlight": "documented consistently across submitted documents", "evidence_type": "Policy Text", "verified": True, "supports": []},
]

# Facts as extracted by the AI service (before rule evaluation).
FACTS = [
    {"id": "FACT-001", "name": "physiotherapy_duration", "label": "Physiotherapy duration", "value": 8, "unit": "weeks",
     "confidence": 0.97, "source_evidence_ids": ["EV-82931"]},
    {"id": "FACT-002", "name": "physiotherapy_duration", "label": "Physiotherapy duration", "value": 4, "unit": "weeks",
     "confidence": 0.95, "source_evidence_ids": ["EV-82933"]},
    {"id": "FACT-003", "name": "diagnosis", "label": "Diagnosis", "value": "Primary osteoarthritis, right knee (KL grade 3)",
     "unit": None, "confidence": 0.98, "source_evidence_ids": ["EV-82932"]},
]

RULES = [
    {"id": "RULE-001", "criterion_id": "PR-002", "expression": "physiotherapy_duration >= 6 weeks",
     "operator": ">=", "threshold": 6, "unit": "weeks", "fact_name": "physiotherapy_duration"},
    {"id": "RULE-002", "criterion_id": "PR-001", "expression": "diagnosis contains 'osteoarthritis'",
     "operator": "contains", "threshold": "osteoarthritis", "unit": None, "fact_name": "diagnosis"},
    {"id": "RULE-003", "criterion_id": "PR-003", "expression": "count(MRI evidence, age <= 12 months) >= 1",
     "operator": ">=", "threshold": 1, "unit": None, "fact_name": None},
    {"id": "RULE-004", "criterion_id": "PR-004", "expression": "distinct(physiotherapy_duration across sources) == 1",
     "operator": "==", "threshold": 1, "unit": None, "fact_name": "physiotherapy_duration"},
]

TIMELINE = [
    {"id": "TL-1", "date": "Jan 05", "label": "Symptoms reported", "detail": "Progressive right knee pain and stiffness.", "evidence_id": "EV-82937"},
    {"id": "TL-2", "date": "Jan 20", "label": "Diagnosis established", "detail": "Primary osteoarthritis, KL grade 3.", "evidence_id": "EV-82932"},
    {"id": "TL-3", "date": "Feb 01", "label": "Physiotherapy started", "detail": "Structured programme commenced.", "evidence_id": "EV-82938"},
    {"id": "TL-4", "date": "Mar 29", "label": "8 weeks completed", "detail": "Limited improvement documented at review.", "evidence_id": "EV-82931"},
    {"id": "TL-5", "date": "Apr 02", "label": "Procedure requested", "detail": "Advanced Knee Intervention submitted.", "evidence_id": "EV-82939"},
]

DASHBOARD_BASELINE = {"active_cases": 12, "needs_review": 5, "missing_evidence": 7, "conflicts": 3, "human_reviews_today": 18}
