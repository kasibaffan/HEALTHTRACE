"""Milestone 3: severity formula boundaries, the HIPAA rule table, and each
scenario's expected severity from SPEC.md section 7 (service scenarios only
— the HIPAA scenarios need the access detector, built in Milestone 4)."""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

import pytest

from app.config import HipaaConfig, SeverityConfig, SeverityThresholds, load_config
from app.detect.severity import score_hipaa_anomaly, score_service_anomaly, score_to_severity
from app.models import Anomaly, WindowMetrics
from generator.generate import generate_batch
from tests.helpers import run_service_pipeline

THRESHOLDS = SeverityThresholds(low_max=0.30, medium_max=0.50, high_max=0.75)
SEVERITY_CONFIG = SeverityConfig(
    deviation_z_cap=6, patient_factor_cap=40, criticality_weight=0.5, patient_factor_weight=0.5,
    thresholds=THRESHOLDS,
)
HIPAA_CONFIG = HipaaConfig(
    bulk_multiplier_high=3, bulk_multiplier_critical=6, bulk_min_threshold=50,
    export_critical_records=100, off_hours_start="07:00", off_hours_end="21:00",
    off_hours_high_records=20, region_mismatch_medium_max=5,
)

T0 = datetime(2026, 9, 28, 12, 0, 0, tzinfo=timezone.utc)


def test_score_to_severity_boundaries():
    assert score_to_severity(0.0, THRESHOLDS) == "LOW"
    assert score_to_severity(0.29, THRESHOLDS) == "LOW"
    assert score_to_severity(0.30, THRESHOLDS) == "MEDIUM"
    assert score_to_severity(0.49, THRESHOLDS) == "MEDIUM"
    assert score_to_severity(0.50, THRESHOLDS) == "HIGH"
    assert score_to_severity(0.74, THRESHOLDS) == "HIGH"
    assert score_to_severity(0.75, THRESHOLDS) == "CRITICAL"
    assert score_to_severity(1.0, THRESHOLDS) == "CRITICAL"


def _metrics(**overrides) -> WindowMetrics:
    base = dict(
        service="prior_auth", window_end=T0, total=100, errors=38, error_rate=0.38,
        p95_latency_ms=300.0, urgent_errors=23, affected_patients_urgent=23, affected_patients_routine=0,
    )
    base.update(overrides)
    return WindowMetrics(**base)


def test_spec_worked_example_matches_explanation_text():
    # SPEC.md 6.6 gives this as an example of the explanation *string*, not a
    # claim about its severity — the severity assertions for this scenario
    # live in test_scenario_severity_matches_spec_table below, driven by the
    # actual generator output rather than this hand-picked (z, patient count).
    metrics = _metrics()
    anomaly = Anomaly(kind="error_rate", ts=T0, service="prior_auth", z=9.1, baseline_mean=0.02, baseline_std=0.04)
    alert = score_service_anomaly(anomaly, metrics, criticality=1.0, config=SEVERITY_CONFIG)
    assert "prior_auth error rate 38%" in alert.explanation
    assert "baseline 2%" in alert.explanation
    assert "z=9.1" in alert.explanation
    assert "23 urgent patients affected" in alert.explanation


def test_small_urgent_spike_outranks_large_routine_spike():
    """The spec's headline claim: a small urgent prior_auth spike beats a
    bigger routine batch spike, because of patient-impact weighting."""
    urgent_metrics = _metrics(
        service="prior_auth", errors=8, error_rate=0.08, urgent_errors=8,
        affected_patients_urgent=8, affected_patients_routine=0,
    )
    urgent_anomaly = Anomaly(kind="error_rate", ts=T0, service="prior_auth", z=4.0, baseline_mean=0.02)
    urgent_alert = score_service_anomaly(urgent_anomaly, urgent_metrics, criticality=1.0, config=SEVERITY_CONFIG)

    batch_metrics = _metrics(
        service="batch", total=200, errors=120, error_rate=0.60, urgent_errors=0,
        affected_patients_urgent=0, affected_patients_routine=0,
    )
    batch_anomaly = Anomaly(kind="error_rate", ts=T0, service="batch", z=4.0, baseline_mean=0.01)
    batch_alert = score_service_anomaly(batch_anomaly, batch_metrics, criticality=0.3, config=SEVERITY_CONFIG)

    assert urgent_alert.score > batch_alert.score
    assert batch_alert.severity == "LOW"


