# MedGuard — Healthcare Pipeline Sentinel

A real-time log anomaly detector with a live alert feed, built for a
healthcare technology company (Acentra Health) that runs Medicaid systems:
claims, prior authorization, eligibility, and pharmacy.

Full design: [SPEC.md](SPEC.md). Built one milestone at a time; see
"Status" below for what exists today.

Only synthetic data is ever used. Patient IDs look like `P-000123`. AWS is
optional — the app runs fully with no credentials (`AWS_MODE=off`).

## Status: Milestone 1 — Skeleton + generator

Done:

- Repo layout (`config.yaml`, `.env.example`, `Makefile`, `generator/`,
  `backend/`).
- `backend/app/models.py`: `AppEvent` and `AuditEvent` pydantic models for
  the two log formats (SPEC.md section 5). `WindowMetrics`, `Alert`, and
  `Incident` are added in later milestones as the pipeline stages that
  produce them are built.
- `generator/generate.py` + `generator/scenarios.py`: synthetic log
  generator covering normal traffic and all 9 scenarios from SPEC.md
  section 7.
- Tests (`backend/tests/test_generator.py`) confirming every generated line
  validates against the models, and that each scenario produces the traffic
  shape the spec promises (error rate, urgent mix, patient counts, off-hours
  timestamps, region mismatches, etc.).

Not built yet (later milestones): the ingestor, parser/enricher, sliding
window, baseline/anomaly/severity engines, access detector, incident engine,
store, API/WebSocket, notifier, and frontend. `make backend`, `make
frontend`, and `make demo` are placeholders until those exist.

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
