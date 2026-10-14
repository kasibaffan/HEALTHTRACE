import re
from collections import defaultdict
from datetime import date, datetime

from app.services.ai.base import AIExtractionService, Conflict, ExtractedItem, FactView

_NUM_WORDS = {w: i for i, w in enumerate(
    ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen"])}
_NUM = r"(?P<n>\d{1,2}|" + "|".join(_NUM_WORDS) + r")"
_PHYSIO = [
    re.compile(rf"\b{_NUM}\s+weeks?\s+of\s+(?:structured\s+)?physio(?:therapy)?", re.I),
    re.compile(rf"physio(?:therapy)?[^.\n]{{0,50}}?\b(?:for|over)\s+{_NUM}\s+weeks?", re.I),
]
_DIAGNOSIS = re.compile(r"(?:primary\s+)?osteoarthritis(?:\s+of\s+the\s+(?:right|left)\s+knee)?", re.I)
_MRI = re.compile(r"\bMRI\b|magnetic\s+resonance", re.I)
_NEGATED_MRI = re.compile(r"\b(?:no|not|without|never)\b[^.\n]{0,25}\b(?:MRI|magnetic\s+resonance)\b|\bMRI\b[^.\n]{0,20}\b(?:not\s+performed|not\s+done)\b", re.I)
_DATE = re.compile(r"\b(\d{1,2})\s+([A-Za-z]{3,9})\.?,?\s+(\d{4})\b")
_SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9])")

_CONFIDENCE = {"Clinical": 0.97, "Imaging": 0.96, "Referral": 0.95}
_VERIFIED_TYPES = {"Clinical", "Imaging"}
_EVIDENCE_TYPE = {"Clinical": "Clinical Evidence", "Imaging": "Imaging Evidence", "Referral": "Referral Statement"}


def _sentences(page_text: str) -> list[str]:
    out: list[str] = []
    for line in page_text.splitlines():
        line = line.strip()
        if line:
            out.extend(s.strip() for s in _SENTENCE.split(line) if s.strip())
    return out


def _parse_date(sentence: str) -> date | None:
    for d, mon, y in _DATE.findall(sentence):
        try:
            return datetime.strptime(f"{int(d)} {mon[:3].title()} {y}", "%d %b %Y").date()
        except ValueError:
            continue
    return None


class MockAIExtractionService(AIExtractionService):
    """Deterministic, offline extractor (regex over real document text). Needs no API key or network."""

    name = "mock-regex-v1"

    def extract_facts(self, doc_type: str, pages: list[str], reference_date: date) -> list[ExtractedItem]:
        if doc_type == "Policy":
            return []  # policy documents define requirements; they are not patient evidence
        conf = _CONFIDENCE.get(doc_type, 0.90)
        verified = doc_type in _VERIFIED_TYPES
        etype = _EVIDENCE_TYPE.get(doc_type, "Supporting Evidence")
        items: list[ExtractedItem] = []
        for page_no, text in enumerate(pages, start=1):
            for sentence in _sentences(text):
                items.extend(self._physio(sentence, page_no, conf, verified, etype))
                items.extend(self._diagnosis(sentence, page_no, conf, verified, etype))
                items.extend(self._mri(sentence, page_no, conf, verified, doc_type, reference_date))
        return items

    def _physio(self, s, page, conf, verified, etype):
        for pattern in _PHYSIO:
            m = pattern.search(s)
            if m:
                raw = m.group("n").lower()
                value = int(raw) if raw.isdigit() else _NUM_WORDS[raw]
                return [ExtractedItem(etype, page, s, m.group(0), "physiotherapy_duration", "Physiotherapy duration", str(value), "weeks", conf, verified)]
        return []

    def _diagnosis(self, s, page, conf, verified, etype):
        if not re.search(r"assessment|diagnos|confirmed", s, re.I):
            return []
        m = _DIAGNOSIS.search(s)
        if not m:
            return []
        return [ExtractedItem(etype, page, s, m.group(0), "diagnosis", "Diagnosis", m.group(0)[0].upper() + m.group(0)[1:], None, conf, verified)]

    def _mri(self, s, page, conf, verified, doc_type, reference):
        if not _MRI.search(s):
            return []
        if _NEGATED_MRI.search(s):
            return [ExtractedItem("Imaging Evidence", page, s, "No MRI performed." if "No MRI performed." in s else None, None, None, None, None, conf, verified, "mri_report_age_months",
                                  "States that no MRI was performed. It does not satisfy an MRI requirement.")]
        when = _parse_date(s)
        if when is None:
            return [ExtractedItem("Imaging Evidence", page, s, None, None, None, None, None, conf, verified, "mri_report_age_months",
                                  "MRI is mentioned without a report date, so recency cannot be established.")]
        months = round((reference - when).days / 30.44, 1)
        return [ExtractedItem("Imaging Evidence", page, s, "MRI", "mri_report_age_months", "MRI report age", str(max(months, 0)), "months", conf, verified, "mri_report_age_months")]

    def find_evidence(self, pages: list[str], terms: list[str]) -> list[tuple[int, str]]:
        hits = []
        for page_no, text in enumerate(pages, start=1):
            hits += [(page_no, s) for s in _sentences(text) if any(t.lower() in s.lower() for t in terms)]
        return hits

    def detect_conflicts(self, facts: list[FactView]) -> list[Conflict]:
        by_name: dict[str, list[FactView]] = defaultdict(list)
        for f in facts:
            by_name[f.name].append(f)
        return [Conflict(n, g[0].label, [f.id for f in g]) for n, g in by_name.items() if len({f.value for f in g}) > 1]

    def summarize_case(self, counts: dict[str, int], titles: dict[str, list[str]]) -> str:
        parts = []
        if counts.get("MATCH"):
            parts.append(f"{counts['MATCH']} criteria are supported by evidence ({', '.join(titles['MATCH'])})")
        if counts.get("MISSING"):
            parts.append(f"no qualifying evidence was found for {', '.join(titles['MISSING'])}")
        if counts.get("CONFLICT"):
            parts.append(f"sources disagree on {', '.join(titles['CONFLICT'])}")
        if counts.get("INCONCLUSIVE"):
            parts.append(f"evidence was found but does not meet the threshold for {', '.join(titles['INCONCLUSIVE'])}")
        if not parts:
            return "No findings yet. Upload documents to begin evidence extraction."
        return (parts[0][0].upper() + parts[0][1:] + "; " + "; ".join(parts[1:]) + "." if len(parts) > 1 else parts[0][0].upper() + parts[0][1:] + ".") + " A human reviewer must confirm each finding."
