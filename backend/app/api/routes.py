"""REST API (SPEC.md section 6.11), plus the read models the dashboard needs."""

from __future__ import annotations

import hmac
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.demo import MAX_DURATION_S, MIN_DURATION_S, SCENARIO_NAMES, SCENARIOS
from app.models import Incident
from app.pipeline import Pipeline

router = APIRouter()

_SEVERITIES = {"LOW", "MEDIUM", "HIGH", "CRITICAL"}
_STATES = {"OPEN", "ACKNOWLEDGED", "RESOLVED"}


def _pipeline(request: Request) -> Pipeline:
    return request.app.state.pipeline


def require_operator(request: Request, x_operator_token: Optional[str] = Header(default=None)) -> None:
    expected = _pipeline(request).settings.operator_token
    if expected and not (x_operator_token and hmac.compare_digest(x_operator_token, expected)):
        raise HTTPException(status_code=401, detail="operator token required")


# -- health / services -------------------------------------------------------


@router.get("/health")
async def health(request: Request) -> dict[str, Any]:
    return _pipeline(request).health_snapshot()


@router.get("/services")
async def services(request: Request) -> list[dict[str, Any]]:
    return _pipeline(request).services_snapshot()


@router.get("/services/{service}")
async def service_detail(service: str, request: Request) -> dict[str, Any]:
    pipeline = _pipeline(request)
    if service not in pipeline.config.services:
        raise HTTPException(status_code=404, detail=f"unknown service: {service}")
    state = next(s for s in pipeline.services_snapshot() if s["service"] == service)
    incidents = [i for i in await _all_incidents(pipeline) if i.service == service][:50]
    alerts = await pipeline.store.list_alerts(limit=50, service=service)
    return {
        **state,
        "baselines": {
            "error_rate": pipeline.baseline.cells_for(service, "error_rate"),
            "p95_latency_ms": pipeline.baseline.cells_for(service, "p95_latency_ms"),
        },
        "incidents": [i.model_dump(mode="json") for i in incidents],
        "alerts": [a.model_dump(mode="json") for a in alerts],
    }


@router.get("/metrics")
async def metrics(
    request: Request, service: str, minutes: int = Query(default=15, ge=1, le=1440)
) -> list[dict[str, Any]]:
    pipeline = _pipeline(request)
    if service not in pipeline.config.services:
        raise HTTPException(status_code=404, detail=f"unknown service: {service}")
    rows = await pipeline.store.list_metrics(service=service, minutes=minutes, before=_metrics_anchor(pipeline))
    return [r.model_dump(mode="json") for r in rows]


def _metrics_anchor(pipeline: Pipeline) -> Optional[datetime]:
    """Time-series windows are anchored to the pipeline's event clock when it
    runs behind the wall clock (replayed history), else to now."""
    clock = pipeline._event_clock  # noqa: SLF001
    now = datetime.now(timezone.utc)
    if clock is not None and now - clock > timedelta(minutes=5):
        return clock
    return None


# -- alerts / incidents ------------------------------------------------------


@router.get("/alerts")
async def alerts(
    request: Request,
    limit: int = Query(default=100, ge=1, le=1000),
    severity: Optional[str] = None,
    service: Optional[str] = None,
    kind: Optional[str] = None,
    incident_id: Optional[int] = None,
    user_id: Optional[str] = None,
) -> list[dict[str, Any]]:
    pipeline = _pipeline(request)
    rows = await pipeline.store.list_alerts(
        limit=limit, severity=severity, service=service, kind=kind, incident_id=incident_id, user_id=user_id
    )
    return [a.model_dump(mode="json") for a in rows]


async def _all_incidents(pipeline: Pipeline, state: Optional[str] = None, limit: int = 500) -> list[Incident]:
    """Persisted history merged with the engine's live view (the engine is
    authoritative for any incident it currently tracks)."""
    merged: dict[int, Incident] = {i.id: i for i in await pipeline.store.list_incidents(state=state, limit=limit)}
    for incident in pipeline.incidents.list_incidents(state=state):
        if incident.id is not None:
            merged[incident.id] = incident
    return sorted(merged.values(), key=lambda i: (i.opened_at, i.id or 0), reverse=True)[:limit]


