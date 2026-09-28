"""Per-service sliding window over enriched app events (SPEC.md section 6.3).

Keeps a deque of the last 60s of *event time* per service and emits one
WindowMetrics snapshot every 5s of event time. Driven entirely by event
timestamps, never the wall clock (SPEC.md section 1): a snapshot becomes due
only once some event's ts crosses the next 5s boundary for that service, so
replaying a log file deterministically reproduces the same metrics.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

from app.models import WindowMetrics
from app.parse.enricher import EnrichedAppEvent

WINDOW_SECONDS = 60.0
STEP_SECONDS = 5.0


@dataclass
class _ServiceWindow:
    events: "deque[EnrichedAppEvent]" = field(default_factory=deque)
    next_emit_at: Optional[datetime] = None


class SlidingWindow:
    def __init__(self, window_seconds: float = WINDOW_SECONDS, step_seconds: float = STEP_SECONDS) -> None:
        self.window_seconds = window_seconds
        self.step_seconds = step_seconds
        self._windows: dict[str, _ServiceWindow] = {}

    def add(self, enriched: EnrichedAppEvent) -> list[WindowMetrics]:
        """Feed one event; return the WindowMetrics snapshot(s) that became
        due as a result (usually 0 or 1, but more than one 5s step may have
        elapsed since the last event seen for this service)."""
        event = enriched.event
        sw = self._windows.setdefault(event.service, _ServiceWindow())
        sw.events.append(enriched)
        # No eager eviction here: after a long gap in traffic, the *newest*
        # event's ts can be far beyond the pending catch-up steps below, and
        # evicting against it immediately would wipe out the very data those
        # steps still need to snapshot. Eviction happens per-step instead,
        # using each step's own window_end (see the loop below) — found by
        # actually running the pipeline through a real gap-then-burst
        # sequence, not just steady synthetic traffic.
        if sw.next_emit_at is None:
            sw.next_emit_at = event.ts + timedelta(seconds=self.step_seconds)
            return []

        emitted: list[WindowMetrics] = []
        while event.ts >= sw.next_emit_at:
            self._evict_expired(sw, sw.next_emit_at)
            emitted.append(self._snapshot(event.service, sw, sw.next_emit_at))
            sw.next_emit_at += timedelta(seconds=self.step_seconds)
        return emitted

    def _evict_expired(self, sw: _ServiceWindow, as_of: datetime) -> None:
        cutoff = as_of - timedelta(seconds=self.window_seconds)
        while sw.events and sw.events[0].event.ts < cutoff:
            sw.events.popleft()

    def _snapshot(self, service: str, sw: _ServiceWindow, window_end: datetime) -> WindowMetrics:
        events = [e for e in sw.events if e.event.ts <= window_end]
        total = len(events)
        error_events = [e for e in events if e.event.is_error]
        errors = len(error_events)
        error_rate = errors / total if total else 0.0

        latencies = sorted(e.event.latency_ms for e in events)
        p95_latency_ms = _percentile(latencies, 0.95)

        urgent_errors = sum(1 for e in error_events if e.event.priority == "urgent")
        affected_patients_urgent = len(
            {e.event.patient_id for e in error_events if e.event.priority == "urgent" and e.event.patient_id}
        )
        affected_patients_routine = len(
            {e.event.patient_id for e in error_events if e.event.priority == "routine" and e.event.patient_id}
        )

        return WindowMetrics(
            service=service,
            window_end=window_end,
            total=total,
            errors=errors,
            error_rate=error_rate,
            p95_latency_ms=p95_latency_ms,
            urgent_errors=urgent_errors,
            affected_patients_urgent=affected_patients_urgent,
            affected_patients_routine=affected_patients_routine,
        )


def _percentile(sorted_values: list[float], pct: float) -> float:
    if not sorted_values:
        return 0.0
    idx = min(int(pct * len(sorted_values)), len(sorted_values) - 1)
    return float(sorted_values[idx])
