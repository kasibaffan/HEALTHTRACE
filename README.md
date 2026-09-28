# MedGuard — Healthcare Pipeline Sentinel

A real-time log anomaly detector with a live alert feed, built for a
healthcare technology company (Acentra Health) that runs Medicaid systems:
claims, prior authorization, eligibility, and pharmacy.

Full design: [SPEC.md](SPEC.md). Built one milestone at a time; see
"Status" below for what exists today.

Only synthetic data is ever used. Patient IDs look like `P-000123`. AWS is
optional — the app runs fully with no credentials (`AWS_MODE=off`).

## Status: Milestone 2 — Ingest + parse + window

Done (Milestone 1):

- Repo layout (`config.yaml`, `.env.example`, `Makefile`, `generator/`,
  `backend/`).
- `backend/app/models.py`: pydantic models for every shape in the pipeline
  (`AppEvent`, `AuditEvent`, `WindowMetrics`, `Anomaly`, `Alert`, `Incident`,
  `IncidentEvent`) — filled in incrementally as each milestone needs them.
- `generator/generate.py` + `generator/scenarios.py`: synthetic log
  generator covering normal traffic and all 9 scenarios from SPEC.md
  section 7.
- Tests confirming every generated line validates against the models, and
  that each scenario produces the traffic shape the spec promises.

Done (Milestone 2):

- `backend/app/config.py`: loads `config.yaml` (detection constants) and
  `.env` (AWS mode, paths) via pydantic-settings.
- `backend/app/ingest/tailer.py`: polling async tailer — handles append,
  buffered partial lines, in-place truncation, and rotation (new inode at
  the same path), all without crashing on a missing file.
- `backend/app/parse/parser.py`: JSON-line -> `AppEvent`/`AuditEvent`,
  counting malformed lines instead of raising.
- `backend/app/parse/enricher.py`: attaches service criticality and
  priority weight to app events.
- `backend/app/detect/window.py`: per-service 60s sliding window, emitting
  `WindowMetrics` every 5s of *event time* (not wall clock).
- Tests for all of the above (39 total, all passing).

Not built yet (later milestones): baseline/anomaly/severity engines, access
detector, incident engine, store, API/WebSocket, notifier, and frontend.
`make backend`, `make frontend`, and `make demo` are placeholders until
those exist.

## Setup

Requires Python 3.11+.

```bash
cd medguard
python -m venv .venv
. .venv/Scripts/activate        # Windows; use `source .venv/bin/activate` on macOS/Linux
pip install -e backend[dev]
```

## Running the generator

Run as a module (`-m generator.generate`, not `python generator/generate.py`)
from the `medguard/` root, so its `from generator.scenarios import ...` finds
the package:

```bash
# Normal traffic forever, ~30 events/sec, appending to data/logs/{app,audit}.log
python -m generator.generate --rate 30

# 24h of historical normal traffic, so every (service, hour_of_day) baseline
# bucket is warm before a demo (SPEC.md section 6.4 seeding).
python -m generator.generate --backfill-hours 24

# Inject one scenario directly (useful without the dashboard / for tests):
python -m generator.generate --scenario urgent_prior_auth_failure --duration 60
```

Scenario names (SPEC.md section 7): `urgent_prior_auth_failure`,
`eligibility_outage`, `claims_degradation`, `batch_spike`,
`latency_degradation`, `bulk_phi_access`, `off_hours_access`,
`region_mismatch`, `recovery`.

While running with no flags, the generator polls `data/control.json` once a
second for a scenario written by the dashboard's demo panel (a later
milestone's `POST /api/demo/inject`).

## Tests

```bash
make test
# or: python -m pytest backend/tests -q
```

## Makefile targets

| Target | Does |
|---|---|
| `make gen` | stream normal traffic, polling for demo injections |
| `make backfill` | write 24h of historical normal traffic |
| `make backend` | run the FastAPI app (Milestone 5+) |
| `make frontend` | run the Vite dev server (Milestone 6+) |
| `make test` | run the backend test suite |
| `make demo` | backfill + generator + backend + frontend together (Milestone 7) |

## Architecture

See SPEC.md section 3 for the full pipeline diagram: ingestor → parser/
enricher → sliding window + access detector → baseline/anomaly/severity
engines → incident engine → store / WebSocket broadcaster / AWS notifier →
frontend.
