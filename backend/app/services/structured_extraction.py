"""Deterministic (rule-based, NOT machine-learned) extraction of dates and laboratory-style results from page text.

Every item carries its page and the exact character span, so a reviewer can find the source. Nothing is inferred:
ambiguous numeric dates are returned unparsed, and absence of an item proves nothing about the patient.
"""
import re
from datetime import date, datetime

_MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec"
_DATE_PATTERNS = [
    ("iso", re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")),
    ("day_month_year", re.compile(rf"\b(\d{{1,2}})\s+({_MONTHS})\.?,?\s+(\d{{4}})\b", re.I)),
    ("month_day_year", re.compile(rf"\b({_MONTHS})\.?\s+(\d{{1,2}}),?\s+(\d{{4}})\b", re.I)),
    ("numeric_slash", re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b")),
]
_UNITS = r"mmol/mol|mmol/L|umol/L|nmol/L|mg/dL|mg/L|g/dL|g/L|U/L|mIU/L|ug/L|mL/min|x10\^9/L|%"
_LAB = re.compile(rf"(?P<name>[A-Za-z][A-Za-z0-9 ]{{1,30}}?)\s*(?:[:=]|\bresult\b|\s)\s*(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>{_UNITS})(?:\s*\(?(?P<flag>H|L|high|low|normal|abnormal)\b\)?)?", re.I)
_STOP_NAMES = {"and", "the", "of", "at", "was", "were", "is", "are", "to", "for", "with", "ref", "range", "reference", "per", "result", "results"}


def _parse(kind: str, g: tuple[str, ...]) -> date | None:
    try:
        if kind == "iso":
            return date(int(g[0]), int(g[1]), int(g[2]))
        if kind == "day_month_year":
            return datetime.strptime(f"{int(g[0])} {g[1][:3].title()} {g[2]}", "%d %b %Y").date()
        if kind == "month_day_year":
            return datetime.strptime(f"{g[0][:3].title()} {int(g[1])} {g[2]}", "%b %d %Y").date()
    except ValueError:
        return None
    return None  # numeric_slash: day/month order is ambiguous, so it is never guessed


def extract_dates(pages: list[str]) -> list[dict]:
    out = []
    for page_no, text in enumerate(pages, start=1):
        for kind, pat in _DATE_PATTERNS:
            for m in pat.finditer(text):
                parsed = _parse(kind, m.groups())
                out.append({"page": page_no, "start": m.start(), "end": m.end(), "text": m.group(0), "isoDate": parsed.isoformat() if parsed else None,
                            "ambiguous": kind == "numeric_slash", "method": "rule"})
    return sorted(out, key=lambda d: (d["page"], d["start"]))


def extract_lab_results(pages: list[str]) -> list[dict]:
    out = []
    for page_no, text in enumerate(pages, start=1):
        for m in _LAB.finditer(text):
            words = m.group("name").strip().split()
            while words and words[0].lower() in _STOP_NAMES:
                words.pop(0)
            while words and words[-1].lower() in _STOP_NAMES:
                words.pop()
            if not words:
                continue
            kept = words[-3:]
            name = " ".join(kept)
            start = m.start("name") + m.group("name").rfind(kept[0])
            out.append({"page": page_no, "start": start, "end": m.end(), "text": text[start:m.end()].strip(), "testName": name, "value": float(m.group("value")),
                        "unit": m.group("unit"), "flag": (m.group("flag") or "").lower() or None, "method": "rule"})
    return out


def extract_fields(pages: list[str]) -> dict:
    return {"dates": extract_dates(pages), "labResults": extract_lab_results(pages), "method": "rule-based",
            "notice": "Deterministic pattern matching on the extracted text; not a machine-learning prediction and not verified. Absence of a field does not mean the event did not occur."}
