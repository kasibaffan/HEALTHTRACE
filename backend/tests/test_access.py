"""Milestone 4: HIPAA access-pattern detection (SPEC.md section 6.7)."""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

import pytest

from app.config import HipaaConfig, load_config
from app.detect.access import AccessDetector
from app.models import AuditEvent
from generator.generate import generate_batch

T0 = datetime(2026, 9, 28, 13, 0, 0, tzinfo=timezone.utc)  # 13:00, inside business hours

CONFIG = HipaaConfig(
    bulk_multiplier_high=3, bulk_multiplier_critical=6, bulk_min_threshold=50, export_min_threshold=50,
    export_critical_records=100, off_hours_start="07:00", off_hours_end="21:00",
    off_hours_high_records=20, region_mismatch_medium_max=5,
)


def audit_event(offset_s, *, user_id="U-100", action="VIEW_RECORD", patient_id, region="TN-North", user_region=None):
    return AuditEvent(
        ts=T0 + timedelta(seconds=offset_s), user_id=user_id, role="care_manager", action=action,
        patient_id=patient_id, patient_region=region, user_region=user_region or region,
    )


def test_new_user_bulk_access_uses_the_flat_floor_threshold():
    detector = AccessDetector(CONFIG)
    anomalies = []
    for i in range(60):
        anomalies = detector.evaluate(audit_event(i, patient_id=f"P-{i:06d}"))
    kinds = [a.kind for a in anomalies]
    assert "hipaa_bulk_access" in kinds
    bulk = next(a for a in anomalies if a.kind == "hipaa_bulk_access")
    assert bulk.metrics["distinct_patients"] == 60


def test_below_floor_threshold_does_not_fire():
    detector = AccessDetector(CONFIG)
    anomalies = []
    for i in range(40):
        anomalies = detector.evaluate(audit_event(i, patient_id=f"P-{i:06d}"))
    assert "hipaa_bulk_access" not in [a.kind for a in anomalies]


def test_established_baseline_raises_threshold_above_the_floor():
    # Prime the user's baseline directly, isolating threshold *selection*
    # from how the baseline is *learned* (covered by the periodic-sampling
    # test below).
    detector = AccessDetector(CONFIG)
    detector.evaluate(audit_event(0, user_id="U-200", patient_id="P-000001"))
    state = detector._users["U-200"]
    state.baseline_mean = 20.0
    state.baseline_count = 10

    # 3x baseline = 60, above the 50 floor -> 60 is now the effective threshold.
    anomalies = []
    for i in range(59):  # + the 1 priming event = 60 distinct, still within the 10-min window
        anomalies = detector.evaluate(audit_event(100 + i, user_id="U-200", patient_id=f"P-{100000 + i:06d}"))
    assert "hipaa_bulk_access" not in [a.kind for a in anomalies]

    anomalies = detector.evaluate(audit_event(200, user_id="U-200", patient_id="P-999999"))
    bulk = next(a for a in anomalies if a.kind == "hipaa_bulk_access")
    assert bulk.metrics["distinct_patients"] == 61
    assert bulk.metrics["multiplier"] == pytest.approx(61 / 20.0)


def test_baseline_samples_once_per_rolling_window_not_every_event():
    """A fast burst must not poison its own baseline mid-burst (README
    "Design decisions"): sampling only happens once per 10-minute period."""
    detector = AccessDetector(CONFIG, baseline_alpha=0.5)
    user = "U-201"
    # A single ~59s burst of 55 distinct patients (above the 50 floor).
    anomalies = []
    for i in range(55):
        anomalies = detector.evaluate(audit_event(i, user_id=user, patient_id=f"P-{i:06d}"))
    assert "hipaa_bulk_access" in [a.kind for a in anomalies]
    # The burst is still mid-window (no 10-minute boundary crossed yet) ->
    # baseline must still be untouched, not dragged up by the burst itself.
    state = detector._users[user]
    assert state.baseline_count == 0


def test_bulk_export_fires_above_the_floor():
    detector = AccessDetector(CONFIG)
    anomalies = []
    for i in range(60):
        anomalies = detector.evaluate(
            audit_event(i, action="EXPORT_RECORDS", user_id="U-020", patient_id=f"P-{i:06d}")
        )
    assert "hipaa_bulk_export" in [a.kind for a in anomalies]
    export = next(a for a in anomalies if a.kind == "hipaa_bulk_export")
    assert export.metrics["records"] == 60


