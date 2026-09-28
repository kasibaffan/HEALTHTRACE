# Development

## Layout

```
backend/     FastAPI app and tests
generator/   Synthetic log generator and demo scenarios
frontend/    React UI
deploy/aws/  CloudFormation template and deploy script
config.yaml  Detection constants
```

## Common tasks

| Task | Command |
|---|---|
| Backend tests | `python -m pytest backend/tests -q` |
| Backend server | `cd backend && uvicorn app.main:app --port 8010 --reload` |
| Generator | `python -m generator.generate --rate 30` |
| One scenario | `python -m generator.generate --scenario eligibility_outage --duration 60` |
| Frontend dev | `cd frontend && npm run dev` |
| Frontend build | `cd frontend && npm run build` |
| Frontend lint | `cd frontend && npm run lint` |
| Full stack | `docker compose up --build` |

## Troubleshooting

- **Port 8000 in use**: run the backend on another port and start the UI with
  `HEALTHTRACE_BACKEND=http://127.0.0.1:<port> npm run dev`.
- **Dashboard shows REPLAYING**: the backend is catching up on existing log
  files; it switches to live when done.
- **No HIPAA traffic**: staff traffic only flows during business hours in
  `hipaa.timezone`. Change it in `config.yaml` for demos in another zone.
- **Reset everything**: stop the backend and delete `data/`.
