# MedGuard — Healthcare Pipeline Sentinel
## Build spec for AI coding agents (Claude Code / Codex)

**How to use this file:** Put it in the empty repo root as SPEC.md. Then tell the agent: "Read SPEC.md fully. Build Milestone 1 only, run its tests, and stop so I can review." Repeat for each milestone. Building one milestone at a time works much better than asking for everything at once.

## 1. Role and goal (the prompt)

You are a senior Python + React engineer. Build MedGuard, a real-time log anomaly detector with a live alert feed. It is designed for a healthcare technology company (Acentra Health) that runs Medicaid systems: claims, prior authorization, eligibility, and pharmacy.

The problem statement requires the system to:

- Monitor a continuously growing log file.
- Calculate rolling error rates using a sliding window.
- Establish a baseline for normal behaviour.
- Detect deviations from the baseline.
- Assign severity levels to detected anomalies.
- Provide a real-time frontend using WebSockets.
- Display alerts as they are generated.
- Push alerts to AWS CloudWatch Logs and SNS.

What makes MedGuard different, and so must be implemented, not skipped:

- **Patient-impact severity.** Severity combines three factors: how far a metric is from its baseline, how critical the service is, and how many patients are affected (urgent requests weigh more). As a result, a small spike in urgent prior-auth failures outranks a large spike in routine batch jobs.
- **HIPAA access-anomaly detection.** A second detector watches access-audit logs for three patterns: bulk record access, off-hours access, and access to patients outside the user's region.
- **Time-aware baselines with poisoning protection.** Baselines are kept per service and per hour of day. The baseline learns only from windows that were not anomalous.
- **Incident lifecycle.** Alerts are de-duplicated into incidents. Each incident moves through the states OPEN → ACKNOWLEDGED → RESOLVED. Incidents auto-recover and track time to resolve (MTTR).

Hard rules for the agent:

- Use only synthetic data. Never use real patient information. Patient IDs look like P-000123.
- AWS must be optional. Support the modes off, mock, and live. The app must run fully with no AWS credentials.
- All detection logic runs on event timestamps, not the wall clock. This keeps tests deterministic and makes replay possible.
- Python 3.11+, type hints everywhere, pytest for tests.
- Keep modules small and single-purpose, following the repo layout below.
- After each milestone: run the tests, fix any failures, update the README, then stop.

## 2. Tech stack

| Layer | Choice |
|---|---|
| Backend | Python 3.11, FastAPI, Uvicorn, asyncio |
| Realtime | FastAPI WebSockets |
| Storage | SQLite via aiosqlite (single file data/medguard.db) |
| Config | config.yaml + .env (pydantic-settings) |
| AWS | boto3 (CloudWatch Logs + SNS) |
| Frontend | React + Vite + TypeScript, Recharts, Tailwind CSS |
| Tests | pytest, pytest-asyncio |
| Packaging | Docker + docker-compose (Milestone 7) |

## 3. Architecture

```
 LOG GENERATOR / REAL LOGS   (data/logs/app.log  +  data/logs/audit.log, JSON lines)
            |
            v
      LOG INGESTOR   async tail -f, rotation/truncation safe, partial-line buffering
            |  asyncio.Queue (bounded -> backpressure)
            v
      PARSER + ENRICHER   validate JSON -> typed events; add service criticality,
            |             priority weight; count malformed lines as a metric
      +-----+-----------------------------------+
      v                                          v
 SLIDING WINDOW (per service)             ACCESS-PATTERN DETECTOR (HIPAA)
 60s window, 5s step                      per-user rolling 10 min: bulk / off-hours /
      |                                   region mismatch / export
      +------> BASELINE ENGINE                   |
      |        EWMA mean+var per                 |
      |        (service, hour_of_day)             |
      |          ^          |                     |
      | update   | only if  | baseline            |
      | normal   |          v                     |
      +------> ANOMALY ENGINE                     |
               z-score vs baseline                |
                     |                             |
                     v                             |
               SEVERITY ENGINE <-------------------+
               deviation x (criticality + patient impact)
                     |
                     v
               INCIDENT ENGINE   fingerprint dedup, cooldown,
                     |           OPEN -> ACKNOWLEDGED -> RESOLVED, auto-resolve, MTTR
      +--------------+-------------------+
      v              v                   v
   STORE        WS BROADCASTER      NOTIFIER QUEUE (async, retry, never blocks)
  (SQLite)     snapshot + live       +- CloudWatch Logs: every alert
      |              |               +- SNS: HIGH and CRITICAL only
      +---- REST --->|
                     v
   FRONTEND: service health . live error-rate chart with baseline band .
             alert feed . incidents (ack/resolve) . timeline . HIPAA panel .
             recovery/MTTR . demo control panel
```