@router.get("/incidents")
async def incidents(
    request: Request, state: Optional[str] = None, limit: int = Query(default=500, ge=1, le=2000)
) -> list[dict[str, Any]]:
    if state is not None and state not in _STATES:
        raise HTTPException(status_code=422, detail=f"state must be one of {sorted(_STATES)}")
    return [i.model_dump(mode="json") for i in await _all_incidents(_pipeline(request), state, limit)]


@router.get("/incidents/{incident_id}")
async def incident_detail(incident_id: int, request: Request) -> dict[str, Any]:
    pipeline = _pipeline(request)
    incident = pipeline.incidents.get(incident_id) or await pipeline.store.get_incident(incident_id)
    if incident is None:
        raise HTTPException(status_code=404, detail="incident not found")
    events = await pipeline.store.list_incident_events(incident_id)
    alerts_ = await pipeline.store.list_alerts(limit=200, incident_id=incident_id)
    return {
        "incident": incident.model_dump(mode="json"),
        "events": [e.model_dump(mode="json") for e in events],
        "alerts": [a.model_dump(mode="json") for a in alerts_],
        "detection": _detection_rule(pipeline, incident.kind),
    }


def _detection_rule(pipeline: Pipeline, kind: str) -> dict[str, Any]:
    """The rule an incident of this kind was detected by, in config terms, so
    the UI can explain *why* rather than just *that*."""
    a, s, h, w = pipeline.config.anomaly, pipeline.config.severity, pipeline.config.hipaa, pipeline.config.window
    if kind == "error_rate":
        return {"metric": "error_rate", "z_threshold": a.error_rate_z_threshold, "min_errors": a.error_rate_min_errors,
                "min_rate": a.error_rate_min_rate, "min_std": a.min_std, "window_seconds": w.size_seconds,
                "step_seconds": w.step_seconds, "severity": s.model_dump()}
    if kind == "latency_degradation":
        return {"metric": "p95_latency_ms", "z_threshold": a.latency_z_threshold, "min_std": a.latency_min_std_ms,
                "window_seconds": w.size_seconds, "step_seconds": w.step_seconds, "severity": s.model_dump()}
    return {"metric": kind, "rolling_window_minutes": 10, "hipaa": h.model_dump()}


@router.post("/incidents/{incident_id}/ack", dependencies=[Depends(require_operator)])
async def ack_incident(incident_id: int, request: Request) -> dict[str, Any]:
    pipeline = _pipeline(request)
    update = pipeline.incidents.acknowledge(incident_id, datetime.now(timezone.utc))
    if update is None:
        raise HTTPException(status_code=404, detail="incident not found, or not OPEN")
    await pipeline.apply_incident_update(update)
    return update.incident.model_dump(mode="json")


@router.post("/incidents/{incident_id}/resolve", dependencies=[Depends(require_operator)])
async def resolve_incident(incident_id: int, request: Request) -> dict[str, Any]:
    pipeline = _pipeline(request)
    update = pipeline.incidents.resolve(incident_id, datetime.now(timezone.utc))
    if update is None:
        raise HTTPException(status_code=404, detail="incident not found, or already RESOLVED")
    await pipeline.apply_incident_update(update)
    return update.incident.model_dump(mode="json")


class MuteRequest(BaseModel):
    minutes: float = Field(default=30, ge=0, le=24 * 60)


@router.post("/incidents/{incident_id}/mute", dependencies=[Depends(require_operator)])
async def mute_incident(incident_id: int, request: Request, payload: MuteRequest) -> dict[str, Any]:
    pipeline = _pipeline(request)
    update = pipeline.incidents.mute(incident_id, datetime.now(timezone.utc), payload.minutes)
    if update is None:
        raise HTTPException(status_code=404, detail="incident not found")
    await pipeline.apply_incident_update(update)
    return update.incident.model_dump(mode="json")


# -- logs ---------------------------------------------------------------------

_FIELD_TERM = re.compile(r'^(\w+):(.+)$')
_LOG_FIELDS = {"service", "level", "status", "priority", "type", "user", "user_id", "action", "request_id",
               "role", "region"}


