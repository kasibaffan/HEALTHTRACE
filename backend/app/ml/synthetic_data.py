"""Reproducible generator for FICTIONAL training documents. No real patient data is used or needed.

Each document is assembled from randomly chosen sentence templates, filled with randomly chosen vocabulary, wrapped in a
randomly chosen header/footer style, and sometimes degraded (case changes, dropped characters) or "contaminated" with a
sentence typical of another class (a clinical note that mentions a lab order, a referral that cites an MRI, ...). That
overlap is deliberate: it keeps the task from being solvable by a single keyword.

Limits: the generator is the only source of both the training and the held-out test documents, so test scores measure
how well the model learned *this generator's* distribution. They say nothing about accuracy on real documents.
"""
from __future__ import annotations

import hashlib
import json
import random
from dataclasses import dataclass

from app.ml.labels import (
    CLAIM_BILLING, CLINICAL_REPORT, IMAGING_REPORT, LABELS, LABORATORY_RESULT, OTHER, POLICY_DOCUMENT, REFERRAL_ORDER,
)

# ---------------------------------------------------------------------------------------------------------- vocabulary
_FIRST = ["Alex", "Jordan", "Morgan", "Riley", "Casey", "Taylor", "Sam", "Jamie", "Robin", "Avery", "Quinn", "Devon", "Rowan", "Kai", "Noor", "Imani"]
_LAST = ["Testwell", "Examplar", "Sample", "Fictson", "Mockley", "Placeholder", "Demoton", "Syntheta", "Notreal", "Faux", "Dummer", "Pretend"]
_FACILITY = ["Riverbend Medical Group", "Northfield Clinic", "Harbor Health Centre", "Maple Grove Hospital", "Summit Care Associates", "Lakeside Specialty Clinic",
             "Fictional General Hospital", "Cedar Valley Health", "Bayview Outpatient Centre", "Pinecrest Medical Practice"]
_CLINICIAN = ["Dr. A. Placeholder", "Dr. B. Example", "Dr. C. Fictive", "Dr. D. Sample", "Dr. E. Mockson", "NP F. Testerman", "Dr. G. Notareal", "PA H. Synthetic"]
_MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
_JOINT = ["right knee", "left knee", "lumbar spine", "right shoulder", "left hip", "cervical spine", "left shoulder", "right ankle", "right hip", "left wrist"]
_CONDITION = ["osteoarthritis", "lumbar radiculopathy", "rotator cuff tendinopathy", "chronic low back pain", "meniscal degeneration", "type 2 diabetes mellitus",
              "hypertension", "plantar fasciitis", "cervical spondylosis", "asthma", "iron deficiency anaemia", "hypothyroidism", "migraine", "atrial fibrillation"]
_MED = ["naproxen", "paracetamol", "ibuprofen", "metformin", "amlodipine", "levothyroxine", "salbutamol", "atorvastatin", "gabapentin", "omeprazole"]
_PROCEDURE = ["total knee arthroplasty", "arthroscopic debridement", "lumbar epidural injection", "rotator cuff repair", "hip replacement", "spinal fusion",
              "cardiology consultation", "orthopaedic surgical review", "pain management programme", "MRI of the lumbar spine", "echocardiogram"]
_LAB_TEST = [("Haemoglobin", "g/dL", (9.0, 17.5)), ("White cell count", "x10^9/L", (3.0, 14.0)), ("Platelets", "x10^9/L", (120, 420)),
             ("Sodium", "mmol/L", (130, 148)), ("Potassium", "mmol/L", (3.1, 5.6)), ("Creatinine", "umol/L", (50, 140)), ("HbA1c", "mmol/mol", (30, 80)),
             ("Total cholesterol", "mmol/L", (3.0, 7.5)), ("TSH", "mIU/L", (0.2, 6.5)), ("CRP", "mg/L", (1, 60)), ("Ferritin", "ug/L", (8, 300)),
             ("ALT", "U/L", (10, 90)), ("eGFR", "mL/min", (35, 110)), ("Vitamin D", "nmol/L", (20, 120))]