## 4. Repo layout

```
medguard/
├── SPEC.md
├── README.md
├── config.yaml
├── .env.example
├── Makefile                  # make gen, make backend, make frontend, make test, make demo
├── docker-compose.yml
├── data/                     # gitignored: logs/, medguard.db, control.json
├── generator/
│   ├── generate.py           # CLI: writes app.log + audit.log continuously
│   └── scenarios.py          # incident injection definitions
├── backend/
│   ├── pyproject.toml
│   ├── app/
│   │   ├── main.py           # FastAPI app, startup/shutdown of pipeline tasks
│   │   ├── config.py
│   │   ├── models.py         # pydantic: AppEvent, AuditEvent, WindowMetrics, Alert, Incident
│   │   ├── pipeline.py       # wires stages together with queues
│   │   ├── ingest/tailer.py
│   │   ├── parse/parser.py
│   │   ├── parse/enricher.py
│   │   ├── detect/window.py
│   │   ├── detect/baseline.py
│   │   ├── detect/anomaly.py
│   │   ├── detect/access.py
│   │   ├── detect/severity.py
│   │   ├── incidents/engine.py
│   │   ├── notify/aws.py     # CloudWatch + SNS, modes off|mock|live
│   │   ├── store/db.py
│   │   ├── api/routes.py
│   │   └── api/ws.py
│   └── tests/
└── frontend/
    └── src/ (components/, hooks/useLiveFeed.ts, api.ts, types.ts)
```

## 5. Log formats (JSON lines)

App log (data/logs/app.log):

```json
{"ts":"2026-09-28T13:00:01.123Z","type":"app","service":"prior_auth","level":"ERROR",
 "priority":"urgent","request_id":"PA-88213","patient_id":"P-000123",
 "status":500,"latency_ms":820,"msg":"Clinical rules engine timeout"}
```

- service is one of: claims, prior_auth, eligibility, pharmacy, batch
- level is one of: INFO, WARN, ERROR
- priority is one of: urgent, routine
- An event counts as an error when level == "ERROR" or status >= 500.

Audit log (data/logs/audit.log):

```json
{"ts":"2026-09-28T13:00:02.004Z","type":"audit","user_id":"U-104","role":"care_manager",
 "action":"VIEW_RECORD","patient_id":"P-000877","patient_region":"TN-North","user_region":"TN-North"}
```

- action is one of: VIEW_RECORD, EDIT_RECORD, EXPORT_RECORDS, SEARCH

## 6. Component specs

### 6.1 Ingestor (tailer.py)

- Asynchronously tail both files, starting from the end. Use --from-start for replay.
- Detect rotation: if the inode changes, reopen the file.
- Detect truncation: if the file size is smaller than the current offset, seek to 0.
- Buffer a partial last line until a newline arrives.
- Push raw lines into a bounded asyncio.Queue(maxsize=10000).

### 6.2 Parser + Enricher

- Parse into pydantic models.
- Count invalid lines as malformed_lines and expose that count; never crash on a bad line.
- Enrich each event with:
  - criticality, taken from config
  - priority_weight: urgent = 2, routine = 1

Default criticality (config.yaml):

```yaml
services:
  prior_auth:  {criticality: 1.0}
  eligibility: {criticality: 0.9}
  pharmacy:    {criticality: 0.8}
  claims:      {criticality: 0.6}
  batch:       {criticality: 0.3}
```

### 6.3 Sliding window (window.py)

- Keep one window per service: a deque of events covering the last 60 seconds of event time. Emit metrics every 5 seconds of event time.
- WindowMetrics contains:
  - service, window_end, total, errors, error_rate
  - p95_latency_ms
  - urgent_errors
  - affected_patients_urgent, affected_patients_routine: the number of unique patients with errors in the window

### 6.4 Baseline engine (baseline.py)

- Track an EWMA mean and variance of error_rate (and p95_latency_ms) for each key (service, hour_of_day), with alpha = 0.1.
- Warm-up: a key is not "ready" until it has seen 12 windows. Before that, fall back to a global per-service baseline; if that isn't ready either, emit no anomalies.
- Poisoning protection: update() is called only when the Anomaly Engine marks the window as normal.
- Persist baseline state to SQLite every 60 seconds and on shutdown, and reload it on startup.
- Seeding: generator/generate.py --backfill-hours 24 writes 24 hours of normal historical logs with past timestamps. The backend replays this file on first run so every hour bucket is ready before the demo.

