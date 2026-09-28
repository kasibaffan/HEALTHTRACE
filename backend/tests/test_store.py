"""Milestone 4: SQLite persistence for alerts, incidents, incident_events,
and access_stats (SPEC.md section 6.10)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.models import Alert, Incident, IncidentEvent, WindowMetrics
from app.store.db import Store

T0 = datetime(2026, 9, 28, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
async def store(tmp_path: Path):
    s = Store(tmp_path / "medguard.db")
    await s.connect()
    yield s
    await s.close()


def make_metrics(window_end, **overrides) -> WindowMetrics:
    base = dict(
        service="claims", window_end=window_end, total=100, errors=5, error_rate=0.05,
        p95_latency_ms=200.0, urgent_errors=0, affected_patients_urgent=0, affected_patients_routine=5,
    )
    base.update(overrides)
    return WindowMetrics(**base)


async def test_save_and_list_metrics_within_window(store: Store):
    await store.save_metrics(make_metrics(T0))
    await store.save_metrics(make_metrics(T0 + timedelta(minutes=5)))
    await store.save_metrics(make_metrics(T0 + timedelta(minutes=20)))  # outside a 15-min lookback from the last

    rows = await store.list_metrics(service="claims", minutes=15, before=T0 + timedelta(minutes=20))
    assert len(rows) == 2  # T0 and T0+5min are within 15 minutes of T0+20min; T0 itself is exactly at the edge

    rows_narrow = await store.list_metrics(service="claims", minutes=1, before=T0 + timedelta(minutes=20))
    assert len(rows_narrow) == 1


async def test_metrics_older_than_24h_are_pruned(store: Store):
    await store.save_metrics(make_metrics(T0))
    await store.save_metrics(make_metrics(T0 + timedelta(hours=25)))  # triggers pruning of the first row

    rows = await store.list_metrics(service="claims", minutes=60 * 30, before=T0 + timedelta(hours=25))
    assert len(rows) == 1
    assert rows[0].window_end == T0 + timedelta(hours=25)


async def test_save_and_list_alerts(store: Store):
    alert = Alert(
        ts=T0, kind="error_rate", service="prior_auth", severity="CRITICAL", score=0.9,
        explanation="x", metrics={"total": 100},
    )
    alert_id = await store.save_alert(alert)
    assert alert_id > 0

    alerts = await store.list_alerts(limit=10)
    assert len(alerts) == 1
    assert alerts[0].id == alert_id
    assert alerts[0].service == "prior_auth"
    assert alerts[0].severity == "CRITICAL"
    assert alerts[0].metrics == {"total": 100}


async def test_list_alerts_filters_by_severity(store: Store):
    await store.save_alert(Alert(ts=T0, kind="error_rate", service="claims", severity="LOW", score=0.1, explanation="x"))
    await store.save_alert(Alert(ts=T0, kind="error_rate", service="claims", severity="HIGH", score=0.6, explanation="y"))

    high_only = await store.list_alerts(severity="HIGH")
    assert len(high_only) == 1
    assert high_only[0].severity == "HIGH"


async def test_list_alerts_orders_newest_first(store: Store):
    await store.save_alert(Alert(ts=T0, kind="error_rate", service="claims", severity="LOW", score=0.1, explanation="old"))
    await store.save_alert(
        Alert(ts=T0 + timedelta(seconds=10), kind="error_rate", service="claims", severity="LOW", score=0.1, explanation="new")
    )
    alerts = await store.list_alerts(limit=10)
    assert alerts[0].explanation == "new"
    assert alerts[1].explanation == "old"


async def test_upsert_and_get_incident(store: Store):
    incident = Incident(
        id=1, fingerprint="error_rate:claims", kind="error_rate", service="claims", state="OPEN",
        peak_severity="MEDIUM", alert_count=1, opened_at=T0,
    )
    await store.upsert_incident(incident)

    fetched = await store.get_incident(1)
    assert fetched is not None
    assert fetched.state == "OPEN"
    assert fetched.peak_severity == "MEDIUM"

    incident.state = "RESOLVED"
    incident.resolved_at = T0 + timedelta(seconds=60)
    incident.mttr_seconds = 60.0
    incident.peak_severity = "HIGH"
    incident.alert_count = 3
    await store.upsert_incident(incident)

    updated = await store.get_incident(1)
    assert updated is not None
    assert updated.state == "RESOLVED"
    assert updated.mttr_seconds == pytest.approx(60.0)
    assert updated.alert_count == 3
    assert updated.peak_severity == "HIGH"


async def test_list_incidents_filters_by_state(store: Store):
    open_incident = Incident(
        id=1, fingerprint="a", kind="error_rate", service="claims", state="OPEN",
        peak_severity="LOW", alert_count=1, opened_at=T0,
    )
    resolved_incident = Incident(
        id=2, fingerprint="b", kind="error_rate", service="pharmacy", state="RESOLVED",
        peak_severity="LOW", alert_count=1, opened_at=T0, resolved_at=T0 + timedelta(seconds=5), mttr_seconds=5.0,
    )
    await store.upsert_incident(open_incident)
    await store.upsert_incident(resolved_incident)

    assert len(await store.list_incidents()) == 2
    assert len(await store.list_incidents(state="OPEN")) == 1
    assert len(await store.list_incidents(state="RESOLVED")) == 1


async def test_incident_events_round_trip(store: Store):
    incident = Incident(
        id=1, fingerprint="a", kind="error_rate", service="claims", state="OPEN",
        peak_severity="LOW", alert_count=1, opened_at=T0,
    )
    await store.upsert_incident(incident)
    await store.save_incident_event(IncidentEvent(incident_id=1, ts=T0, event_type="opened", severity="LOW"))
    await store.save_incident_event(
        IncidentEvent(incident_id=1, ts=T0 + timedelta(seconds=5), event_type="escalated", severity="HIGH")
    )

    events = await store.list_incident_events(1)
    assert [e.event_type for e in events] == ["opened", "escalated"]
    assert events[1].severity == "HIGH"


async def test_access_stats_round_trip(store: Store):
    await store.save_access_stat("U-117", "distinct_patients_10min", mean=12.5, variance=3.0, count=8)
    rows = await store.load_access_stats()
    assert rows == [("U-117", "distinct_patients_10min", 12.5, 3.0, 8)]

    await store.save_access_stat("U-117", "distinct_patients_10min", mean=15.0, variance=4.0, count=9)
    rows = await store.load_access_stats()
    assert len(rows) == 1  # upsert, not a second row
    assert rows[0][2] == 15.0
