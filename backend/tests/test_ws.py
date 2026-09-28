"""Milestone 5: WebSocket snapshot-on-connect and live streaming (SPEC.md 6.11)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings, load_config
from app.main import create_app

T0 = datetime(2026, 9, 28, 12, 0, 0, tzinfo=timezone.utc)


def _make_settings(tmp_path: Path) -> Settings:
    return Settings(
        aws_mode="off",
        demo_mode=True,
        log_dir=tmp_path / "logs",
        db_path=tmp_path / "medguard.db",
        control_file=tmp_path / "control.json",
    )


def _init_log_dir(settings: Settings) -> None:
    settings.log_dir.mkdir(parents=True)
    (settings.log_dir / "app.log").write_text("", encoding="utf-8")
    (settings.log_dir / "audit.log").write_text("", encoding="utf-8")


def _app_line(ts: datetime, *, service: str = "claims") -> str:
    return json.dumps(
        {
            "ts": ts.strftime("%Y-%m-%dT%H:%M:%S.000Z"), "type": "app", "service": service, "level": "INFO",
            "priority": "routine", "request_id": "X-1", "patient_id": "P-000001", "status": 200,
            "latency_ms": 100, "msg": "x",
        }
    )


def test_snapshot_arrives_on_connect(tmp_path: Path):
    settings = _make_settings(tmp_path)
    _init_log_dir(settings)
    app = create_app(settings=settings, config=load_config())

    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws:
            data = ws.receive_json()
            assert data["type"] == "snapshot"
            assert "services" in data and "alerts" in data and "incidents" in data and "metrics" in data
            assert len(data["services"]) == 5
            assert data["alerts"] == []
            assert data["incidents"] == []


def test_metric_message_streams_after_connect(tmp_path: Path):
    settings = _make_settings(tmp_path)
    _init_log_dir(settings)
    app = create_app(settings=settings, config=load_config())

    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws:
            ws.receive_json()  # snapshot

            with (settings.log_dir / "app.log").open("a", encoding="utf-8") as f:
                f.write(_app_line(T0) + "\n")
                f.write(_app_line(T0 + timedelta(seconds=6)) + "\n")  # crosses the 5s step boundary

            message = ws.receive_json()
            assert message["type"] == "metric"
            assert message["service"] == "claims"
            assert message["total"] == 1  # only the T0 event falls inside the first 5s window


def test_snapshot_reflects_existing_incidents(tmp_path: Path):
    settings = _make_settings(tmp_path)
    _init_log_dir(settings)
    app = create_app(settings=settings, config=load_config())
    pipeline = app.state.pipeline

    from app.models import Alert, Anomaly

    anomaly = Anomaly(kind="error_rate", ts=T0, service="claims", z=5.0)
    alert = Alert(ts=T0, kind="error_rate", service="claims", severity="HIGH", score=0.6, explanation="x")
    update = pipeline.incidents.record_alert(anomaly, alert)
    pipeline.recent_alerts.append(alert)

    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws:
            data = ws.receive_json()
            assert len(data["incidents"]) == 1
            assert data["incidents"][0]["id"] == update.incident.id
            assert len(data["alerts"]) == 1
