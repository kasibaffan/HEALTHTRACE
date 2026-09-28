"""Per-user HIPAA access-pattern detection (SPEC.md section 6.7).

For each user, tracks a rolling 10-minute window of patient accesses and
runs three checks: bulk access (too many distinct patients relative to the
user's own baseline), bulk export, off-hours access, and region mismatch.

A user's own "normal" distinct-patient-access rate is learned the same way
the per-service baseline is (EWMA, updated only from non-anomalous
observations — SPEC.md 6.4's poisoning protection, mirrored here) so a bulk
burst can't inflate its own detection threshold while it's happening. That
sampling happens once per 10-minute period (the same length as the rolling
window itself), not on every event: distinct-patient count within an
*ongoing* burst only ever climbs, so sampling it continuously would let the
baseline chase the burst upward before the burst ever finishes — the same
failure mode as a gradual service-metric ramp (see README "Design
decisions"), just guaranteed to happen here since a rolling count can only
increase within one window.

Design decisions where SPEC.md left the exact mechanics unstated (documented
in README under "Design decisions" too):

- A brand-new user (no access history at all) has baseline 0, so the bulk
  threshold collapses to the flat floor (``bulk_min_threshold``) rather than
  requiring history to exist first — a user who's never touched more than a
  handful of records suddenly viewing hundreds is exactly the case this
  should catch, not exempt. Its severity multiplier is then set just above
  the CRITICAL cutoff, since "no baseline at all" is at least as suspicious
  as "far above an established one".
- Off-hours and bulk-export use the same 10-minute rolling window as bulk
  access, for one consistent mechanism rather than three window lengths.
- Bulk export has its own floor (``export_min_threshold``), separate from
  bulk access's (``bulk_min_threshold``): exports are a small fraction of
  audit actions, so the two need very different scales (see README "Design
  decisions") — below the floor nothing fires; above it but at or below
  ``export_critical_records`` is MEDIUM; above that is CRITICAL.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, time as dt_time, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from app.config import HipaaConfig
from app.models import Anomaly, AuditEvent

ROLLING_WINDOW = timedelta(minutes=10)


@dataclass
class _AccessRecord:
    ts: datetime
    patient_id: str
    action: str
    off_hours: bool
    region_mismatch: bool


@dataclass
class _UserState:
    records: "deque[_AccessRecord]" = field(default_factory=deque)
    baseline_mean: float = 0.0
    baseline_count: int = 0
    next_sample_at: Optional[datetime] = None


class AccessDetector:
    def __init__(self, config: HipaaConfig, *, baseline_alpha: float = 0.1) -> None:
        self._config = config
        self._alpha = baseline_alpha
        self._users: dict[str, _UserState] = {}
        self._off_hours_start = dt_time.fromisoformat(config.off_hours_start)
        self._off_hours_end = dt_time.fromisoformat(config.off_hours_end)
        self._tz = ZoneInfo(config.timezone)

    def evaluate(self, event: AuditEvent) -> list[Anomaly]:
        state = self._users.setdefault(event.user_id, _UserState())
        off_hours = self._is_off_hours(event.ts)
        region_mismatch = event.is_region_mismatch

        state.records.append(
            _AccessRecord(event.ts, event.patient_id, event.action, off_hours, region_mismatch)
        )
        self._evict_expired(state, event.ts)

        anomalies: list[Anomaly] = []
        distinct_patients = len({r.patient_id for r in state.records})

        bulk_anomaly = self._check_bulk_access(event, state, distinct_patients, anomalies)
        if event.action == "EXPORT_RECORDS":
            self._check_bulk_export(event, state, anomalies)
        if off_hours:
            self._check_off_hours(event, state, anomalies)
        if region_mismatch:
            self._check_region_mismatch(event, state, anomalies)

        # Baseline sampling, once per rolling-window period (see module
        # docstring): only when due, and only from a non-anomalous reading
        # (poisoning protection, mirroring SPEC.md 6.4).
        if state.next_sample_at is None:
            state.next_sample_at = event.ts + ROLLING_WINDOW
        elif event.ts >= state.next_sample_at:
            if not bulk_anomaly:
                self._update_baseline(state, distinct_patients)
            state.next_sample_at += ROLLING_WINDOW

        return anomalies

    # -- checks --------------------------------------------------------------

    def _check_bulk_access(
        self, event: AuditEvent, state: _UserState, distinct_patients: int, anomalies: list[Anomaly]
    ) -> bool:
        baseline = state.baseline_mean if state.baseline_count > 0 else 0.0
        threshold = max(self._config.bulk_multiplier_high * baseline, self._config.bulk_min_threshold)
        if distinct_patients <= threshold:
            return False

        multiplier = (
            distinct_patients / baseline if baseline > 0 else self._config.bulk_multiplier_critical + 1
        )
        anomalies.append(
            Anomaly(
                kind="hipaa_bulk_access",
                ts=event.ts,
                user_id=event.user_id,
                metrics={"multiplier": multiplier, "distinct_patients": distinct_patients},
            )
        )
        return True

    def _check_bulk_export(self, event: AuditEvent, state: _UserState, anomalies: list[Anomaly]) -> None:
        exported = len({r.patient_id for r in state.records if r.action == "EXPORT_RECORDS"})
        if exported <= self._config.export_min_threshold:
            return
        anomalies.append(
            Anomaly(kind="hipaa_bulk_export", ts=event.ts, user_id=event.user_id, metrics={"records": exported})
        )

    def _check_off_hours(self, event: AuditEvent, state: _UserState, anomalies: list[Anomaly]) -> None:
        off_hours_count = sum(1 for r in state.records if r.off_hours)
        anomalies.append(
            Anomaly(kind="hipaa_off_hours", ts=event.ts, user_id=event.user_id, metrics={"records": off_hours_count})
        )

    def _check_region_mismatch(self, event: AuditEvent, state: _UserState, anomalies: list[Anomaly]) -> None:
        mismatched_patients = len({r.patient_id for r in state.records if r.region_mismatch})
        anomalies.append(
            Anomaly(
                kind="hipaa_region_mismatch",
                ts=event.ts,
                user_id=event.user_id,
                metrics={"distinct_patients": mismatched_patients},
            )
        )

    # -- helpers ---------------------------------------------------------------

    def _is_off_hours(self, ts: datetime) -> bool:
        local = ts.astimezone(self._tz).time() if ts.tzinfo else ts.time()
        return not (self._off_hours_start <= local < self._off_hours_end)

    def _evict_expired(self, state: _UserState, as_of: datetime) -> None:
        cutoff = as_of - ROLLING_WINDOW
        while state.records and state.records[0].ts < cutoff:
            state.records.popleft()

    def _update_baseline(self, state: _UserState, distinct_patients: int) -> None:
        if state.baseline_count == 0:
            state.baseline_mean = float(distinct_patients)
        else:
            state.baseline_mean += self._alpha * (distinct_patients - state.baseline_mean)
        state.baseline_count += 1

    def user_summaries(self) -> list[dict]:
        """Current rolling-window picture per user, for the HIPAA panel."""
        out = []
        for user_id, state in self._users.items():
            if not state.records:
                continue
            baseline = state.baseline_mean if state.baseline_count > 0 else 0.0
            out.append(
                {
                    "user_id": user_id,
                    "distinct_patients": len({r.patient_id for r in state.records}),
                    "events": len(state.records),
                    "exports": sum(1 for r in state.records if r.action == "EXPORT_RECORDS"),
                    "off_hours_events": sum(1 for r in state.records if r.off_hours),
                    "region_mismatch_patients": len({r.patient_id for r in state.records if r.region_mismatch}),
                    "baseline": baseline if state.baseline_count > 0 else None,
                    "bulk_threshold": max(self._config.bulk_multiplier_high * baseline, self._config.bulk_min_threshold),
                    "last_seen": state.records[-1].ts.isoformat(),
                }
            )
        return sorted(out, key=lambda u: u["distinct_patients"], reverse=True)
