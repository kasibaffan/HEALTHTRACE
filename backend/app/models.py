"""Pydantic models shared across the MedGuard backend.

Milestone 1 defines only the raw event shapes emitted by the log generator
(``AppEvent``, ``AuditEvent``) so the generator's output can be validated
against them. ``WindowMetrics``, ``Alert``, and ``Incident`` belong to later
milestones (sliding window, severity engine, incident engine) and are added
when those pieces are built, per SPEC.md section 8.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field

Service = Literal["claims", "prior_auth", "eligibility", "pharmacy", "batch"]
Level = Literal["INFO", "WARN", "ERROR"]
Priority = Literal["urgent", "routine"]
AuditAction = Literal["VIEW_RECORD", "EDIT_RECORD", "EXPORT_RECORDS", "SEARCH"]

# Synthetic patient IDs only, e.g. "P-000123" (SPEC.md section 1: hard rules).
PATIENT_ID_PATTERN = r"^P-\d{6}$"


class AppEvent(BaseModel):
    """One JSON line from data/logs/app.log (SPEC.md section 5)."""

    ts: datetime
    type: Literal["app"] = "app"
    service: Service
    level: Level
    priority: Priority
    request_id: str
    patient_id: Optional[str] = Field(default=None, pattern=PATIENT_ID_PATTERN)
    status: int = Field(ge=100, le=599)
    latency_ms: int = Field(ge=0)
    msg: str

    @property
    def is_error(self) -> bool:
        """An event counts as an error when level == ERROR or status >= 500."""
        return self.level == "ERROR" or self.status >= 500


class AuditEvent(BaseModel):
    """One JSON line from data/logs/audit.log (SPEC.md section 5)."""

    ts: datetime
    type: Literal["audit"] = "audit"
    user_id: str
    role: str
    action: AuditAction
    patient_id: str = Field(pattern=PATIENT_ID_PATTERN)
    patient_region: str
    user_region: str

    @property
    def is_region_mismatch(self) -> bool:
        return self.patient_region != self.user_region