_MODALITY = [("MRI", "magnetic resonance imaging"), ("X-ray", "plain radiograph"), ("CT", "computed tomography"), ("Ultrasound", "ultrasonography")]
_IMG_FINDING = ["moderate joint space narrowing with marginal osteophytes", "no acute fracture or dislocation", "small joint effusion",
                "degenerative signal change within the posterior horn of the medial meniscus", "mild disc bulge at L4-L5 without canal stenosis",
                "partial thickness supraspinatus tear", "preserved alignment and normal bone density", "subchondral sclerosis and cystic change",
                "no focal soft tissue mass", "mild intervertebral disc height loss", "cortical irregularity without periosteal reaction"]
_CPT = lambda r: str(r.choice([27447, 29881, 62323, 23412, 27130, 22612, 99213, 99214, 72148, 73721, 93306, 36415, 80053, 85025]))  # noqa: E731
_ICD = ["M17.11", "M17.12", "M54.16", "M75.10", "E11.9", "I10", "J45.909", "M72.2", "M47.812", "E03.9", "G43.909", "I48.91"]
_PAYER = ["Fictional Health Plan", "Northwind Mutual (synthetic)", "Example Assurance", "Acme Benefits (test)", "Contoso Care Plan", "Sample Insurance Co."]
_WEEKS = ["four", "six", "eight", "ten", "twelve", "4", "6", "8", "10", "12"]


def _date(r: random.Random) -> str:
    d, m, y = r.randint(1, 28), r.choice(_MONTHS), r.randint(2023, 2026)
    return r.choice([f"{d} {m} {y}", f"{m} {d}, {y}", f"{y}-{_MONTHS.index(m) + 1:02d}-{d:02d}", f"{d:02d}/{_MONTHS.index(m) + 1:02d}/{y}"])


def _name(r: random.Random) -> str:
    return f"{r.choice(_FIRST)} {r.choice(_LAST)}"


def _ref(r: random.Random, prefix: str) -> str:
    return f"{prefix}-{r.randint(10000, 99999)}"


# ------------------------------------------------------------------------------------------------ per-class sentences
def _clinical(r: random.Random) -> list[str]:
    j, c, m = r.choice(_JOINT), r.choice(_CONDITION), r.choice(_MED)
    pool = [
        f"The patient presents with {r.choice(['persistent', 'worsening', 'intermittent', 'chronic'])} pain in the {j} for {r.randint(2, 18)} months.",
        f"Assessment: {c} of the {j}, {r.choice(['mild', 'moderate', 'severe', 'progressive'])}.",
        f"History of present illness: symptoms {r.choice(['began', 'started', 'were first noted'])} after {r.choice(['a fall', 'increased activity', 'a minor injury', 'no clear trigger'])}.",
        f"Completed {r.choice(_WEEKS)} weeks of structured physiotherapy with {r.choice(['limited', 'partial', 'minimal', 'no'])} improvement.",
        f"Current medications include {m} {r.choice([5, 10, 20, 50, 100, 250, 500])} mg {r.choice(['daily', 'twice daily', 'as needed'])}.",
        f"On examination there is {r.choice(['tenderness', 'crepitus', 'reduced range of motion', 'swelling'])} over the {j}; neurovascular status intact.",
        f"Plan: continue {r.choice(['conservative management', 'analgesia', 'home exercise programme', 'weight management'])} and review in {r.randint(2, 12)} weeks.",
        f"Vital signs: blood pressure {r.randint(105, 160)}/{r.randint(60, 98)} mmHg, pulse {r.randint(52, 105)} bpm, temperature {r.uniform(36.0, 37.8):.1f} C.",
        f"The patient reports {r.choice(['no known drug allergies', 'an allergy to penicillin', 'no adverse reactions to prior treatment'])}.",
        f"Progress note: the patient was seen for follow up of {c}; {r.choice(['condition stable', 'symptoms improving', 'no change since last visit'])}.",
        f"Discharge summary: admitted for {r.choice(['observation', 'pain control', 'investigation'])} and discharged home in stable condition.",
        f"Past medical history is significant for {c} and {r.choice(_CONDITION)}.",
        f"Functional status: walks {r.choice(['unaided', 'with a cane', 'short distances only'])}; difficulty with stairs.",
        f"Impression and plan discussed with the patient, who verbalised understanding. Seen by {r.choice(_CLINICIAN)}.",
    ]
    return pool


