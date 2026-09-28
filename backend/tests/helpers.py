"""Shared test helper: run app events through parse/enrich/window/baseline/
anomaly/severity synchronously, without the async runtime pipeline (that's
Milestone 5's app/pipeline.py). Used by Milestone 3's scenario-severity test
and Milestone 7's end-to-end acceptance test. Not a test module itself
(pytest only collects test_*.py).
"""

from __future__ import annotations

from app.config import AppConfig
from app.detect.anomaly import AnomalyEngine
from app.detect.baseline import BaselineEngine
from app.detect.severity import score_service_anomaly
from app.detect.window import SlidingWindow
from app.models import Alert, AppEvent
from app.parse.enricher import Enricher


def run_service_pipeline(app_events: list[dict], config: AppConfig) -> list[Alert]:
    """Feed raw app-log dicts through enrich -> window -> anomaly -> severity,
    in order, returning every Alert produced along the way."""
    enricher = Enricher(config)
    window = SlidingWindow(config.window.size_seconds, config.window.step_seconds)
    baseline = BaselineEngine(config.baseline)
    anomaly_engine = AnomalyEngine(config.anomaly, baseline)

    alerts: list[Alert] = []
    for raw in app_events:
        event = AppEvent.model_validate(raw)
        enriched = enricher.enrich(event)
        for metrics in window.add(enriched):
            result = anomaly_engine.evaluate(metrics)
            criticality = config.services[metrics.service].criticality
            for anomaly in result.anomalies:
                alerts.append(score_service_anomaly(anomaly, metrics, criticality, config.severity))
    return alerts