def _match_log(record: dict[str, Any], terms: list[str]) -> bool:
    haystack = None
    for term in terms:
        m = _FIELD_TERM.match(term)
        if m and m.group(1).lower() in _LOG_FIELDS:
            key, value = m.group(1).lower(), m.group(2).lower()
            if key == "user":
                key = "user_id"
            if key == "region":
                candidates = [record.get("patient_region"), record.get("user_region")]
            else:
                candidates = [record.get(key)]
            if not any(c is not None and str(c).lower() == value for c in candidates):
                return False
            continue
        if haystack is None:
            haystack = " ".join(str(v) for v in record.values() if v is not None).lower()
        if term.lower() not in haystack:
            return False
    return True


@router.get("/logs")
async def logs(
    request: Request,
    q: str = "",
    limit: int = Query(default=200, ge=1, le=2000),
    before_seq: Optional[int] = None,
) -> dict[str, Any]:
    """Search the in-memory buffer of recent events. ``q`` is space-separated
    terms, all of which must match (the word AND is accepted and ignored):
    ``field:value`` for service/level/status/priority/type/user/action/
    request_id/role/region, anything else is a case-insensitive substring."""
    pipeline = _pipeline(request)
    terms = [t for t in q.split() if t.upper() != "AND"]
    results = []
    for record in reversed(pipeline.recent_logs):
        if before_seq is not None and record["seq"] >= before_seq:
            continue
        if _match_log(record, terms):
            results.append(record)
            if len(results) >= limit:
                break
    return {"events": results, "buffer_size": len(pipeline.recent_logs),
            "buffer_capacity": pipeline.recent_logs.maxlen}


@router.get("/logs/{seq}/context")
async def log_context(seq: int, request: Request, around: int = Query(default=10, ge=1, le=100)) -> dict[str, Any]:
    pipeline = _pipeline(request)
    records = list(pipeline.recent_logs)
    idx = next((i for i, r in enumerate(records) if r["seq"] == seq), None)
    if idx is None:
        raise HTTPException(status_code=404, detail="log event is no longer in the recent buffer")
    target = records[idx]
    related = [a.model_dump(mode="json") for a in pipeline.recent_alerts
               if target.get("service") and a.service == target.get("service")
               and abs((a.ts - datetime.fromisoformat(target["ts"])).total_seconds()) <= 120]
    return {"event": target, "before": records[max(0, idx - around):idx], "after": records[idx + 1:idx + 1 + around],
            "related_alerts": related[-5:]}


# -- HIPAA ------------------------------------------------------------------


@router.get("/hipaa/users")
async def hipaa_users(request: Request, limit: int = Query(default=50, ge=1, le=500)) -> list[dict[str, Any]]:
    return _pipeline(request).access_detector.user_summaries()[:limit]


# -- analytics ----------------------------------------------------------------


@router.get("/analytics")
async def analytics(request: Request, hours: int = Query(default=24, ge=1, le=168)) -> dict[str, Any]:
    pipeline = _pipeline(request)
    anchor = _metrics_anchor(pipeline) or datetime.now(timezone.utc)
    since = anchor - timedelta(hours=hours)

    per_hour: dict[str, dict[str, Any]] = {}
    by_service: dict[str, dict[str, int]] = {}
    for hour, severity, svc, count in await pipeline.store.alert_counts(since=since):
        bucket = per_hour.setdefault(hour, {"hour": hour, "LOW": 0, "MEDIUM": 0, "HIGH": 0, "CRITICAL": 0})
        bucket[severity] = bucket.get(severity, 0) + count
        by_service.setdefault(svc, {"LOW": 0, "MEDIUM": 0, "HIGH": 0, "CRITICAL": 0})[severity] += count

    step_factor = pipeline.config.window.size_seconds / pipeline.config.window.step_seconds
    volume: dict[str, dict[str, Any]] = {}
    for hour, svc, total, errors, p95 in await pipeline.store.metrics_hourly(since=since):
        row = volume.setdefault(hour, {"hour": hour, "events": 0, "errors": 0, "services": {}})
        events, errs = total / step_factor, errors / step_factor
        row["events"] += events
        row["errors"] += errs
        row["services"][svc] = {"events": round(events), "errors": round(errs),
                                "error_rate": errs / events if events else 0.0, "p95_latency_ms": p95}
    for row in volume.values():
        row["error_rate"] = row["errors"] / row["events"] if row["events"] else 0.0
        row["events"], row["errors"] = round(row["events"]), round(row["errors"])

    incidents_ = [i for i in await _all_incidents(pipeline, limit=2000) if i.opened_at >= since]
    mttr: dict[str, list[float]] = {}
    for i in incidents_:
        if i.mttr_seconds is not None:
            mttr.setdefault(i.service or "hipaa", []).append(i.mttr_seconds)
    recurring: dict[str, int] = {}
    for i in incidents_:
        recurring[i.fingerprint] = recurring.get(i.fingerprint, 0) + 1

    return {
        "hours": hours,
        "since": since.isoformat(),
        "alerts_per_hour": sorted(per_hour.values(), key=lambda r: r["hour"]),
        "alerts_by_service": by_service,
        "alerts_by_kind": dict(await pipeline.store.alert_kind_counts(since=since)),
        "volume_per_hour": sorted(volume.values(), key=lambda r: r["hour"]),
        "incidents": {
            "total": len(incidents_),
            "active": sum(1 for i in incidents_ if i.state != "RESOLVED"),
            "resolved": sum(1 for i in incidents_ if i.state == "RESOLVED"),
            "by_severity": {s: sum(1 for i in incidents_ if i.peak_severity == s) for s in _SEVERITIES},
        },
        "mttr_seconds": {k: {"mean": sum(v) / len(v), "count": len(v), "max": max(v)} for k, v in mttr.items()},
        "recurring": sorted(
            ({"fingerprint": fp, "count": n} for fp, n in recurring.items() if n > 1),
            key=lambda r: r["count"], reverse=True,
        )[:10],
        "detection_lag_seconds": pipeline.health_snapshot()["event_lag_seconds"],
    }


