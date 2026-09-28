"""Milestone 4: incident dedup, escalation, cooldown, auto-resolve, and MTTR
(SPEC.md section 6.8)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.config import IncidentConfig
from app.incidents.engine import IncidentEngine, fingerprint_for
from app.models import Alert, Anomaly

T0 = datetime(2026, 9, 28, 12, 0, 0, tzinfo=timezone.utc)

CONFIG = IncidentConfig(cooldown_minutes=5, service_auto_resolve_windows=6, hipaa_auto_resolve_minutes=10)


def service_anomaly(offset_s=0, *, service="claims", kind="error_rate", z=5.0) -> Anomaly:
    return Anomaly(kind=kind, ts=T0 + timedelta(seconds=offset_s), service=service, z=z)


def hipaa_anomaly(offset_s=0, *, user_id="U-117", kind="hipaa_bulk_access") -> Anomaly:
    return Anomaly(kind=kind, ts=T0 + timedelta(seconds=offset_s), user_id=user_id, metrics={"multiplier": 5.0})


def alert_for(anomaly: Anomaly, severity="HIGH", score=0.6) -> Alert:
    return Alert(
        ts=anomaly.ts, kind=anomaly.kind, service=anomaly.service, user_id=anomaly.user_id,
        severity=severity, score=score, explanation="x", metrics={},
    )


def test_fingerprint_rules():
    assert fingerprint_for(service_anomaly(service="claims", kind="error_rate")) == "error_rate:claims"
    assert fingerprint_for(hipaa_anomaly(user_id="U-1", kind="hipaa_bulk_access")) == "hipaa_bulk_access:U-1"


def test_new_alert_opens_an_incident():
    engine = IncidentEngine(CONFIG)
    anomaly = service_anomaly()
    update = engine.record_alert(anomaly, alert_for(anomaly, severity="MEDIUM"))
    assert update.is_new
    assert update.should_notify
    assert update.incident.state == "OPEN"
    assert update.incident.alert_count == 1
    assert update.incident.peak_severity == "MEDIUM"
    assert update.events[0].event_type == "opened"


def test_dedup_attaches_to_existing_open_incident_without_escalating():
    engine = IncidentEngine(CONFIG)
    a1 = service_anomaly(0)
    a2 = service_anomaly(5)
    update1 = engine.record_alert(a1, alert_for(a1, severity="MEDIUM"))
    update2 = engine.record_alert(a2, alert_for(a2, severity="MEDIUM"))

    assert not update2.is_new
    assert update2.incident.id == update1.incident.id
    assert update2.incident.alert_count == 2
    assert update2.incident.peak_severity == "MEDIUM"
    assert not update2.should_notify  # same severity: no re-notification
    assert update2.events[0].event_type == "alert_attached"


def test_escalation_bumps_peak_severity_and_notifies():
    engine = IncidentEngine(CONFIG)
    a1 = service_anomaly(0)
    a2 = service_anomaly(5)
    engine.record_alert(a1, alert_for(a1, severity="LOW"))
    update2 = engine.record_alert(a2, alert_for(a2, severity="CRITICAL"))

    assert update2.is_escalation
    assert update2.should_notify
    assert update2.incident.peak_severity == "CRITICAL"
    assert update2.events[0].event_type == "escalated"


def test_a_lower_severity_alert_does_not_de_escalate():
    engine = IncidentEngine(CONFIG)
    a1 = service_anomaly(0)
    a2 = service_anomaly(5)
    engine.record_alert(a1, alert_for(a1, severity="CRITICAL"))
    update2 = engine.record_alert(a2, alert_for(a2, severity="LOW"))
    assert update2.incident.peak_severity == "CRITICAL"
    assert not update2.should_notify


def test_manual_ack_then_resolve_records_mttr():
    engine = IncidentEngine(CONFIG)
    anomaly = service_anomaly(0)
    opened = engine.record_alert(anomaly, alert_for(anomaly))
    incident_id = opened.incident.id

    ack_time = T0 + timedelta(seconds=30)
    ack_update = engine.acknowledge(incident_id, ack_time)
    assert ack_update is not None
    assert ack_update.incident.state == "ACKNOWLEDGED"
    assert ack_update.incident.acknowledged_at == ack_time

    resolve_time = T0 + timedelta(seconds=90)
    resolve_update = engine.resolve(incident_id, resolve_time)
    assert resolve_update is not None
    assert resolve_update.incident.state == "RESOLVED"
    assert resolve_update.incident.mttr_seconds == pytest.approx(90.0)
    assert resolve_update.events[0].event_type == "resolved"


def test_cannot_ack_an_already_resolved_incident():
    engine = IncidentEngine(CONFIG)
    anomaly = service_anomaly(0)
    incident_id = engine.record_alert(anomaly, alert_for(anomaly)).incident.id
    engine.resolve(incident_id, T0 + timedelta(seconds=10))
    assert engine.acknowledge(incident_id, T0 + timedelta(seconds=20)) is None
    assert engine.resolve(incident_id, T0 + timedelta(seconds=20)) is None


def test_cooldown_suppresses_notification_but_still_records_the_alert():
    engine = IncidentEngine(CONFIG)
    a1 = service_anomaly(0)
    incident_id = engine.record_alert(a1, alert_for(a1)).incident.id
    engine.resolve(incident_id, T0 + timedelta(seconds=10))

    # A new matching alert 1 minute later: well inside the 5-minute cooldown.
    a2 = service_anomaly(70)
    update = engine.record_alert(a2, alert_for(a2, severity="CRITICAL"))
    assert update.is_new  # still recorded, as its own new incident
    assert not update.should_notify  # but suppressed by cooldown
    assert update.incident.id != incident_id


def test_cooldown_expires_after_configured_minutes():
    engine = IncidentEngine(CONFIG)
    a1 = service_anomaly(0)
    incident_id = engine.record_alert(a1, alert_for(a1)).incident.id
    engine.resolve(incident_id, T0 + timedelta(seconds=10))

    # 6 minutes later: past the 5-minute cooldown.
    a2 = service_anomaly(10 + 6 * 60)
    update = engine.record_alert(a2, alert_for(a2))
    assert update.should_notify


def test_service_incident_auto_resolves_after_6_consecutive_normal_windows():
    engine = IncidentEngine(CONFIG)
    anomaly = service_anomaly(0)
    engine.record_alert(anomaly, alert_for(anomaly))

    for i in range(1, 6):
        update = engine.record_normal_window("error_rate", "claims", T0 + timedelta(seconds=i * 5))
        assert update is None  # not yet at 6

    final_update = engine.record_normal_window("error_rate", "claims", T0 + timedelta(seconds=6 * 5))
    assert final_update is not None
    assert final_update.incident.state == "RESOLVED"
    assert final_update.events[0].event_type == "auto_resolved"
    assert final_update.incident.mttr_seconds == pytest.approx(30.0)


def test_a_new_alert_resets_the_normal_window_streak():
    engine = IncidentEngine(CONFIG)
    a1 = service_anomaly(0)
    engine.record_alert(a1, alert_for(a1))

    for i in range(1, 4):
        engine.record_normal_window("error_rate", "claims", T0 + timedelta(seconds=i * 5))

    # A fresh alert before reaching 6 -> streak resets.
    a2 = service_anomaly(4 * 5)
    engine.record_alert(a2, alert_for(a2))

    for i in range(5, 5 + 5):  # only 5 more normal windows: should not resolve yet
        update = engine.record_normal_window("error_rate", "claims", T0 + timedelta(seconds=i * 5))
        assert update is None


def test_hipaa_incident_auto_resolves_after_10_minutes_with_no_new_alert():
    engine = IncidentEngine(CONFIG)
    anomaly = hipaa_anomaly(0)
    engine.record_alert(anomaly, alert_for(anomaly, severity="HIGH"))

    # Before the 10-minute timeout: nothing resolves.
    early_updates = engine.sweep_hipaa_timeouts(T0 + timedelta(minutes=9))
    assert early_updates == []

    late_updates = engine.sweep_hipaa_timeouts(T0 + timedelta(minutes=11))
    assert len(late_updates) == 1
    assert late_updates[0].incident.state == "RESOLVED"
    assert late_updates[0].events[0].event_type == "auto_resolved"


def test_hipaa_timeout_is_not_reset_by_service_normal_windows():
    engine = IncidentEngine(CONFIG)
    anomaly = hipaa_anomaly(0)
    engine.record_alert(anomaly, alert_for(anomaly))
    # Unrelated service fingerprint: must not interfere with the HIPAA incident.
    engine.record_normal_window("error_rate", "claims", T0 + timedelta(seconds=5))
    updates = engine.sweep_hipaa_timeouts(T0 + timedelta(minutes=11))
    assert len(updates) == 1


def test_different_services_get_independent_incidents():
    engine = IncidentEngine(CONFIG)
    a_claims = service_anomaly(service="claims")
    a_pharmacy = service_anomaly(service="pharmacy")
    u1 = engine.record_alert(a_claims, alert_for(a_claims))
    u2 = engine.record_alert(a_pharmacy, alert_for(a_pharmacy))
    assert u1.incident.id != u2.incident.id
    assert u1.is_new and u2.is_new


def test_list_incidents_filters_by_state():
    engine = IncidentEngine(CONFIG)
    a1 = service_anomaly(service="claims")
    a2 = service_anomaly(service="pharmacy")
    id1 = engine.record_alert(a1, alert_for(a1)).incident.id
    engine.record_alert(a2, alert_for(a2))
    engine.resolve(id1, T0 + timedelta(seconds=10))

    assert len(engine.list_incidents()) == 2
    assert len(engine.list_incidents(state="OPEN")) == 1
    assert len(engine.list_incidents(state="RESOLVED")) == 1
