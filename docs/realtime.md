# Real-time events

Endpoint: `GET /ws` (WebSocket, push-only). Every message is JSON with a `type`.

| type | When | Payload |
|---|---|---|
| `snapshot` | On connect, and again when a replay finishes | `services`, `alerts`, `incidents`, `metrics`, `health`, `logs` |
| `metric` | Every 5 s per service | Window metrics plus current baseline and z |
| `alert` | Each detection | `Alert` (severity, score, explanation, metrics, incident_id) |
| `incident_update` | Each lifecycle change | `incident` plus the event (`opened`, `escalated`, `acknowledged`, `resolved`, `auto_resolved`, `muted`, ...) |
| `logs` | Once a second | Up to 60 newest parsed events (`dropped` counts the rest) |
| `replay` | Once a second during replay | `progress` (0..1), `event_clock` |
| `heartbeat` | Every 10 s | `ts` |

Server side, each client has a bounded queue (2000 messages). A client that
falls further behind is closed with code 4008 and reconnects to a fresh
snapshot, so it never shows a state with gaps.

Client side (`frontend/src/lib/live.ts`): exponential backoff from 0.5 s to
10 s with jitter, a 25 s watchdog that reconnects if nothing arrives, and a
re-fetch of metric history after every snapshot.
