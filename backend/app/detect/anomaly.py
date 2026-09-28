"""z-score anomaly detection against the baseline engine (SPEC.md section 6.5).

For each WindowMetrics, checks error_rate (kind="error_rate") and
p95_latency_ms (kind="latency_degradation") against their own baselines.
Whichever metric's check comes back non-anomalous is fed back into the
baseline via ``BaselineEngine.update`` — this is the poisoning-protection
loop from the architecture diagram, applied per metric so an anomaly in one
metric doesn't block the other from still learning.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from math import sqrt

from app.config import AnomalyConfig
from app.detect.baseline import BaselineEngine
from app.models import Anomaly, WindowMetrics


@dataclass
class AnomalyResult:
    anomalies: list[Anomaly] = field(default_factory=list)
    error_rate_normal: bool = True
    latency_normal: bool = True


class AnomalyEngine:
    def __init__(self, config: AnomalyConfig, baseline: BaselineEngine) -> None:
        self._config = config
        self._baseline = baseline

    def evaluate(self, metrics: WindowMetrics) -> AnomalyResult:
        hour = metrics.window_end.hour
        anomalies: list[Anomaly] = []

        error_rate_normal = self._check_error_rate(metrics, hour, anomalies)
        latency_normal = self._check_latency(metrics, hour, anomalies)

        # Poisoning protection (SPEC.md 6.4): a window feeds the baseline for
        # a metric only if that metric's own check judged it non-anomalous.
        if error_rate_normal:
            self._baseline.update(metrics.service, hour, "error_rate", metrics.error_rate)
        if latency_normal:
            self._baseline.update(metrics.service, hour, "p95_latency_ms", metrics.p95_latency_ms)

        return AnomalyResult(anomalies=anomalies, error_rate_normal=error_rate_normal, latency_normal=latency_normal)

    def _check_error_rate(self, metrics: WindowMetrics, hour: int, anomalies: list[Anomaly]) -> bool:
        baseline = self._baseline.get(metrics.service, hour, "error_rate")
        if baseline is None:
            return True  # not warmed up: can't flag anything, but safe to learn from
        z = self._z_score(metrics.error_rate, baseline.mean, baseline.variance)
        is_anomaly = (
            z >= self._config.error_rate_z_threshold
            and metrics.errors >= self._config.error_rate_min_errors
            and metrics.error_rate >= self._config.error_rate_min_rate
        )
        if is_anomaly:
            anomalies.append(
                Anomaly(
                    kind="error_rate",
                    ts=metrics.window_end,
                    service=metrics.service,
                    z=z,
                    metrics=metrics.model_dump(mode="json"),
                    baseline_mean=baseline.mean,
                    baseline_std=sqrt(max(baseline.variance, 0.0)),
                )
            )
        return not is_anomaly

    def _check_latency(self, metrics: WindowMetrics, hour: int, anomalies: list[Anomaly]) -> bool:
        baseline = self._baseline.get(metrics.service, hour, "p95_latency_ms")
        if baseline is None:
            return True
        z = self._z_score(metrics.p95_latency_ms, baseline.mean, baseline.variance)
        is_anomaly = z >= self._config.latency_z_threshold
        if is_anomaly:
            anomalies.append(
                Anomaly(
                    kind="latency_degradation",
                    ts=metrics.window_end,
                    service=metrics.service,
                    z=z,
                    metrics=metrics.model_dump(mode="json"),
                    baseline_mean=baseline.mean,
                    baseline_std=sqrt(max(baseline.variance, 0.0)),
                )
            )
        return not is_anomaly

    def _z_score(self, value: float, mean: float, variance: float) -> float:
        std_eff = max(sqrt(max(variance, 0.0)), self._config.min_std)
        return (value - mean) / std_eff