def _imaging(r: random.Random) -> list[str]:
    mod, long = r.choice(_MODALITY)
    j = r.choice(_JOINT)
    pool = [
        f"EXAMINATION: {mod} of the {j}.",
        f"TECHNIQUE: {long} of the {j} was performed {r.choice(['without contrast', 'with intravenous contrast', 'using standard protocol'])}.",
        f"FINDINGS: {r.choice(_IMG_FINDING)}; {r.choice(_IMG_FINDING)}.",
        f"IMPRESSION: {r.choice(_IMG_FINDING)}. {r.choice(['No further imaging is required.', 'Clinical correlation is advised.', 'Follow-up imaging in 6 months is suggested.'])}",
        f"Comparison: {r.choice(['no prior studies available', f'prior {mod} dated {_date(r)}', 'compared with previous radiographs'])}.",
        f"The {j} {mod.lower()} demonstrates {r.choice(_IMG_FINDING)}.",
        f"Clinical indication: {r.choice(['chronic pain', 'trauma', 'pre-operative assessment', 'persistent symptoms'])} of the {j}.",
        f"Radiologist: {r.choice(_CLINICIAN)}. Report finalised {_date(r)}.",
        f"Bone marrow signal is {r.choice(['normal', 'heterogeneous', 'mildly oedematous'])}; articular cartilage shows {r.choice(['focal thinning', 'full thickness loss', 'preserved thickness'])}.",
        f"Image quality was {r.choice(['diagnostic', 'adequate', 'limited by motion artefact'])}. Slice thickness {r.choice([2, 3, 4, 5])} mm.",
        f"No {r.choice(['fracture', 'mass lesion', 'acute abnormality', 'osseous destruction'])} is identified.",
    ]
    return pool


def _lab(r: random.Random) -> list[str]:
    def row() -> str:
        name, unit, (lo, hi) = r.choice(_LAB_TEST)
        val = round(r.uniform(lo, hi), 1)
        flag = r.choice(["", "", " H", " L", " (normal)", " (abnormal)"])
        return r.choice([f"{name}: {val} {unit}{flag}", f"{name.upper()}  {val}  {unit}  ref {round(lo * 1.1, 1)}-{round(hi * 0.9, 1)}{flag}", f"{name} result {val} {unit}{flag}"])

    pool = [row() for _ in range(6)] + [
        f"Specimen: {r.choice(['venous blood', 'serum', 'plasma', 'urine', 'capillary blood'])} collected {_date(r)}.",
        f"Accession number {_ref(r, 'LAB')}; received {_date(r)}; reported {_date(r)}.",
        f"Reference range shown in brackets; values outside the range are flagged {r.choice(['H or L', 'with an asterisk', 'in bold'])}.",
        f"Comment: {r.choice(['sample haemolysed, interpret with caution', 'fasting sample', 'repeat testing recommended if clinically indicated', 'results phoned to ward'])}.",
        f"Laboratory report: {r.choice(['Haematology', 'Clinical chemistry', 'Microbiology', 'Endocrinology', 'Urinalysis'])} panel.",
        f"Pathology laboratory director: {r.choice(_CLINICIAN)}. Analyser run {r.randint(1000, 9999)}.",
        f"Culture {r.choice(['no growth after 48 hours', 'grew mixed flora', 'positive, sensitivities pending'])}.",
    ]
    return pool


