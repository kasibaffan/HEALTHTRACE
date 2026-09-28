"""Milestone 1: generated lines must validate against the shared models, and
each scenario in SPEC.md section 7 must produce the traffic shape it
promises. Severity itself (LOW/MEDIUM/HIGH/CRITICAL) is Milestone 3 — these
tests only check the generator's output shape.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from app.models import AppEvent, AuditEvent
from generator.generate import SERVICES, generate_batch
from generator.scenarios import ACCESS_SCENARIOS, SERVICE_SCENARIOS

START = datetime(2026, 9, 28, 12, 0, 0, tzinfo=timezone.utc)


def _generate(scenario, duration_s=120, rate=40, seed=1):
    rng = random.Random(seed)
    return generate_batch(scenario, duration_s, rate, START, rng)


def _validate_all(app_events, audit_events):
    for e in app_events:
        AppEvent.model_validate(e)
    for e in audit_events:
        AuditEvent.model_validate(e)


def test_normal_traffic_validates_and_covers_all_services():
    app_events, audit_events = _generate(None, duration_s=300, rate=40)
    assert app_events and audit_events
    _validate_all(app_events, audit_events)
    assert {e["service"] for e in app_events} == set(SERVICES)


def test_normal_error_rate_within_spec_band():
    app_events, _ = _generate(None, duration_s=600, rate=50, seed=7)
    errors = [e for e in app_events if AppEvent.model_validate(e).is_error]
    rate = len(errors) / len(app_events)
    # Spec: "realistic error rates of 0.5-3%" per service; the cross-service
    # blend should stay comfortably below that, with slack for randomness.
    assert 0.0 <= rate <= 0.08


def test_malformed_events_are_rejected_by_the_model():
    base = {
        "priority": "urgent", "request_id": "X-1", "status": 500,
        "latency_ms": 10, "msg": "bad",
    }
    with pytest.raises(ValidationError):
        AppEvent.model_validate({**base, "ts": "not-a-time", "service": "claims", "level": "ERROR"})
    with pytest.raises(ValidationError):
        AppEvent.model_validate({**base, "ts": START.isoformat(), "service": "not-a-service", "level": "ERROR"})
    with pytest.raises(ValidationError):
        AppEvent.model_validate({**base, "ts": START.isoformat(), "service": "claims", "level": "CRITICAL"})


@pytest.mark.parametrize("name,scn", sorted(SERVICE_SCENARIOS.items()))
def test_service_scenarios_validate_and_match_expected_shape(name, scn):
    app_events, audit_events = _generate(name, duration_s=120, rate=40, seed=hash(name) % 1000)
    _validate_all(app_events, audit_events)

    target = [e for e in app_events if e["service"] == scn.service]
    assert target, f"no events generated for {scn.service}"
    errors = [e for e in target if AppEvent.model_validate(e).is_error]
    observed_rate = len(errors) / len(target)
    assert abs(observed_rate - scn.error_rate) < 0.15, (name, observed_rate, scn.error_rate)

    if not scn.affected_patients:
        assert all(e["patient_id"] is None for e in target)
    else:
        assert all(e["patient_id"] is not None for e in errors)

    if scn.urgent_fraction > 0.5:
        urgent_errors = [e for e in errors if e["priority"] == "urgent"]
        assert len(urgent_errors) / max(len(errors), 1) > 0.5


def test_urgent_prior_auth_failure_affects_20_plus_patients():
    app_events, _ = _generate("urgent_prior_auth_failure", duration_s=180, rate=45, seed=3)
    errors = [e for e in app_events if e["service"] == "prior_auth" and AppEvent.model_validate(e).is_error]
    patients = {e["patient_id"] for e in errors if e["patient_id"]}
    assert len(patients) >= 20


def test_batch_spike_has_no_patients_but_high_error_rate():
    app_events, _ = _generate("batch_spike", duration_s=120, rate=40, seed=4)
    batch = [e for e in app_events if e["service"] == "batch"]
    assert batch and all(e["patient_id"] is None for e in batch)
    errors = [e for e in batch if AppEvent.model_validate(e).is_error]
    assert len(errors) / len(batch) > 0.4


def test_latency_degradation_raises_pharmacy_p95():
    def p95(latencies: list[int]) -> int:
        return sorted(latencies)[int(0.95 * len(latencies)) - 1]

    normal, _ = _generate(None, duration_s=180, rate=40, seed=5)
    scenario, _ = _generate("latency_degradation", duration_s=180, rate=40, seed=5)
    normal_p95 = p95([e["latency_ms"] for e in normal if e["service"] == "pharmacy"])
    scenario_p95 = p95([e["latency_ms"] for e in scenario if e["service"] == "pharmacy"])
    assert scenario_p95 > normal_p95 * 3


@pytest.mark.parametrize("name,scn", sorted(ACCESS_SCENARIOS.items()))
def test_access_scenarios_validate(name, scn):
    _, audit_events = _generate(name, duration_s=300, rate=30, seed=hash(name) % 1000)
    _validate_all([], audit_events)

    target_events = [e for e in audit_events if e["user_id"] == scn.user_id]
    assert target_events
    if scn.kind == "region_mismatch":
        assert all(e["patient_region"] != e["user_region"] for e in target_events)
    if scn.kind == "off_hours":
        assert all(e["ts"][11:13] == "03" for e in target_events)
    # A loose bound: total_patients is a Poisson-process target, not exact, and
    # off_hours_access/region_mismatch use small counts (12-15) where a tight
    # bound would make this test flaky. This still catches a pace/count bug.
    patients = {e["patient_id"] for e in target_events}
    assert len(patients) >= scn.total_patients * 0.3


def test_recovery_scenario_is_plain_normal_traffic():
    app_events, audit_events = _generate("recovery", duration_s=120, rate=30, seed=6)
    _validate_all(app_events, audit_events)
    assert app_events and audit_events


def test_backfill_window_ends_at_the_given_time_and_validates():
    # Mirrors generate.py's main(): backfill starts `hours` before "now" and
    # ends at "now", i.e. it produces past timestamps, not future ones.
    rng = random.Random(9)
    hours = 24
    end = START
    start = end - timedelta(hours=hours)
    app_events, audit_events = generate_batch(None, hours * 3600, 30, start, rng)
    _validate_all(app_events, audit_events)
    first_ts = datetime.fromisoformat(app_events[0]["ts"].replace("Z", "+00:00"))
    last_ts = datetime.fromisoformat(app_events[-1]["ts"].replace("Z", "+00:00"))
    assert first_ts >= start
    assert last_ts <= end


def test_unknown_scenario_name_is_rejected():
    with pytest.raises(ValueError):
        generate_batch("not_a_real_scenario", 10, 10, START, random.Random(1))
