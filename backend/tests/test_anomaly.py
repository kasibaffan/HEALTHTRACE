"""Milestone 3: anomaly thresholds and, critically, poisoning protection
(SPEC.md section 6.5) — during a sustained outage, the baseline mean must
not drift toward the outage rate."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

import random

from app.config import AnomalyConfig, BaselineConfig, load_config
from app.detect.anomaly import AnomalyEngine
from app.detect.baseline import BaselineEngine
from app.models import WindowMetrics
from app.parse.enricher import Enricher
from app.detect.window import SlidingWindow
from app.models import AppEvent
from generator.generate import generate_batch

T0 = datetime(2026, 9, 28, 9, 0, 0, tzinfo=timezone.utc)  # fixed hour=9, for determinism

ANOMALY_CONFIG = AnomalyConfig(
    min_std=0.01,
    error_rate_z_threshold=3.0,
    error_rate_min_errors=5,
    error_rate_min_rate=0.05,
    latency_z_threshold=4.0,
    latency_min_std_ms=20.0,
)
BASELINE_CONFIG = BaselineConfig(alpha=0.1, warmup_windows=12)


def make_metrics(
    offset_s: float,
    *,
    error_rate: float,
    errors: int = 10,
    total: int = 200,
    p95_latency_ms: float = 200.0,
    service: str = "claims",
) -> WindowMetrics:
    return WindowMetrics(
        service=service,
        window_end=T0 + timedelta(seconds=offset_s),
        total=total,
        errors=errors,
        error_rate=error_rate,
        p95_latency_ms=p95_latency_ms,
        urgent_errors=0,
        affected_patients_urgent=0,
        affected_patients_routine=0,
    )


def _warm_up(engine: AnomalyEngine, *, error_rate=0.02, p95=200.0, n=15, service="claims"):
    for i in range(n):
        engine.evaluate(make_metrics(i * 5, error_rate=error_rate, p95_latency_ms=p95, service=service))


def test_no_anomaly_before_baseline_is_warm():
    baseline = BaselineEngine(BASELINE_CONFIG)
    engine = AnomalyEngine(ANOMALY_CONFIG, baseline)
    result = engine.evaluate(make_metrics(0, error_rate=0.9, errors=180, total=200))
    assert result.anomalies == []


def test_flags_error_rate_spike_once_warm():
    baseline = BaselineEngine(BASELINE_CONFIG)
    engine = AnomalyEngine(ANOMALY_CONFIG, baseline)
    _warm_up(engine)
    result = engine.evaluate(make_metrics(1000, error_rate=0.35, errors=70, total=200))
    assert "error_rate" in [a.kind for a in result.anomalies]


def test_below_min_errors_is_not_flagged_even_with_high_rate():
    baseline = BaselineEngine(BASELINE_CONFIG)
    engine = AnomalyEngine(ANOMALY_CONFIG, baseline)
    _warm_up(engine)
    result = engine.evaluate(make_metrics(1000, error_rate=0.5, errors=2, total=4))
    assert result.anomalies == []


def test_below_min_rate_is_not_flagged():
    baseline = BaselineEngine(BASELINE_CONFIG)
    engine = AnomalyEngine(ANOMALY_CONFIG, baseline)
    _warm_up(engine)
    # errors >= 5 satisfied, but error_rate itself is below the 0.05 floor.
    result = engine.evaluate(make_metrics(1000, error_rate=0.03, errors=6, total=200))
    assert result.anomalies == []


def test_flags_latency_degradation():
    baseline = BaselineEngine(BASELINE_CONFIG)
    engine = AnomalyEngine(ANOMALY_CONFIG, baseline)
    _warm_up(engine, p95=200.0)
    result = engine.evaluate(make_metrics(1000, error_rate=0.02, errors=4, p95_latency_ms=1200.0))
    assert "latency_degradation" in [a.kind for a in result.anomalies]


def test_poisoning_protection_sustained_outage_does_not_drift_baseline():
    baseline = BaselineEngine(BASELINE_CONFIG)
    engine = AnomalyEngine(ANOMALY_CONFIG, baseline)
    _warm_up(engine, error_rate=0.02, n=15)

    mean_before = baseline.get("claims", 9, "error_rate").mean
    assert mean_before == pytest.approx(0.02, abs=0.01)

    # Sustained outage: 30 more windows at a 40% error rate.
    for i in range(30):
        engine.evaluate(make_metrics(1000 + i * 5, error_rate=0.40, errors=80, total=200))

    mean_after = baseline.get("claims", 9, "error_rate").mean
    assert mean_after == pytest.approx(mean_before, abs=0.01)
    assert mean_after < 0.05  # nowhere close to the 0.40 outage rate


def test_recovery_after_outage_resumes_learning():
    baseline = BaselineEngine(BASELINE_CONFIG)
    engine = AnomalyEngine(ANOMALY_CONFIG, baseline)
    _warm_up(engine, error_rate=0.02, n=15)

    for i in range(10):
        engine.evaluate(make_metrics(1000 + i * 5, error_rate=0.40, errors=80, total=200))

    # Back to normal: judged non-anomalous again, so the baseline resumes learning.
    for i in range(5):
        engine.evaluate(make_metrics(2000 + i * 5, error_rate=0.021, errors=4, total=200))

    mean_after_recovery = baseline.get("claims", 9, "error_rate").mean
    assert mean_after_recovery == pytest.approx(0.02, abs=0.01)


def test_real_config_does_not_false_positive_on_normal_traffic_across_seeds():
    """Regression test: found by running the anomaly engine against real
    generator output across multiple seeds, not just one (see README
    "Design decisions" — anomaly.latency_min_std_ms). p95 latency's natural
    window-to-window variance can occasionally be tiny by chance; the old
    shared min_std=0.01 (fine for error_rate, a 0-1 fraction) is a units
    mismatch for latency in milliseconds and spuriously fires on that noise."""
    config = load_config()
    T0 = datetime(2026, 9, 28, 9, 0, 0, tzinfo=timezone.utc)

    for seed in range(10):
        rng = random.Random(seed)
        app_events, _ = generate_batch(None, 1800, 40, T0, rng)  # 30 min normal traffic

        enricher = Enricher(config)
        window = SlidingWindow(config.window.size_seconds, config.window.step_seconds)
        baseline = BaselineEngine(config.baseline)
        anomaly_engine = AnomalyEngine(config.anomaly, baseline)

        for raw in app_events:
            event = AppEvent.model_validate(raw)
            enriched = enricher.enrich(event)
            for metrics in window.add(enriched):
                result = anomaly_engine.evaluate(metrics)
                assert result.anomalies == [], (seed, metrics.service, metrics.window_end, result.anomalies)
