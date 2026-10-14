from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date


@dataclass
class ExtractedItem:
    """One piece of evidence, optionally tied to a structured fact. Raw AI output; validated before persistence."""

    evidence_type: str
    page: int
    text: str
    highlight: str | None = None
    fact_name: str | None = None
    fact_label: str | None = None
    fact_value: str | None = None
    fact_unit: str | None = None
    confidence: float = 0.9
    verified: bool = False
    topic: str | None = None
    note: str | None = None


@dataclass
class FactView:
    id: str
    name: str
    label: str
    value: str


@dataclass
class Conflict:
    fact_name: str
    label: str
    fact_ids: list[str]


class AIExtractionService(ABC):
    """AI assists with extraction and retrieval only. Rule results and final decisions are never made by AI."""

    name: str

    @abstractmethod
    def extract_facts(self, doc_type: str, pages: list[str], reference_date: date) -> list[ExtractedItem]: ...

    @abstractmethod
    def find_evidence(self, pages: list[str], terms: list[str]) -> list[tuple[int, str]]:
        """Return (page, exact sentence) hits for search terms."""

    @abstractmethod
    def detect_conflicts(self, facts: list[FactView]) -> list[Conflict]: ...

    @abstractmethod
    def summarize_case(self, counts: dict[str, int], titles: dict[str, list[str]]) -> str: ...