@pytest.mark.parametrize(
    "metrics_kwargs,severity",
    [
        (dict(multiplier=4.0, count=200, kind="hipaa_bulk_access"), "HIGH"),
        (dict(multiplier=7.0, count=350, kind="hipaa_bulk_access"), "CRITICAL"),
    ],
)
def test_hipaa_bulk_access_severity(metrics_kwargs, severity):
    kind = metrics_kwargs.pop("kind")
    anomaly = Anomaly(
        kind=kind, ts=T0, user_id="U-117",
        metrics={"multiplier": metrics_kwargs["multiplier"], "distinct_patients": metrics_kwargs["count"]},
    )
    alert = score_hipaa_anomaly(anomaly, HIPAA_CONFIG)
    assert alert.severity == severity


def test_hipaa_export_over_100_records_is_critical():
    anomaly = Anomaly(kind="hipaa_bulk_export", ts=T0, user_id="U-020", metrics={"records": 150})
    assert score_hipaa_anomaly(anomaly, HIPAA_CONFIG).severity == "CRITICAL"


def test_hipaa_export_under_100_records_is_medium():
    anomaly = Anomaly(kind="hipaa_bulk_export", ts=T0, user_id="U-020", metrics={"records": 40})
    assert score_hipaa_anomaly(anomaly, HIPAA_CONFIG).severity == "MEDIUM"


def test_hipaa_off_hours_severity_by_record_count():
    low = Anomaly(kind="hipaa_off_hours", ts=T0, user_id="U-042", metrics={"records": 5})
    high = Anomaly(kind="hipaa_off_hours", ts=T0, user_id="U-042", metrics={"records": 25})
    assert score_hipaa_anomaly(low, HIPAA_CONFIG).severity == "MEDIUM"
    assert score_hipaa_anomaly(high, HIPAA_CONFIG).severity == "HIGH"


def test_hipaa_region_mismatch_severity_by_patient_count():
    low = Anomaly(kind="hipaa_region_mismatch", ts=T0, user_id="U-088", metrics={"distinct_patients": 3})
    high = Anomaly(kind="hipaa_region_mismatch", ts=T0, user_id="U-088", metrics={"distinct_patients": 12})
    assert score_hipaa_anomaly(low, HIPAA_CONFIG).severity == "MEDIUM"
    assert score_hipaa_anomaly(high, HIPAA_CONFIG).severity == "HIGH"


# -- full scenario -> severity, through enrich/window/baseline/anomaly/severity --


def _run_scenario(name: str, seed: int, *, warmup_s: float = 240, scenario_s: float = 90, rate: float = 40):
    config = load_config()
    rng = random.Random(seed)
    normal_events, _ = generate_batch(None, warmup_s, rate, T0, rng)
    scenario_start = T0 + timedelta(seconds=warmup_s)
    scenario_events, _ = generate_batch(name, scenario_s, rate, scenario_start, rng)
    alerts = run_service_pipeline(normal_events + scenario_events, config)
    # Only alerts caused by the scenario itself, not any warm-up noise.
    return [a for a in alerts if a.ts >= scenario_start]


@pytest.mark.parametrize(
    "name,expected,seed",
    [
        ("urgent_prior_auth_failure", {"CRITICAL"}, 11),
        ("eligibility_outage", {"CRITICAL"}, 12),
        ("claims_degradation", {"LOW", "MEDIUM"}, 13),
        ("batch_spike", {"LOW"}, 14),
        ("latency_degradation", {"MEDIUM"}, 15),
    ],
)
def test_scenario_severity_matches_spec_table(name, expected, seed):
    alerts = _run_scenario(name, seed)
    assert alerts, f"{name}: expected at least one alert"
    order = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}
    peak = max(alerts, key=lambda a: order[a.severity])
    assert peak.severity in expected, (
        f"{name}: expected {expected}, got {peak.severity} " f"(all severities: {[a.severity for a in alerts]})"
    )