def test_off_hours_access_is_flagged():
    off_hours_ts_offset = 0
    off_hours_time = T0.replace(hour=3, minute=0, second=0)  # 03:00, outside 07:00-21:00
    detector = AccessDetector(CONFIG)
    event = AuditEvent(
        ts=off_hours_time, user_id="U-042", role="care_manager", action="VIEW_RECORD",
        patient_id="P-000001", patient_region="TN-North", user_region="TN-North",
    )
    anomalies = detector.evaluate(event)
    assert "hipaa_off_hours" in [a.kind for a in anomalies]


def test_in_hours_access_is_not_flagged_as_off_hours():
    detector = AccessDetector(CONFIG)
    anomalies = detector.evaluate(audit_event(0, patient_id="P-000001"))  # T0 = 13:00
    assert "hipaa_off_hours" not in [a.kind for a in anomalies]


def test_off_hours_record_count_drives_medium_vs_high_via_metrics():
    off_hours_time = T0.replace(hour=3, minute=0, second=0)
    detector = AccessDetector(CONFIG)
    anomalies = []
    for i in range(25):
        event = AuditEvent(
            ts=off_hours_time + timedelta(seconds=i), user_id="U-042", role="care_manager", action="VIEW_RECORD",
            patient_id=f"P-{i:06d}", patient_region="TN-North", user_region="TN-North",
        )
        anomalies = detector.evaluate(event)
    off_hours_alert = next(a for a in anomalies if a.kind == "hipaa_off_hours")
    assert off_hours_alert.metrics["records"] == 25  # > 20 -> HIGH per the severity table


def test_region_mismatch_is_flagged_with_distinct_patient_count():
    detector = AccessDetector(CONFIG)
    anomalies = []
    for i in range(3):
        event = audit_event(i, user_id="U-088", patient_id=f"P-{i:06d}", region="TN-South", user_region="TN-North")
        anomalies = detector.evaluate(event)
    mismatch = next(a for a in anomalies if a.kind == "hipaa_region_mismatch")
    assert mismatch.metrics["distinct_patients"] == 3


def test_matching_region_is_not_flagged():
    detector = AccessDetector(CONFIG)
    anomalies = detector.evaluate(audit_event(0, patient_id="P-000001", region="TN-North", user_region="TN-North"))
    assert "hipaa_region_mismatch" not in [a.kind for a in anomalies]


def test_rolling_window_evicts_after_10_minutes():
    detector = AccessDetector(CONFIG)
    for i in range(60):
        detector.evaluate(audit_event(i, patient_id=f"P-{i:06d}"))
    # 11 minutes later: the old 60 should have rolled off the 10-minute window.
    anomalies = detector.evaluate(audit_event(11 * 60, patient_id="P-999999"))
    assert "hipaa_bulk_access" not in [a.kind for a in anomalies]


def test_real_config_does_not_false_positive_on_normal_traffic():
    """Regression test: found by actually running the backend against real
    generator output (see README "Design decisions" — bulk_min_threshold).
    30 minutes of pure normal traffic must never trip hipaa_bulk_access, and
    the real bulk_phi_access scenario must still reliably fire."""
    config = load_config().hipaa
    detector = AccessDetector(config)

    rng = random.Random(5)
    T0 = datetime(2026, 9, 28, 9, 0, 0, tzinfo=timezone.utc)
    _, normal_events = generate_batch(None, 1800, 40, T0, rng)
    for raw in normal_events:
        anomalies = detector.evaluate(AuditEvent.model_validate(raw))
        assert not any(a.kind == "hipaa_bulk_access" for a in anomalies)

    scenario_detector = AccessDetector(config)
    rng2 = random.Random(99)
    _, scenario_events = generate_batch("bulk_phi_access", 300, 40, T0, rng2)
    fired = any(
        a.kind == "hipaa_bulk_access"
        for raw in scenario_events
        for a in scenario_detector.evaluate(AuditEvent.model_validate(raw))
    )
    assert fired


def test_users_are_tracked_independently():
    detector = AccessDetector(CONFIG)
    anomalies_a = []
    for i in range(60):
        anomalies_a = detector.evaluate(audit_event(i, user_id="U-A", patient_id=f"P-{i:06d}"))
    anomalies_b = detector.evaluate(audit_event(0, user_id="U-B", patient_id="P-000001"))
    assert "hipaa_bulk_access" in [a.kind for a in anomalies_a]
    assert "hipaa_bulk_access" not in [a.kind for a in anomalies_b]
