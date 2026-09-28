# HEALTH TRACE

Real-time log anomaly monitoring for healthcare pipelines (claims, prior
authorization, eligibility, pharmacy, batch). HEALTH TRACE tails growing log
files, keeps a sliding error-rate window per service, learns a baseline for
each service and hour of day, flags deviations, scores their severity by
patient impact, and pushes alerts to a live dashboard and to AWS
(CloudWatch Logs + SNS).

The detection engine is the MedGuard backend described in [SPEC.md](SPEC.md).
Only synthetic data is used: patient IDs look like `P-000123`.

```
LOG FILES -> TAILER -> SLIDING WINDOW -> BASELINE -> ANOMALY -> SEVERITY -> INCIDENT
                                                                  |-> SQLite store
                                                                  |-> WebSocket -> dashboard
                                                                  '-> CloudWatch Logs / SNS
```

## Quick start (local)

Requirements: Python 3.11+, Node 20+.

```bash
python -m venv .venv
.venv/Scripts/activate            # macOS/Linux: source .venv/bin/activate
pip install -e "backend[dev]"
cd frontend && npm install && cd ..

python -m generator.generate --backfill-hours 2      # seed history (once)
python -m generator.generate --rate 30                # terminal 1: live logs
cd backend && uvicorn app.main:app --port 8010        # terminal 2: API
cd frontend && npm run dev                            # terminal 3: UI on :5173
```

Open http://localhost:5173. The dev server proxies `/api` and `/ws` to the
backend (override with `HEALTHTRACE_BACKEND=http://host:port`).

With Docker: `docker compose up --build`, then open http://localhost:8080.

## Tests

```bash
python -m pytest backend/tests -q      # 152 tests
cd frontend && npm run build           # typecheck + production build
```

## Demo script

1. Open the dashboard: every service is healthy.
2. Press `Ctrl K`, choose *Inject Urgent prior-auth failure*: a CRITICAL
   anomaly opens within seconds. Open it to see why it was detected.
3. Inject *Batch error spike*: a higher error rate, but it scores LOW because
   no patients are affected.
4. Inject *Bulk PHI access*: a HIPAA access anomaly for user U-117.
5. Inject *Recovery*: anomalies resolve on their own and MTTR is recorded.

## Documentation

- [Architecture](docs/architecture.md)
- [Backend](docs/backend.md) and the [changes made during stabilisation](docs/backend.md#stabilisation-log)
- [Real-time events](docs/realtime.md)
- [API](docs/api.md)
- [Frontend](docs/frontend.md)
- [AWS deployment](docs/aws-deployment.md)
- [Development](docs/development.md)

## Configuration

Detection constants live in `config.yaml`. Deployment settings are
environment variables (see `.env.example`): `AWS_MODE` (off | mock | live),
`AWS_REGION`, `CLOUDWATCH_LOG_GROUP`, `SNS_TOPIC_ARN`, `DEMO_MODE`,
`PROJECT_NAME`, `ENVIRONMENT`, `CORS_ORIGINS`, `OPERATOR_TOKEN`, `LOG_DIR`,
`DB_PATH`.
