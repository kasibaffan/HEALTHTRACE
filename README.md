# MedGuard — Healthcare Pipeline Sentinel

A real-time log anomaly detector with a live alert feed, built for a
healthcare technology company (Acentra Health) that runs Medicaid systems:
claims, prior authorization, eligibility, and pharmacy.

Full design: [SPEC.md](SPEC.md). Built one milestone at a time; see
"Status" below for what exists today.

Only synthetic data is ever used. Patient IDs look like `P-000123`. AWS is
optional — the app runs fully with no credentials (`AWS_MODE=off`).

## Design decisions

Places where SPEC.md was ambiguous, or where its literal constants needed
tuning once run against real generated traffic (task instruction: tune only
config.yaml values, never the formulas themselves — every change below is
exactly that, and is also called out at its own spot in config.yaml):

- **`baseline.alpha`: 0.1 → 0.05.** At 0.1, a *gradual* ramp (like
  `claims_degradation`'s ~4.5x rate shift, diluted over the 60s sliding
  window rather than arriving as a step) causes the EWMA baseline to adapt
  fast enough to chase the ramp before any single window's z-score crosses
  the anomaly threshold — so it's never caught, no matter how long the
  scenario runs. 0.05 makes the baseline "stickier" against exactly this
  slow-poisoning pattern, while sudden step changes (urgent_prior_auth_
  failure, eligibility_outage, batch_spike) still trip the threshold on
  their very first window regardless of alpha, since that check runs against
  the *already-warm* pre-scenario baseline. Verified with
  `test_poisoning_protection_sustained_outage_does_not_drift_baseline` (an
  abrupt outage) and the scenario-severity tests (a gradual ramp).
- **`severity.patient_factor_cap`: 40 → 400.** SPEC.md's own worked example
  (§6.6) uses a ~100-event window with 23 affected patients, but its
  generator section (§7) suggests 20-50 events/sec *across all 5 services*,
  which at the spec's fixed 60s window size means several hundred events —
  and so several dozen affected patients — accumulate per window for any
  service carrying real traffic share. At the original cap of 40, that
  volume saturates the patient-impact term to 1.0 for almost any sustained
  elevated error rate, collapsing severity down to criticality alone and
  erasing the patient-impact signal the cap exists to represent. 400 keeps
  the term meaningful at the generator's realistic scale while true mass
  incidents (urgent_prior_auth_failure, eligibility_outage) still saturate
  it.
- **Two-tier baseline key.** SPEC.md 6.4 describes a per-(service,
  hour_of_day) baseline plus a "global per-service" fallback but doesn't say
  how the fallback is keyed internally. Modeled it as one more bucket per
  service, `hour_of_day = -1`, updated on every window alongside whichever
  hourly bucket is current — simplest option that needs no separate code
  path in the store schema.
- **Poisoning protection is per-metric, not per-window.** SPEC.md 6.4 says
  "update() is called only when the Anomaly Engine marks the window as
  normal" without specifying whether that's a single verdict per window or
  one per metric (error_rate vs latency). Implemented it per-metric: a
  window anomalous on latency alone still lets the error-rate baseline learn
  from it, and vice versa. Simplest option that doesn't let an anomaly in
  one metric block learning on an unrelated one.

## Status: Milestone 3 — Baseline + anomaly + severity

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

Done (Milestone 3):

- `backend/app/store/db.py`: aiosqlite schema for all 6 tables (SPEC.md
  6.10), with the `baselines` read/write methods this milestone needs; the
  rest gain their own methods in Milestones 4-5.
- `backend/app/detect/baseline.py`: EWMA baseline per (service, hour_of_day)
  with a global per-service fallback, warm-up, and persistence
  (save/load against the store).
- `backend/app/detect/anomaly.py`: z-score checks for error rate and p95
  latency, with per-metric poisoning protection (only feeds the baseline
  from windows judged non-anomalous for that metric).
- `backend/app/detect/severity.py`: the continuous service-anomaly score and
  the rule-based HIPAA severity table (the HIPAA *detector* that produces
  its inputs is Milestone 4; this module's formula is ready now).
- Two config.yaml values tuned against real generator output — see "Design
  decisions" above.
- Tests: baseline warm-up/fallback/persistence, poisoning protection under a
  sustained outage, severity formula boundaries, the HIPAA severity table,
  and a full enrich→window→baseline→anomaly→severity run of every service
  scenario from SPEC.md §7 confirming it lands in its expected severity
  (27 new tests; 66 total, all passing).

Not built yet (later milestones): access detector, incident engine, the rest
of the store, API/WebSocket, notifier, and frontend. `make backend`, `make
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
