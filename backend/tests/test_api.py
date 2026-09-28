"""Milestone 5: REST API (SPEC.md section 6.11)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings, load_config
from app.main import create_app
from app.models import Alert, Anomaly

T0 = datetime(2026, 9, 28, 12, 0, 0, tzinfo=timezone.utc)


def _make_settings(tmp_path: Path, *, demo_mode: bool = True) -> Settings:
    return Settings(
        aws_mode="off",
        demo_mode=demo_mode,
        log_dir=tmp_path / "logs",
        db_path=tmp_path / "medguard.db",
        control_file=tmp_path / "control.json",
    )


def _init_log_dir(settings: Settings) -> None:
    settings.log_dir.mkdir(parents=True)
    (settings.log_dir / "app.log").write_text("", encoding="utf-8")
    (settings.log_dir / "audit.log").write_text("", encoding="utf-8")


def _build_app(tmp_path: Path, **settings_kwargs):
    settings = _make_settings(tmp_path, **settings_kwargs)
    _init_log_dir(settings)
    app = create_app(settings=settings, config=load_config())
    return app, app.state.pipeline


def test_health(tmp_path: Path):
    app, _ = _build_app(tmp_path)
    with TestClient(app) as client:
        response = client.get("/api/health")
        assert response.status_code == 200
        body = response.json()
        assert body["aws_mode"] == "off"
        assert body["malformed_lines"] == 0


def test_services_lists_all_five_configured_services(tmp_path: Path):
    app, _ = _build_app(tmp_path)
    with TestClient(app) as client:
        response = client.get("/api/services")
        assert response.status_code == 200
        services = {s["service"] for s in response.json()}
        assert services == {"claims", "prior_auth", "eligibility", "pharmacy", "batch"}


def test_metrics_rejects_unknown_service(tmp_path: Path):
    app, _ = _build_app(tmp_path)
    with TestClient(app) as client:
        response = client.get("/api/metrics", params={"service": "not-a-service"})
        assert response.status_code == 404


def test_metrics_returns_empty_list_for_known_service_with_no_data(tmp_path: Path):
    app, _ = _build_app(tmp_path)
    with TestClient(app) as client:
        response = client.get("/api/metrics", params={"service": "claims", "minutes": 15})
        assert response.status_code == 200
        assert response.json() == []


def test_incidents_reflects_a_directly_recorded_alert(tmp_path: Path):
    # IncidentEngine.record_alert is synchronous (only store writes and the
    # WS broadcast are async), so it can be seeded directly without touching
    # the pipeline's own event loop.
    app, pipeline = _build_app(tmp_path)
    anomaly = Anomaly(kind="error_rate", ts=T0, service="claims", z=5.0)
    alert = Alert(ts=T0, kind="error_rate", service="claims", severity="HIGH", score=0.6, explanation="boom")
    update = pipeline.incidents.record_alert(anomaly, alert)

    with TestClient(app) as client:
        response = client.get("/api/incidents")
        assert response.status_code == 200
        body = response.json()
        assert len(body) == 1
        assert body[0]["id"] == update.incident.id
        assert body[0]["peak_severity"] == "HIGH"


def test_ack_and_resolve_lifecycle(tmp_path: Path):
    app, pipeline = _build_app(tmp_path)
    anomaly = Anomaly(kind="error_rate", ts=T0, service="claims", z=5.0)
    alert = Alert(ts=T0, kind="error_rate", service="claims", severity="MEDIUM", score=0.4, explanation="x")
    update = pipeline.incidents.record_alert(anomaly, alert)
    incident_id = update.incident.id

    with TestClient(app) as client:
        ack_response = client.post(f"/api/incidents/{incident_id}/ack")
        assert ack_response.status_code == 200
        assert ack_response.json()["state"] == "ACKNOWLEDGED"

        resolve_response = client.post(f"/api/incidents/{incident_id}/resolve")
        assert resolve_response.status_code == 200
        body = resolve_response.json()
        assert body["state"] == "RESOLVED"
        assert body["mttr_seconds"] is not None

        again_response = client.post(f"/api/incidents/{incident_id}/resolve")
        assert again_response.status_code == 404


def test_ack_unknown_incident_is_404(tmp_path: Path):
    app, _ = _build_app(tmp_path)
    with TestClient(app) as client:
        response = client.post("/api/incidents/999/ack")
        assert response.status_code == 404


def test_incidents_filter_by_state(tmp_path: Path):
    app, pipeline = _build_app(tmp_path)
    a1 = Anomaly(kind="error_rate", ts=T0, service="claims", z=5.0)
    a2 = Anomaly(kind="error_rate", ts=T0, service="pharmacy", z=5.0)
    alert1 = Alert(ts=T0, kind="error_rate", service="claims", severity="LOW", score=0.1, explanation="x")
    alert2 = Alert(ts=T0, kind="error_rate", service="pharmacy", severity="LOW", score=0.1, explanation="y")
    id1 = pipeline.incidents.record_alert(a1, alert1).incident.id
    pipeline.incidents.record_alert(a2, alert2)
    pipeline.incidents.resolve(id1, T0)

    with TestClient(app) as client:
        open_response = client.get("/api/incidents", params={"state": "OPEN"})
        resolved_response = client.get("/api/incidents", params={"state": "RESOLVED"})
        assert len(open_response.json()) == 1
        assert len(resolved_response.json()) == 1


def test_demo_inject_writes_control_file(tmp_path: Path):
    app, pipeline = _build_app(tmp_path)
    with TestClient(app) as client:
        response = client.post("/api/demo/inject", json={"scenario": "batch_spike", "duration_s": 30})
        assert response.status_code == 200
        assert response.json() == {"scenario": "batch_spike", "duration_s": 30.0}

    control = json.loads(pipeline.settings.control_file.read_text(encoding="utf-8"))
    assert control["scenario"] == "batch_spike"
    assert control["duration_s"] == 30.0


def test_demo_inject_disabled_when_demo_mode_is_off(tmp_path: Path):
    app, _ = _build_app(tmp_path, demo_mode=False)
    with TestClient(app) as client:
        response = client.post("/api/demo/inject", json={"scenario": "recovery", "duration_s": 5})
        assert response.status_code == 403


def test_demo_inject_requires_scenario(tmp_path: Path):
    app, _ = _build_app(tmp_path)
    with TestClient(app) as client:
        response = client.post("/api/demo/inject", json={"duration_s": 5})
        assert response.status_code == 422