def _referral(r: random.Random) -> list[str]:
    j, c, p = r.choice(_JOINT), r.choice(_CONDITION), r.choice(_PROCEDURE)
    pool = [
        f"Referral to {r.choice(['orthopaedics', 'cardiology', 'rheumatology', 'pain management', 'neurosurgery', 'physiotherapy', 'endocrinology'])} for {p}.",
        f"Reason for referral: {c} of the {j} not responding to conservative treatment.",
        f"Please assess and advise regarding {p}. Urgency: {r.choice(['routine', 'urgent', 'expedited', 'within 2 weeks'])}.",
        f"Referring clinician: {r.choice(_CLINICIAN)}, {r.choice(_FACILITY)}.",
        f"Order: {r.choice(['MRI', 'X-ray', 'blood tests', 'ECG', 'physiotherapy course', 'specialist review'])} requested for {_name(r)}.",
        f"Requested service: {p}. Diagnosis code {r.choice(_ICD)}.",
        f"Thank you for seeing this patient, who has {c} and has tried {r.choice(_MED)} without adequate relief.",
        f"Please arrange an appointment and send your recommendations to the referring practice. Referral reference {_ref(r, 'REF')}.",
        f"Prior authorisation is being requested for {p}; supporting notes enclosed.",
        f"Relevant history: {c}; current medications {r.choice(_MED)}; no known allergies.",
        f"Dear colleague, I would be grateful for your opinion on this patient with {c}.",
        f"Order set signed {_date(r)} by {r.choice(_CLINICIAN)}. Patient to be contacted by the receiving service.",
    ]
    return pool


def _claim(r: random.Random) -> list[str]:
    def line() -> str:
        return f"Line {r.randint(1, 9)}: CPT {_CPT(r)}  units {r.randint(1, 3)}  charge ${r.randint(35, 18500)}.{r.randint(0, 99):02d}"

    pool = [line() for _ in range(5)] + [
        f"Claim number {_ref(r, 'CLM')}; payer {r.choice(_PAYER)}; date of service {_date(r)}.",
        f"Member ID {r.randint(100000, 999999)}; group {r.randint(1000, 9999)}; subscriber {_name(r)}.",
        f"Total billed ${r.randint(100, 40000)}.{r.randint(0, 99):02d}; allowed amount ${r.randint(80, 30000)}.{r.randint(0, 99):02d}; patient responsibility ${r.randint(0, 900)}.{r.randint(0, 99):02d}.",
        f"Diagnosis codes: {r.choice(_ICD)}, {r.choice(_ICD)}. Place of service {r.choice(['11 office', '21 inpatient hospital', '22 outpatient hospital', '24 ambulatory surgical centre'])}.",
        f"Explanation of benefits: {r.choice(['claim processed', 'claim denied - missing documentation', 'claim partially approved', 'claim pending review'])}.",
        f"Billing provider NPI {r.randint(1000000000, 1999999999)}; tax ID {r.randint(10, 99)}-{r.randint(1000000, 9999999)}.",
        f"Invoice {_ref(r, 'INV')} due {_date(r)}. Remit payment to the billing office of {r.choice(_FACILITY)}.",
        f"Adjustment reason code {r.choice(['CO-45', 'PR-1', 'CO-97', 'PR-2', 'CO-50'])}; remark code {r.choice(['N130', 'M86', 'N290'])}.",
        f"Deductible met to date ${r.randint(0, 3000)}.{r.randint(0, 99):02d}; out-of-pocket maximum ${r.randint(3000, 9000)}.",
    ]
    return pool


def _policy(r: random.Random) -> list[str]:
    p = r.choice(_PROCEDURE)
    pool = [
        f"Medical policy {_ref(r, 'MP')}: coverage criteria for {p}.",
        f"{p.capitalize()} is considered medically necessary when all of the following criteria are met.",
        f"The member must have documented completion of at least {r.choice(_WEEKS)} weeks of conservative therapy, including supervised physiotherapy.",
        f"Imaging within the past {r.choice(['3', '6', '12', 'three', 'six'])} months demonstrating {r.choice(_IMG_FINDING)} is required.",
        f"Prior authorisation is required for {p}. Requests without the documentation listed below will be returned.",
        f"This policy applies to {r.choice(_PAYER)} commercial and Medicare Advantage plans effective {_date(r)}.",
        f"Exclusions: {p} is not covered for {r.choice(['cosmetic purposes', 'experimental indications', 'members without a confirmed diagnosis'])}.",
        f"Required documentation: clinical notes, imaging reports, and a record of prior treatments attempted.",
        f"Policy version {r.randint(1, 9)}.{r.randint(0, 9)}; last reviewed {_date(r)}; next scheduled review {_date(r)}.",
        f"Definitions: 'conservative therapy' means non-surgical management such as medication, bracing and exercise therapy.",
        f"Approval criteria are evaluated by a clinical reviewer; the criteria do not replace the judgement of the treating clinician.",
        f"Coverage rationale: evidence supports {p} for members who meet the criteria in section {r.randint(2, 7)}.",
    ]
    return pool


