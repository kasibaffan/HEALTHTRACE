# Backend

FastAPI app in `backend/app`, started with `uvicorn app.main:app` from the
`backend/` directory (or from anywhere with `HEALTHTRACE_ROOT` pointing at the
repository root).

## Key behaviours

- **Business hours** for the HIPAA off-hours rule are judged in
  `hipaa.timezone` (default `America/Chicago`). The generator only produces
  ordinary staff traffic inside those hours.
- **HIPAA re-alerting** is throttled per user and pattern
  (`hipaa.realert_seconds`); a severity escalation always alerts.
- **Mute** pauses AWS notifications for one anomaly; detection continues.
- **Operator token**: when `OPERATOR_TOKEN` is set, write endpoints require
  the `X-Operator-Token` header.
- **Alerts carry their scoring inputs** (z, baseline, criticality, deviation
  and patient factors) so the UI can show exactly how severity was computed.

## Stabilisation log

Problems found by running the backend against real generator output, and
their fixes (each has a regression test in `tests/test_hardening.py`):

| Problem | Effect | Fix |
|---|---|---|
| Off-hours judged in UTC while staff traffic ran 24/7 | ~90 false HIGH alerts/sec for 10 h a day, detection stalled | Configurable timezone; generator respects business hours; re-alert throttle |
| First-run detection keyed on "any baseline saved" | An interrupted first start skipped the whole backfill | Persist tail positions with baselines |
| Tailer read the whole file into memory | 600 MB+ string on replay | Bounded 1 MB chunked, byte-offset reads |
| Incident ids restarted at 1 | New incidents overwrote stored history | Restore incidents and next id on startup |
| `/api/incidents` read memory only | Older incidents per fingerprint disappeared | Merge store history with live state |
| One SQLite commit per write, fsync'd | ~100 writes/s ceiling | WAL + `synchronous=NORMAL`, periodic pruning |
| WebSocket sends awaited inline | A slow browser slowed detection; snapshot could interleave | Per-client bounded queue and sender task |
| HIPAA timeout sweep only on audit events | HIPAA incidents never resolved overnight | Sweep on every event-second |
| Notifier `stop()` waited forever | Shutdown hung while AWS was failing | Bounded drain |
| Live mode without `SNS_TOPIC_ARN` | Five retries per page | Skipped and counted |
| Demo inject accepted any string | Arbitrary control-file contents | Validated scenario and duration |
| CORS `*` with credentials | Invalid and over-broad | Configurable origin list |
| Generator | ~60% of requested rate on Windows; scenarios paced wrong; replayed last scenario on restart | Schedule-based emission, per-scenario pacing, ignore stale control file |
| Test dependencies | Suite failed to import on a clean install | Added `httpx` to dev extras |