# -- config / AWS -------------------------------------------------------------


@router.get("/config")
async def config(request: Request) -> dict[str, Any]:
    """Effective detection configuration (read-only: edit config.yaml and
    restart to change it) and non-secret deployment settings."""
    pipeline = _pipeline(request)
    s = pipeline.settings
    return {
        "detection": pipeline.config.model_dump(),
        "deployment": {
            "project_name": s.project_name,
            "environment": s.environment,
            "demo_mode": s.demo_mode,
            "aws_mode": s.aws_mode,
            "log_sources": [
                {"name": t.path.name, "path": str(t.path), "size_bytes": t.file_size, "offset": t.committed_offset}
                for t in pipeline._tailers  # noqa: SLF001
            ],
            "operator_token_required": bool(s.operator_token),
        },
    }


@router.get("/aws/status")
async def aws_status(request: Request) -> dict[str, Any]:
    pipeline = _pipeline(request)
    n = pipeline.notifier
    return {
        "mode": n.mode,
        "region": n.region,
        "cloudwatch": {"log_group": n.log_group, **n.status["cloudwatch"].to_dict()},
        "sns": {"topic_arn": n.sns_topic_arn or None, "configured": n.sns_configured, **n.status["sns"].to_dict()},
        "queue_depth": n.queue_depth,
        "credentials_source": n.credentials_source(),
    }


@router.post("/aws/test-connection", dependencies=[Depends(require_operator)])
async def aws_test_connection(request: Request) -> dict[str, Any]:
    return await _pipeline(request).notifier.test_connection()


@router.post("/aws/test-alert", dependencies=[Depends(require_operator)])
async def aws_test_alert(request: Request) -> dict[str, Any]:
    return await _pipeline(request).notifier.send_test_alert()


# -- demo ---------------------------------------------------------------------


class InjectRequest(BaseModel):
    scenario: str
    duration_s: float = Field(default=60, ge=MIN_DURATION_S, le=MAX_DURATION_S)


@router.get("/demo/scenarios")
async def demo_scenarios(request: Request) -> dict[str, Any]:
    return {"enabled": _pipeline(request).settings.demo_mode, "scenarios": SCENARIOS}


@router.post("/demo/inject", dependencies=[Depends(require_operator)])
async def demo_inject(request: Request, payload: InjectRequest) -> dict[str, Any]:
    pipeline = _pipeline(request)
    if not pipeline.settings.demo_mode:
        raise HTTPException(status_code=403, detail="DEMO_MODE is disabled")
    if payload.scenario not in SCENARIO_NAMES:
        raise HTTPException(status_code=422, detail=f"unknown scenario: {payload.scenario}")
    pipeline.write_control_file(payload.scenario, payload.duration_s)
    return {"scenario": payload.scenario, "duration_s": payload.duration_s}