def _other(r: random.Random) -> list[str]:
    pool = [
        f"Minutes of the {r.choice(['facilities', 'staff', 'finance', 'quality', 'IT steering'])} committee meeting held on {_date(r)}. Attendees: {_name(r)}, {_name(r)}.",
        f"Action item: {r.choice(['update the rota', 'renew the parking permits', 'order printer toner', 'schedule the fire drill', 'refresh the intranet page'])} by {_date(r)}.",
        f"Recipe: combine {r.randint(1, 4)} cups of flour with {r.randint(1, 3)} eggs and bake for {r.randint(20, 50)} minutes.",
        f"Your parcel {_ref(r, 'TRK')} has shipped and is expected to arrive on {_date(r)}.",
        f"Newsletter: join us for the {r.choice(['annual picnic', 'wellness walk', 'charity quiz', 'holiday market'])} on {_date(r)}. Everyone is welcome.",
        f"Patient information leaflet: staying active can help you feel better. Speak to your care team before starting a new programme.",
        f"IT ticket {_ref(r, 'IT')}: user cannot connect to the VPN. Resolution: password reset and client reinstall.",
        f"Dear team, a reminder that the car park will be closed on {_date(r)} for resurfacing. Please use the overflow lot.",
        f"Travel itinerary: flight departs {_date(r)} at {r.randint(5, 22)}:{r.choice(['00', '15', '30', '45'])}; hotel confirmation {_ref(r, 'HTL')}.",
        f"Job description: the successful candidate will coordinate schedules and maintain the shared calendar. Salary band {r.choice('ABCD')}.",
        f"Cafeteria menu for the week of {_date(r)}: soup of the day, grilled vegetables, and fruit salad.",
        f"Appointment reminder: you are booked for {_date(r)} at {r.randint(8, 16)}:{r.choice(['00', '30'])}. Please arrive 10 minutes early. Reply C to cancel.",
        f"Annual report highlights: volunteer hours increased by {r.randint(3, 40)} percent and donations rose across all regions.",
        f"Privacy notice: we use cookies to improve your experience on this website. You may change your preferences at any time.",
        f"Lease agreement between {_name(r)} and {_name(r)}, term {r.randint(6, 36)} months, monthly rent ${r.randint(900, 3200)}.",
    ]
    return pool


_POOLS = {CLINICAL_REPORT: _clinical, IMAGING_REPORT: _imaging, LABORATORY_RESULT: _lab, REFERRAL_ORDER: _referral,
          CLAIM_BILLING: _claim, POLICY_DOCUMENT: _policy, OTHER: _other}

_TITLES = {
    CLINICAL_REPORT: ["Clinical Note", "Progress Note", "Consultation Report", "Discharge Summary", "Office Visit", "History and Physical", ""],
    IMAGING_REPORT: ["Radiology Report", "Imaging Report", "MRI Report", "Diagnostic Imaging", "Imaging Findings", ""],
    LABORATORY_RESULT: ["Laboratory Report", "Lab Results", "Pathology Results", "Test Results", "Blood Work", ""],
    REFERRAL_ORDER: ["Referral Letter", "Referral Request", "Order Form", "Specialist Referral", "Service Request", ""],
    CLAIM_BILLING: ["Claim Form", "Statement of Charges", "Explanation of Benefits", "Invoice", "Billing Summary", ""],
    POLICY_DOCUMENT: ["Medical Policy", "Coverage Policy", "Clinical Policy Bulletin", "Utilisation Criteria", "Plan Guidelines", ""],
    OTHER: ["Memo", "Meeting Minutes", "Newsletter", "Notice", "Notes", "Letter", ""],
}

