"""Milestone 2: the sliding window emits metrics every 5s of event time over
the last 60s, and computes error rate / p95 latency / patient counts
correctly (SPEC.md section 6.3)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.detect.window import SlidingWindow
from app.models import AppEvent
from app.parse.enricher import EnrichedAppEvent

T0 = datetime(2026, 9, 28, 12, 0, 0, tzinfo=timezone.utc)


def make_event(
    offset_s: float,
    *,
    service: str = "claims",
    level: str = "INFO",
    status: int = 200,
    priority: str = "routine",
    patient_id: str | None = "P-000001",
    latency_ms: int = 100,
) -> EnrichedAppEvent:
    event = AppEvent(
        ts=T0 + timedelta(seconds=offset_s),
        service=service,
        level=level,
        priority=priority,
        request_id="X-1",
        patient_id=patient_id,
        status=status,
        latency_ms=latency_ms,
        msg="x",
    )
    return EnrichedAppEvent(event=event, criticality=0.6, priority_weight=1 if priority == "routine" else 2)


def test_no_snapshot_from_a_single_event():
    window = SlidingWindow()
    emitted = window.add(make_event(0))
    assert emitted == []


def test_emits_every_5s_of_event_time():
    window = SlidingWindow(window_seconds=60, step_seconds=5)
    emissions = []
    for t in range(0, 12):
        emissions.extend(window.add(make_event(t)))
    # events at t=0..11; first emit due once ts crosses t=5, again at t=10.
    assert len(emissions) == 2
    assert emissions[0].window_end == T0 + timedelta(seconds=5)
    assert emissions[1].window_end == T0 + timedelta(seconds=10)


def test_error_rate_counts_error_level_or_5xx_status():
    window = SlidingWindow(window_seconds=60, step_seconds=5)
    for i in range(4):
        window.add(make_event(i, level="ERROR", status=500))
    for i in range(4, 8):
        window.add(make_event(i, level="WARN", status=400))
    window.add(make_event(8, level="INFO", status=502))  # 5xx but INFO still counts as error
    # Trigger the window_end=10s snapshot; ts=11 > window_end so this event
    # itself is excluded from the snapshot it triggers.
    emitted = window.add(make_event(11, level="INFO", status=200))
    snap = emitted[-1]
    assert snap.total == 9
    assert snap.errors == 5  # 4 ERROR + 1 status>=500
    assert snap.error_rate == 5 / 9


def test_p95_latency():
    window = SlidingWindow(window_seconds=60, step_seconds=5)
    for i in range(20):
        window.add(make_event(i * 0.2, latency_ms=i + 1))  # latencies 1..20, all within the first 4s
    # Trigger the window_end=5s snapshot from outside the window it should
    # cover, so it's excluded from its own snapshot.
    emitted = window.add(make_event(6, latency_ms=999))
    snap = emitted[0]
    assert snap.total == 20
    assert snap.p95_latency_ms == 20.0  # nearest-rank of 20 samples


def test_urgent_errors_and_affected_patient_counts():
    window = SlidingWindow(window_seconds=60, step_seconds=5)
    window.add(make_event(0, level="ERROR", status=500, priority="urgent", patient_id="P-000001"))
    window.add(make_event(1, level="ERROR", status=500, priority="urgent", patient_id="P-000001"))  # dup patient
    window.add(make_event(2, level="ERROR", status=500, priority="urgent", patient_id="P-000002"))
    window.add(make_event(3, level="ERROR", status=500, priority="routine", patient_id="P-000003"))
    emitted = window.add(make_event(5, level="INFO", status=200, priority="routine", patient_id="P-000004"))
    snap = emitted[0]
    assert snap.urgent_errors == 3
    assert snap.affected_patients_urgent == 2  # P-000001 (x2), P-000002
    assert snap.affected_patients_routine == 1  # P-000003 (the non-error P-000004 doesn't count)


def test_batch_events_with_no_patient_id_do_not_count_as_affected():
    window = SlidingWindow(window_seconds=60, step_seconds=5)
    window.add(make_event(0, service="batch", level="ERROR", status=500, patient_id=None))
    emitted = window.add(make_event(5, service="batch", level="ERROR", status=500, patient_id=None))
    snap = emitted[0]
    assert snap.errors == 2
    assert snap.affected_patients_urgent == 0
    assert snap.affected_patients_routine == 0


def test_events_older_than_60s_are_evicted():
    window = SlidingWindow(window_seconds=60, step_seconds=5)
    window.add(make_event(0))
    emitted = window.add(make_event(65))
    snap = emitted[-1]
    # window_end is near t=65; the t=0 event is now >60s old and must be gone.
    assert snap.total == 1


def test_services_are_windowed_independently():
    window = SlidingWindow(window_seconds=60, step_seconds=5)
    for i in range(6):
        window.add(make_event(i, service="claims", level="ERROR", status=500))

    window.add(make_event(0, service="pharmacy", level="INFO", status=200))
    emitted = window.add(make_event(5, service="pharmacy", level="INFO", status=200))
    assert emitted and emitted[0].service == "pharmacy"
    assert emitted[0].total == 2
    assert emitted[0].errors == 0
