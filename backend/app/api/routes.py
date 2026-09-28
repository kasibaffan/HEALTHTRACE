"""REST API (SPEC.md section 6.11)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query, Request

from app.pipeline import Pipeline

router = APIRouter()


def _pipeline(request: Request) -> Pipeline:
    return request.app.state.pipeline


@router.get("/health")
async def health(request: Request) -> dict[str, Any]:
    return _pipeline(request).health_snapshot()


@router.get("/services")
async def services(request: Request) -> list[dict[str, Any]]:
    return _pipeline(request).services_snapshot()


@router.get("/metrics")
async def metrics(request: Request, service: str, minutes: int = Query(default=15, ge=1, le=1440)) -> list[dict[str, Any]]:
    pipeline = _pipeline(request)
    if service not in pipeline.config.services:
        raise HTTPException(status_code=404, detail=f"unknown service: {service}")
    rows = await pipeline.store.list_metrics(service=service, minutes=minutes)
    return [r.model_dump(mode="json") for r in rows]


@router.get("/alerts")
async def alerts(
    request: Request, limit: int = Query(default=100, ge=1, le=1000), severity: Optional[str] = None
) -> list[dict[str, Any]]:
    pipeline = _pipeline(request)
    rows = await pipeline.store.list_alerts(limit=limit, severity=severity)
    return [a.model_dump(mode="json") for a in rows]


@router.get("/incidents")
async def incidents(request: Request, state: Optional[str] = None) -> list[dict[str, Any]]:
    pipeline = _pipeline(request)
    return [i.model_dump(mode="json") for i in pipeline.incidents.list_incidents(state=state)]


@router.post("/incidents/{incident_id}/ack")
async def ack_incident(incident_id: int, request: Request) -> dict[str, Any]:
    pipeline = _pipeline(request)
    update = pipeline.incidents.acknowledge(incident_id, datetime.now(timezone.utc))
    if update is None:
        raise HTTPException(status_code=404, detail="incident not found, or not OPEN")
    await pipeline.apply_incident_update(update)
    return update.incident.model_dump(mode="json")


@router.post("/incidents/{incident_id}/resolve")
async def resolve_incident(incident_id: int, request: Request) -> dict[str, Any]:
    pipeline = _pipeline(request)
    update = pipeline.incidents.resolve(incident_id, datetime.now(timezone.utc))
    if update is None:
        raise HTTPException(status_code=404, detail="incident not found, or already RESOLVED")
    await pipeline.apply_incident_update(update)
    return update.incident.model_dump(mode="json")


@router.post("/demo/inject")
async def demo_inject(request: Request, payload: dict[str, Any]) -> dict[str, Any]:
    pipeline = _pipeline(request)
    if not pipeline.settings.demo_mode:
        raise HTTPException(status_code=403, detail="DEMO_MODE is disabled")
    scenario = payload.get("scenario")
    if not scenario:
        raise HTTPException(status_code=422, detail="'scenario' is required")
    duration_s = float(payload.get("duration_s", 60))
    pipeline.write_control_file(scenario, duration_s)
    return {"scenario": scenario, "duration_s": duration_s}