# Sentence topics from other classes that may appear as incidental mentions in a document of another class.
_CONTAMINATION_ROUTES = [CLINICAL_REPORT, IMAGING_REPORT, LABORATORY_RESULT, REFERRAL_ORDER, CLAIM_BILLING, POLICY_DOCUMENT]
_BOILERPLATE = [
    "CONFIDENTIAL - synthetic test document, not a real record.", "Page 1 of 1", "Page {p} of {q}", "Fax: 555-01{n:02d}", "Phone 555-01{n:02d}",
    "Generated automatically.", "Please retain a copy for your records.", "Printed {d}.", "Internal use only.",
]


def _degrade(text: str, r: random.Random) -> str:
    mode = r.random()
    if mode < 0.08:
        return text.upper()
    if mode < 0.14:
        return text.lower()
    if mode < 0.30:  # OCR-like character loss
        return "".join(ch for ch in text if ch == " " or ch == "\n" or r.random() > 0.015)
    return text


def generate_document(label: str, r: random.Random) -> str:
    pool = _POOLS[label](r)
    n = r.randint(2, min(6, len(pool)))
    body = r.sample(pool, n)
    if r.random() < 0.6:  # incidental mentions typical of other classes (a clinical note citing an MRI order, a claim citing a diagnosis, ...)
        for _ in range(r.choice([1, 1, 2, 3])):
            other_label = r.choice([x for x in _CONTAMINATION_ROUTES + [OTHER] if x != label])
            body.insert(r.randint(0, len(body)), r.choice(_POOLS[other_label](r)))
    parts: list[str] = []
    title = r.choice(_TITLES[label]) if r.random() < 0.6 else ""
    header_style = r.randint(0, 3)
    if title and header_style == 0:
        parts.append(title.upper())
    elif title and header_style == 1:
        parts.append(f"{r.choice(_FACILITY)} - {title}")
    elif title and header_style == 2:
        parts.append(f"{title}\n{'-' * len(title)}")
    if r.random() < 0.55:
        parts.append(f"{r.choice(_FACILITY)}")
    if r.random() < 0.5 and label != POLICY_DOCUMENT:
        parts.append(f"Patient: {_name(r)}  DOB: {_date(r)}")
    sep = r.choice(["\n", "\n\n", " "])
    parts.append(sep.join(body))
    if r.random() < 0.5:
        parts.append(r.choice(_BOILERPLATE).format(p=1, q=r.randint(1, 4), n=r.randint(0, 99), d=_date(r)))
    return _degrade("\n".join(parts), r)


@dataclass(frozen=True)
class Dataset:
    texts: list[str]
    labels: list[str]
    seed: int
    per_class: int

    def fingerprint(self) -> str:
        """Content hash used as dataset provenance in the model metadata."""
        h = hashlib.sha256()
        h.update(json.dumps({"seed": self.seed, "per_class": self.per_class}, sort_keys=True).encode())
        for t, y in zip(self.texts, self.labels):
            h.update(y.encode())
            h.update(b"\x00")
            h.update(t.encode("utf-8"))
            h.update(b"\x01")
        return h.hexdigest()


def generate_dataset(per_class: int = 300, seed: int = 42, deduplicate: bool = True) -> Dataset:
    """Same (per_class, seed) always yields the same dataset. Exact duplicate texts are removed so a document cannot
    appear in both the training and the test split."""
    r = random.Random(seed)
    texts: list[str] = []
    labels: list[str] = []
    seen: set[str] = set()
    for label in LABELS:
        made, attempts = 0, 0
        while made < per_class and attempts < per_class * 20:
            attempts += 1
            doc = generate_document(label, r)
            key = " ".join(doc.lower().split())
            if deduplicate and key in seen:
                continue
            seen.add(key)
            texts.append(doc)
            labels.append(label)
            made += 1
    order = list(range(len(texts)))
    r.shuffle(order)
    return Dataset([texts[i] for i in order], [labels[i] for i in order], seed, per_class)