### 6.5 Anomaly engine (anomaly.py)

- Compute std_eff = max(sqrt(var), min_std), with min_std = 0.01.
- Compute z = (current - mean) / std_eff.
- The window is an anomaly when all of these hold:
  - z >= 3.0
  - errors >= 5 (a minimum count to avoid noise)
  - error_rate >= 0.05
- Run the same check on p95 latency with z >= 4; this produces a latency_degradation anomaly.
- Output: Anomaly(kind, service, z, metrics, baseline_mean, baseline_std).

### 6.6 Severity engine (severity.py)

```
deviation      = min(z / 6, 1.0)
patient_factor = min((2 * affected_patients_urgent + affected_patients_routine) / 40, 1.0)
score          = deviation * (0.5 * criticality + 0.5 * patient_factor)

LOW < 0.30 <= MEDIUM < 0.50 <= HIGH < 0.75 <= CRITICAL
```

- All weights and thresholds come from config.yaml.
- Every alert must store a human-readable explanation, for example: "prior_auth error rate 38% vs baseline 2% (z=9.1); 23 urgent patients affected".
- HIPAA alerts use rule-based severity instead:

| Pattern | Severity |
|---|---|
| Bulk access, more than 3x the user's baseline | HIGH |
| Bulk access, more than 6x the user's baseline | CRITICAL |
| EXPORT_RECORDS with more than 100 records | CRITICAL |
| Off-hours access (outside 07:00-21:00) | MEDIUM |
| Off-hours access with more than 20 records | HIGH |
| Region mismatch, 1-5 patients | MEDIUM |
| Region mismatch, more than 5 patients | HIGH |

### 6.7 Access-pattern detector (access.py)

- For each user, track a rolling 10-minute count of distinct patients accessed, the user's own EWMA baseline, off-hours events, and region-mismatch events.
- The bulk threshold is max(3 * user_baseline, 50).
- Emit an Anomaly(kind="hipaa_bulk_access" | "hipaa_off_hours" | "hipaa_region_mismatch" | "hipaa_bulk_export", user_id=..., ...).

### 6.8 Incident engine (incidents/engine.py)

- Fingerprint: (kind, service) for service anomalies, (kind, user_id) for HIPAA anomalies.
- If an incident with the same fingerprint is OPEN or ACKNOWLEDGED:
  - attach the alert to it
  - update peak_severity and alert_count
  - do not notify again, unless severity escalates
- Cooldown: after an incident is RESOLVED, suppress new notifications for the same fingerprint for 5 minutes. Still record the alerts.
- Auto-resolve: a service incident resolves after 6 consecutive normal windows (30 seconds). A HIPAA incident resolves after 10 minutes with no new matching events.
- Record timestamps: opened_at, acknowledged_at, resolved_at, and mttr_seconds.
- Every state change is written to the incident_events table and broadcast over WebSocket.

### 6.9 Notifier (notify/aws.py)

- Uses its own async queue and worker. Retries with exponential backoff (up to 5 attempts). Must never block detection.
- AWS_MODE is one of:
  - off: do nothing
  - mock: append JSON to data/aws_mock.log and print to the console
  - live: use boto3
- CloudWatch Logs: log group /medguard/alerts, one log stream per day (YYYY-MM-DD). Create the group and stream if missing. Send every alert.
- SNS: use SNS_TOPIC_ARN from .env. Send HIGH and CRITICAL incidents only, on creation or escalation. The subject is `[MedGuard CRITICAL] prior_auth: urgent failures`; the body contains the explanation and the incident ID.

### 6.10 Store (store/db.py)

Tables:

- metrics: window metrics; keep 24 hours
- alerts
- incidents
- incident_events
- baselines
- access_stats

Add indexes on timestamp and service.

### 6.11 API

| Method | Path | Purpose |
|---|---|---|
| GET | /api/health | pipeline status, queue depth, malformed lines, AWS mode |
| GET | /api/services | current state of each service plus its baseline |
| GET | /api/metrics?service=&minutes=15 | time series for charts |
| GET | /api/alerts?limit=100&severity= | recent alerts |
| GET | /api/incidents?state= | incidents |
| POST | /api/incidents/{id}/ack | acknowledge |
| POST | /api/incidents/{id}/resolve | resolve manually |
| POST | /api/demo/inject | {scenario, duration_s}; writes data/control.json (only when DEMO_MODE=true) |

WebSocket /ws:

- On connect, send `{"type":"snapshot","services":[...],"alerts":[...],"incidents":[...],"metrics":{...}}`.
- Then stream these message types:
  - `{"type":"metric", ...}`
  - `{"type":"alert", ...}`
  - `{"type":"incident_update", ...}`
  - `{"type":"heartbeat","ts":...}` every 10 seconds

### 6.12 Frontend

- Top bar: connection status (live or reconnecting), AWS mode badge, count of open incidents by severity.
- Service health cards: one per service, showing status colour, current error rate, baseline, and z-score.
- Live chart: error rate over the last 15 minutes against a baseline band (mean ± 3σ), with a service selector.
- Alert feed: newest first; severity colours; filters by severity and service; the explanation text; a short animation when a new alert arrives.
- Incidents table: state, peak severity, alert count, and duration, with Ack and Resolve buttons.
- Timeline: a horizontal timeline of incident open and resolve events.
- HIPAA panel: access anomalies by user. Mask patient IDs as P-****23.
- Recovery panel: MTTR per service, and a list of recently resolved incidents.
- Demo panel (only if DEMO_MODE): one button per scenario.
- Reconnect with backoff. Fetch the snapshot again on every reconnect.

## 7. Generator (generator/generate.py)

- Steady normal traffic: about 20-50 events per second across all services, with realistic error rates of 0.5-3%. Include audit events from about 30 users.
- CLI options:
  - --rate
  - --backfill-hours N
  - --scenario NAME --duration S
- The generator polls data/control.json every second for scenarios injected from the dashboard.

| Scenario | Effect | Expected result |
|---|---|---|
| urgent_prior_auth_failure | prior_auth errors reach 35%, mostly urgent, 20+ patients | CRITICAL |
| eligibility_outage | eligibility returns 503 at an 80% rate | CRITICAL |
| claims_degradation | claims error rate 8-10%, routine | LOW or MEDIUM |
| batch_spike | batch error rate 60%, no patients | LOW (this proves impact weighting) |
| latency_degradation | pharmacy p95 latency x5, few errors | MEDIUM |
| bulk_phi_access | U-117 views 300 patients in 5 minutes | HIGH or CRITICAL (HIPAA) |
| off_hours_access | U-042 accesses records at a simulated 03:00 | MEDIUM or HIGH |
| region_mismatch | U-088 views 12 patients from another region | HIGH |
| recovery | return to normal | incidents auto-resolve and MTTR is shown |

## 8. Milestones (build in order; stop after each)

1. **Skeleton + generator.** Create the repo layout, config, and generator with backfill and all scenarios. Test that the generated lines validate against the models.
2. **Ingest + parse + window.** Build the tailer (with rotation and truncation handling), parser, enricher, and window. Test rotation, truncation, partial lines, malformed lines, and window metrics.
3. **Baseline + anomaly + severity.** Test baseline warm-up and poisoning protection: during a sustained outage, the baseline mean must not drift toward the outage rate. Test that each scenario produces its expected severity from the table in §7.
4. **Access detector + incident engine + store.** Test dedup, escalation, cooldown, auto-resolve, and MTTR.
5. **API + WebSocket + notifier.** Test the snapshot on connect, AWS_MODE=mock output, and that a slow notifier does not block the pipeline (simulate with a sleep).
6. **Frontend.** Build all panels and the demo panel, and verify reconnect behaviour.
7. **Polish.** Add Docker, docker-compose, make demo (runs backfill, generator, backend, and frontend), and a README with setup, architecture, AWS setup (IAM policy for logs:* on the log group and sns:Publish on the topic), and the demo script.

End-to-end acceptance test (tests/test_e2e_scenarios.py): feed the backfill plus each scenario through the whole pipeline using an accelerated event-time clock, then assert the incident kind and severity for each scenario, and that the recovery scenario resolves every incident.

## 9. Demo script (for README)

1. Run make demo. The dashboard shows all services green.
2. Inject urgent_prior_auth_failure. A CRITICAL alert appears in a few seconds, and an SNS email arrives when AWS_MODE=live.
3. Inject batch_spike. Point out that it gets LOW even though its error rate is higher: impact-based severity at work.
4. Inject bulk_phi_access. A HIPAA alert appears with the user ID and masked patient IDs.
5. Inject recovery. Incidents auto-resolve and MTTR appears in the Recovery panel.

## 10. Out of scope for v1 (roadmap slide)

- Authentication and role-based views (ops vs compliance)
- Kafka or Fluent Bit ingestion
- Multiple detector workers
- TimescaleDB
- Encryption at rest
- A full HIPAA compliance programme
- ML-based detectors (for example, Isolation Forest on access patterns)
