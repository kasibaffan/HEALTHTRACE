"""Wires ingest -> parse/enrich -> detect -> incidents -> store/broadcast/
notify together (SPEC.md section 3).

All detection runs off event timestamps (SPEC.md section 1): app and audit
events advance an internal event-time clock, which is what drives the
HIPAA incident auto-resolve sweep — not the wall clock — so replay stays
deterministic.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from math import sqrt
from typing import Any, Optional

from app.api.ws import Broadcaster
from app.config import AppConfig, Settings
from app.detect.access import AccessDetector
from app.detect.anomaly import AnomalyEngine
from app.detect.baseline import BaselineEngine
from app.detect.severity import score_hipaa_anomaly, score_service_anomaly
from app.detect.window import SlidingWindow
from app.incidents.engine import IncidentEngine, IncidentUpdate
from app.ingest.tailer import Tailer
from app.models import Alert, Anomaly, AppEvent, AuditEvent, WindowMetrics
from app.notify.aws import AwsNotifier
from app.parse.enricher import Enricher
from app.parse.parser import Parser
from app.store.db import Store

logger = logging.getLogger(__name__)

BASELINE_SAVE_INTERVAL_SECONDS = 60
HEARTBEAT_INTERVAL_SECONDS = 10


@dataclass
class ServiceState:
    service: str
    window_end: Optional[datetime] = None
    total: int = 0
    errors: int = 0
    error_rate: float = 0.0
    p95_latency_ms: float = 0.0
    urgent_errors: int = 0
    baseline_mean: Optional[float] = None
    baseline_std: Optional[float] = None
    z: Optional[float] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "service": self.service,
            "window_end": self.window_end.isoformat() if self.window_end else None,
            "total": self.total,
            "errors": self.errors,
            "error_rate": self.error_rate,
            "p95_latency_ms": self.p95_latency_ms,
            "urgent_errors": self.urgent_errors,
            "baseline_mean": self.baseline_mean,
            "baseline_std": self.baseline_std,
            "z": self.z,
        }


class Pipeline:
    def __init__(self, settings: Settings, config: AppConfig) -> None:
        self.settings = settings
        self.config = config

        self.queue: "asyncio.Queue[str]" = asyncio.Queue(maxsize=10000)
        self.parser = Parser()
        self.enricher = Enricher(config)
        self.window = SlidingWindow(config.window.size_seconds, config.window.step_seconds)
        self.baseline = BaselineEngine(config.baseline)
        self.anomaly_engine = AnomalyEngine(config.anomaly, self.baseline)
        self.access_detector = AccessDetector(config.hipaa)
        self.incidents = IncidentEngine(config.incident)
        self.store = Store(settings.db_path)
        self.notifier = AwsNotifier(
            mode=settings.aws_mode,
            region=settings.aws_region,
            log_group=settings.cloudwatch_log_group,
            sns_topic_arn=settings.sns_topic_arn,
            mock_log_path=settings.log_dir.parent / "aws_mock.log",
        )
        self.broadcaster = Broadcaster()

        self.service_states: dict[str, ServiceState] = {}
        self.recent_alerts: list[Alert] = []  # newest last; capped at _MAX_RECENT_ALERTS
        self._MAX_RECENT_ALERTS = 500

        self._event_clock: Optional[datetime] = None
        self._tailers: list[Tailer] = []
        self._tasks: list[asyncio.Task] = []

    # -- lifecycle -------------------------------------------------------------

    async def start(self) -> None:
        await self.store.connect()
        await self.baseline.load(self.store)
        await self.notifier.start()

        # SPEC.md 6.4: "the backend replays this file on first run so every
        # hour bucket is ready before the demo" — first run meaning no
        # baselines were persisted from a previous session. On any later
        # restart, tail from the end as usual so history isn't reprocessed.
        first_run = self.baseline.is_empty()
        self._tailers = [
            Tailer(self.settings.log_dir / "app.log", self.queue, from_start=first_run),
            Tailer(self.settings.log_dir / "audit.log", self.queue, from_start=first_run),
        ]
        for tailer in self._tailers:
            self._tasks.append(asyncio.create_task(tailer.run()))
        self._tasks.append(asyncio.create_task(self._consume()))
        self._tasks.append(asyncio.create_task(self._periodic_baseline_save()))
        self._tasks.append(asyncio.create_task(self._heartbeat()))

    async def stop(self) -> None:
        for tailer in self._tailers:
            tailer.stop()
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._tasks = []
        await self.baseline.save(self.store)
        await self.notifier.stop()
        await self.store.close()

    async def _periodic_baseline_save(self) -> None:
        while True:
            await asyncio.sleep(BASELINE_SAVE_INTERVAL_SECONDS)
            await self.baseline.save(self.store)

    async def _heartbeat(self) -> None:
        while True:
            await asyncio.sleep(HEARTBEAT_INTERVAL_SECONDS)
            await self.broadcaster.broadcast({"type": "heartbeat", "ts": datetime.now(timezone.utc).isoformat()})

    # -- ingestion loop ----------------------------------------------------

    async def _consume(self) -> None:
        while True:
            line = await self.queue.get()
            try:
                await self._process_line(line)
            except Exception:
                logger.exception("pipeline: error processing line")
            finally:
                self.queue.task_done()

    async def _process_line(self, line: str) -> None:
        event = self.parser.parse_line(line)
        if event is None:
            return
        if isinstance(event, AppEvent):
            await self._process_app_event(event)
        else:
            await self._process_audit_event(event)

    def _advance_clock(self, ts: datetime) -> None:
        if self._event_clock is None or ts > self._event_clock:
            self._event_clock = ts

    # -- app events: window -> anomaly -> severity -> incident --------------

    async def _process_app_event(self, event: AppEvent) -> None:
        self._advance_clock(event.ts)
        enriched = self.enricher.enrich(event)
        for metrics in self.window.add(enriched):
            await self._process_window_metrics(metrics)

    async def _process_window_metrics(self, metrics: WindowMetrics) -> None:
        metrics.malformed_lines = self.parser.malformed_lines
        result = self.anomaly_engine.evaluate(metrics)
        self._update_service_state(metrics)

        await self.store.save_metrics(metrics)
        await self.broadcaster.broadcast({"type": "metric", **metrics.model_dump(mode="json")})

        criticality = self.config.services[metrics.service].criticality
        for anomaly in result.anomalies:
            alert = score_service_anomaly(anomaly, metrics, criticality, self.config.severity)
            await self._handle_alert(anomaly, alert)

        if result.error_rate_normal:
            update = self.incidents.record_normal_window("error_rate", metrics.service, metrics.window_end)
            if update:
                await self.apply_incident_update(update)
        if result.latency_normal:
            update = self.incidents.record_normal_window("latency_degradation", metrics.service, metrics.window_end)
            if update:
                await self.apply_incident_update(update)

    def _update_service_state(self, metrics: WindowMetrics) -> None:
        baseline = self.baseline.get(metrics.service, metrics.window_end.hour, "error_rate")
        z = None
        baseline_std = None
        if baseline is not None:
            baseline_std = sqrt(max(baseline.variance, 0.0))
            std_eff = max(baseline_std, self.config.anomaly.min_std)
            z = (metrics.error_rate - baseline.mean) / std_eff
        self.service_states[metrics.service] = ServiceState(
            service=metrics.service,
            window_end=metrics.window_end,
            total=metrics.total,
            errors=metrics.errors,
            error_rate=metrics.error_rate,
            p95_latency_ms=metrics.p95_latency_ms,
            urgent_errors=metrics.urgent_errors,
            baseline_mean=baseline.mean if baseline else None,
            baseline_std=baseline_std,
            z=z,
        )

    # -- audit events: access detector -> severity -> incident --------------

    async def _process_audit_event(self, event: AuditEvent) -> None:
        self._advance_clock(event.ts)
        anomalies = self.access_detector.evaluate(event)
        for anomaly in anomalies:
            alert = score_hipaa_anomaly(anomaly, self.config.hipaa)
            await self._handle_alert(anomaly, alert)

        if self._event_clock is not None:
            for update in self.incidents.sweep_hipaa_timeouts(self._event_clock):
                await self.apply_incident_update(update)

    # -- shared: alerts -> incidents -> store/broadcast/notify --------------

    async def _handle_alert(self, anomaly: Anomaly, alert: Alert) -> None:
        update = self.incidents.record_alert(anomaly, alert)
        alert.incident_id = update.incident.id

        self._remember_alert(alert)
        self.notifier.notify_alert(alert)  # CloudWatch: every alert
        await self.store.save_alert(alert)
        await self.broadcaster.broadcast({"type": "alert", **alert.model_dump(mode="json")})

        await self.apply_incident_update(update)
        if update.should_notify and (update.is_new or update.is_escalation):
            self.notifier.notify_incident(update.incident, alert.explanation)

    async def apply_incident_update(self, update: IncidentUpdate) -> None:
        await self.store.upsert_incident(update.incident)
        for event in update.events:
            await self.store.save_incident_event(event)
            await self.broadcaster.broadcast(
                {"type": "incident_update", "incident": update.incident.model_dump(mode="json"),
                 **event.model_dump(mode="json")}
            )

    def _remember_alert(self, alert: Alert) -> None:
        self.recent_alerts.append(alert)
        if len(self.recent_alerts) > self._MAX_RECENT_ALERTS:
            self.recent_alerts = self.recent_alerts[-self._MAX_RECENT_ALERTS :]

    # -- read models for the API (Milestone 5) -------------------------------

    def health_snapshot(self) -> dict[str, Any]:
        return {
            "status": "ok",
            "queue_depth": self.queue.qsize(),
            "malformed_lines": self.parser.malformed_lines,
            "aws_mode": self.settings.aws_mode,
            "notifier_queue_depth": self.notifier.queue_depth,
        }

    def services_snapshot(self) -> list[dict[str, Any]]:
        known = set(self.config.services) | set(self.service_states)
        return [
            self.service_states[s].to_dict() if s in self.service_states else ServiceState(service=s).to_dict()
            for s in sorted(known)
        ]

    def snapshot(self) -> dict[str, Any]:
        return {
            "type": "snapshot",
            "services": self.services_snapshot(),
            "alerts": [a.model_dump(mode="json") for a in self.recent_alerts[-50:]],
            "incidents": [i.model_dump(mode="json") for i in self.incidents.list_incidents()],
            "metrics": {s.service: s.to_dict() for s in self.service_states.values()},
        }

    def write_control_file(self, scenario: str, duration_s: float) -> None:
        """POST /api/demo/inject writes this file; generator.generate polls it
        once a second (SPEC.md section 7)."""
        path = self.settings.control_file
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "scenario": scenario,
            "duration_s": duration_s,
            "injected_at": datetime.now(timezone.utc).isoformat(),
        }
        path.write_text(json.dumps(payload), encoding="utf-8")
