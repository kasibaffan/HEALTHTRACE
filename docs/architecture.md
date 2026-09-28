# Architecture

## Runtime

A single Python process (FastAPI + asyncio) runs the whole pipeline and also
serves the built frontend, so the UI, REST API and WebSocket share one origin.

| Stage | Module | Notes |
|---|---|---|
| Read | `ingest/tailer.py` | Polls each log file, 1 MB chunks, survives rotation/truncation, resumable byte offsets |
| Parse | `parse/parser.py`, `parse/enricher.py` | Invalid lines are counted, never fatal |
| Window | `detect/window.py` | 60 s window per service, emitted every 5 s of event time |
| Baseline | `detect/baseline.py` | EWMA mean/variance per (service, hour of day), learns only from normal windows |
| Detect | `detect/anomaly.py`, `detect/access.py` | z-score on error rate and p95 latency; HIPAA access patterns per user |
| Severity | `detect/severity.py` | deviation x (criticality + patient impact); rule table for HIPAA |
| Incident | `incidents/engine.py` | Fingerprint dedup, escalation, cooldown, mute, auto-resolve, MTTR |
| Store | `store/db.py` | SQLite (WAL): metrics (24 h), alerts, incidents, baselines, tail positions |
| Push | `api/ws.py`, `notify/aws.py` | Per-client WebSocket queues; async notifier with retries |

All detection runs on event timestamps, so replaying history gives the same
result as live processing.

## Restart and replay

Tail offsets are saved together with the baselines, only when every line read
has been processed. A restart resumes from that point. A backlog (first run,
or logs written while the backend was down) is processed in *replay* mode:
detection runs normally, clients receive progress messages instead of
historical events, and alerts older than 15 minutes are not sent to AWS.

## Frontend

React + TypeScript (Vite), Tailwind CSS, Motion for transitions, React Three
Fiber for the telemetry scene, TanStack Query for REST reads and a Zustand
store fed by the WebSocket. See [frontend.md](frontend.md).

## Deployment

One ECS Fargate task behind an Application Load Balancer. See
[aws-deployment.md](aws-deployment.md).
