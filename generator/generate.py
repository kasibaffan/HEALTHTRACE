"""MedGuard synthetic log generator (SPEC.md section 7).

Writes JSON-line app and audit logs. Three modes:

- ``--backfill-hours N``  write N hours of normal historical logs ending now,
  then exit. Used to warm every (service, hour_of_day) baseline before a demo.
- ``--scenario NAME --duration S``  write normal traffic for S seconds with
  NAME injected on top, then exit. Useful for tests and for exercising a
  scenario without the dashboard.
- (no flags) stream normal traffic forever in real time, polling
  data/control.json once a second for a scenario injected by the dashboard's
  POST /api/demo/inject (a later milestone).

Only synthetic data: patient IDs look like P-000123, never real PHI.
"""

from __future__ import annotations

import argparse
import json
import random
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator, Optional

from generator.scenarios import (
    ALL_SCENARIO_NAMES,
    RECOVERY_SCENARIO,
    AccessScenario,
    ServiceScenario,
    get_access_scenario,
    get_service_scenario,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LOG_DIR = REPO_ROOT / "data" / "logs"
DEFAULT_CONTROL_FILE = REPO_ROOT / "data" / "control.json"

SERVICES = ["prior_auth", "eligibility", "pharmacy", "claims", "batch"]
REGIONS = ["TN-North", "TN-South", "TN-East", "TN-West"]
ROLES = [
    "care_manager",
    "claims_processor",
    "pharmacist",
    "eligibility_specialist",
    "supervisor",
    "auditor",
]
NUM_USERS = 30

# Per-service normal-traffic shape. err_range keeps overall error rate in the
# spec's 0.5-3% band; urgent_base is each service's normal urgent/routine mix.
SERVICE_META: dict[str, dict] = {
    "prior_auth": dict(
        weight=0.25, prefix="PA", err_range=(0.01, 0.03), urgent_base=0.50,
        latency_range=(120, 450), has_patients=True,
        errors=[
            "Clinical rules engine timeout",
            "Prior auth service unavailable",
            "Downstream eligibility check failed",
            "Rules engine returned malformed response",
        ],
        oks=["Prior authorization approved", "Prior authorization request processed"],
    ),
    "eligibility": dict(
        weight=0.20, prefix="ELG", err_range=(0.005, 0.02), urgent_base=0.25,
        latency_range=(80, 350), has_patients=True,
        errors=[
            "Eligibility lookup timeout",
            "Payer system unavailable",
            "Eligibility record not found",
        ],
        oks=["Eligibility verified", "Eligibility check completed"],
    ),
    "pharmacy": dict(
        weight=0.20, prefix="RX", err_range=(0.005, 0.02), urgent_base=0.20,
        latency_range=(60, 300), has_patients=True,
        errors=[
            "Pharmacy claim rejected",
            "Drug interaction check failed",
            "Formulary lookup timeout",
        ],
        oks=["Pharmacy claim processed", "Prescription fill approved"],
    ),
    "claims": dict(
        weight=0.25, prefix="CLM", err_range=(0.01, 0.03), urgent_base=0.05,
        latency_range=(50, 300), has_patients=True,
        errors=[
            "Claim adjudication error",
            "Claims database timeout",
            "Invalid claim payload",
        ],
        oks=["Claim adjudicated", "Claim accepted for processing"],
    ),
    "batch": dict(
        weight=0.10, prefix="BATCH", err_range=(0.005, 0.015), urgent_base=0.0,
        latency_range=(200, 2000), has_patients=False,
        errors=[
            "Nightly batch job failed",
            "Batch record processing error",
            "Batch job timeout",
        ],
        oks=["Batch job completed", "Batch record processed"],
    ),
}

_ERROR_STATUSES = [500, 502, 503, 504]
_OK_STATUSES = [200, 200, 200, 201, 400, 404]
_ACTION_WEIGHTS = [("VIEW_RECORD", 0.70), ("SEARCH", 0.20), ("EDIT_RECORD", 0.08), ("EXPORT_RECORDS", 0.02)]


@dataclass
class UserProfile:
    user_id: str
    role: str
    region: str


def build_user_pool(rng: random.Random, count: int = NUM_USERS) -> list[UserProfile]:
    return [
        UserProfile(user_id=f"U-{i:03d}", role=rng.choice(ROLES), region=rng.choice(REGIONS))
        for i in range(1, count + 1)
    ]


def _scenario_user_profile(user_id: str, region: str) -> UserProfile:
    """A named individual called out by a scenario (e.g. U-117), not from the normal pool."""
    return UserProfile(user_id=user_id, role="care_manager", region=region)


def _iso(ts: datetime) -> str:
    ts = ts.astimezone(timezone.utc)
    return ts.strftime("%Y-%m-%dT%H:%M:%S.") + f"{ts.microsecond // 1000:03d}Z"


def _random_patient_id(rng: random.Random) -> str:
    return f"P-{rng.randint(1, 999999):06d}"


def _service_weights() -> list[float]:
    return [SERVICE_META[s]["weight"] for s in SERVICES]


def make_app_event(
    service: str,
    ts: datetime,
    rng: random.Random,
    override: Optional[ServiceScenario] = None,
) -> dict:
    """Build one app.log line (SPEC.md section 5), optionally under a ServiceScenario."""
    meta = SERVICE_META[service]
    scenario_active = override is not None and override.service == service

    error_rate = override.error_rate if scenario_active else rng.uniform(*meta["err_range"])
    is_error = rng.random() < error_rate

    urgent_base = override.urgent_fraction if (scenario_active and is_error) else meta["urgent_base"]
    priority = "urgent" if rng.random() < urgent_base else "routine"

    has_patients = override.affected_patients if scenario_active else meta["has_patients"]
    patient_id = _random_patient_id(rng) if has_patients else None

    latency_min, latency_max = meta["latency_range"]
    multiplier = override.latency_multiplier if scenario_active else 1.0
    latency_ms = rng.uniform(latency_min, latency_max) * multiplier
    if is_error:
        latency_ms *= rng.uniform(1.3, 2.5)  # timeouts run long

    if is_error:
        level = "ERROR"
        status = rng.choice(_ERROR_STATUSES)
        msg = rng.choice(meta["errors"])
    else:
        status = rng.choice(_OK_STATUSES)
        if status >= 400:
            level = "WARN"
            msg = "Client request rejected"
        elif latency_ms > latency_max:
            level = "WARN"
            msg = "Elevated latency observed"
        else:
            level = "INFO"
            msg = rng.choice(meta["oks"])

    return {
        "ts": _iso(ts),
        "type": "app",
        "service": service,
        "level": level,
        "priority": priority,
        "request_id": f"{meta['prefix']}-{rng.randint(10000, 99999)}",
        "patient_id": patient_id,
        "status": status,
        "latency_ms": max(int(latency_ms), 1),
        "msg": msg,
    }


def make_audit_event(
    user: UserProfile,
    ts: datetime,
    rng: random.Random,
    *,
    action: Optional[str] = None,
    region_mismatch: bool = False,
) -> dict:
    """Build one audit.log line (SPEC.md section 5)."""
    if action is None:
        action = rng.choices(
            [a for a, _ in _ACTION_WEIGHTS],
            weights=[w for _, w in _ACTION_WEIGHTS],
        )[0]

    patient_region = user.region
    if region_mismatch:
        other_regions = [r for r in REGIONS if r != user.region]
        patient_region = rng.choice(other_regions)

    return {
        "ts": _iso(ts),
        "type": "audit",
        "user_id": user.user_id,
        "role": user.role,
        "action": action,
        "patient_id": _random_patient_id(rng),
        "patient_region": patient_region,
        "user_region": user.region,
    }


def _poisson_times(start: datetime, duration_s: float, rate_per_sec: float, rng: random.Random) -> Iterator[datetime]:
    """Event arrival times for a Poisson process, so ~rate_per_sec events land per second on average."""
    rate_per_sec = max(rate_per_sec, 1e-6)
    t = 0.0
    while True:
        t += rng.expovariate(rate_per_sec)
        if t >= duration_s:
            return
        yield start + timedelta(seconds=t)


def generate_batch(
    scenario_name: Optional[str],
    duration_s: float,
    rate: float,
    start: datetime,
    rng: random.Random,
) -> tuple[list[dict], list[dict]]:
    """Normal traffic across all services/users for duration_s, with an optional
    named scenario (SPEC.md section 7) injected on top. Returns (app_events,
    audit_events), each sorted by ts. scenario_name=None or "recovery" means
    plain normal traffic (used for --backfill-hours and for demonstrating
    recovery).
    """
    if scenario_name not in (None, *ALL_SCENARIO_NAMES):
        raise ValueError(f"Unknown scenario: {scenario_name}")

    service_scn = get_service_scenario(scenario_name) if scenario_name else None
    access_scn = get_access_scenario(scenario_name) if scenario_name else None
    users = build_user_pool(rng)

    app_events = [
        make_app_event(rng.choices(SERVICES, weights=_service_weights())[0], ts, rng, override=service_scn)
        for ts in _poisson_times(start, duration_s, rate, rng)
    ]

    audit_rate = max(rate / 6, 0.5)  # ~30 users browsing steadily; not error-driven
    audit_events = [
        make_audit_event(rng.choice(users), ts, rng) for ts in _poisson_times(start, duration_s, audit_rate, rng)
    ]

    if access_scn is not None:
        target = _scenario_user_profile(access_scn.user_id, "TN-North")
        pace = access_scn.total_patients / duration_s
        for ts in _poisson_times(start, duration_s, pace, rng):
            event_ts = ts
            if access_scn.kind == "off_hours" and access_scn.hour_of_day is not None:
                elapsed = (ts - start).total_seconds()
                event_ts = start.replace(hour=access_scn.hour_of_day, minute=0, second=0, microsecond=0)
                event_ts += timedelta(seconds=elapsed)
            audit_events.append(
                make_audit_event(target, event_ts, rng, region_mismatch=(access_scn.kind == "region_mismatch"))
            )

    app_events.sort(key=lambda e: e["ts"])
    audit_events.sort(key=lambda e: e["ts"])
    return app_events, audit_events


def _append_lines(path: Path, events: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        for event in events:
            f.write(json.dumps(event) + "\n")


def _read_control(path: Path) -> Optional[tuple[dict, float]]:
    try:
        mtime = path.stat().st_mtime
        data = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    return data, mtime


def run_live(rate: float, log_dir: Path, control_file: Path, rng: random.Random) -> None:
    """Stream normal traffic forever, polling control_file once a second for a
    dashboard-injected scenario (SPEC.md section 7). Runs until interrupted.
    """
    log_dir.mkdir(parents=True, exist_ok=True)
    users = build_user_pool(rng)
    app_path = log_dir / "app.log"
    audit_path = log_dir / "audit.log"

    active_service: Optional[ServiceScenario] = None
    active_access: Optional[AccessScenario] = None
    active_until = 0.0
    scenario_started_at = datetime.now(timezone.utc)
    last_control_check = 0.0
    last_control_mtime: Optional[float] = None

    audit_rate = max(rate / 6, 0.5)

    with app_path.open("a", encoding="utf-8") as app_f, audit_path.open("a", encoding="utf-8") as audit_f:
        next_app = time.monotonic()
        next_audit = time.monotonic()

        while True:
            now_mono = time.monotonic()

            if now_mono - last_control_check >= 1.0:
                last_control_check = now_mono
                result = _read_control(control_file)
                if result is not None:
                    data, mtime = result
                    if mtime != last_control_mtime:
                        last_control_mtime = mtime
                        name = data.get("scenario")
                        duration_s = float(data.get("duration_s", 60))
                        if name in (None, RECOVERY_SCENARIO):
                            active_service = active_access = None
                            active_until = 0.0
                        else:
                            active_service = get_service_scenario(name)
                            active_access = get_access_scenario(name)
                            active_until = now_mono + duration_s
                            scenario_started_at = datetime.now(timezone.utc)

            if active_until and now_mono >= active_until:
                active_service = active_access = None
                active_until = 0.0

            if now_mono >= next_app:
                ts = datetime.now(timezone.utc)
                service = rng.choices(SERVICES, weights=_service_weights())[0]
                event = make_app_event(service, ts, rng, override=active_service)
                app_f.write(json.dumps(event) + "\n")
                app_f.flush()
                next_app = now_mono + rng.expovariate(max(rate, 1e-6))

            if now_mono >= next_audit:
                ts = datetime.now(timezone.utc)
                pace = audit_rate
                if active_access is not None:
                    target = _scenario_user_profile(active_access.user_id, "TN-North")
                    if active_access.kind == "off_hours" and active_access.hour_of_day is not None:
                        elapsed = (ts - scenario_started_at).total_seconds()
                        ts = ts.replace(hour=active_access.hour_of_day, minute=0, second=0, microsecond=0)
                        ts += timedelta(seconds=elapsed)
                    event = make_audit_event(
                        target, ts, rng, region_mismatch=(active_access.kind == "region_mismatch")
                    )
                    remaining = max(active_until - now_mono, 1.0)
                    pace = max(active_access.total_patients / remaining, audit_rate)
                else:
                    event = make_audit_event(rng.choice(users), ts, rng)
                audit_f.write(json.dumps(event) + "\n")
                audit_f.flush()
                next_audit = now_mono + rng.expovariate(max(pace, 1e-6))

            time.sleep(0.01)


def main(argv: Optional[list[str]] = None) -> None:
    parser = argparse.ArgumentParser(description="MedGuard synthetic log generator (SPEC.md section 7).")
    parser.add_argument("--rate", type=float, default=30.0, help="app events/sec (spec range 20-50, default 30)")
    parser.add_argument(
        "--backfill-hours", type=float, default=None,
        help="write N hours of normal historical logs ending now, then exit",
    )
    parser.add_argument("--scenario", choices=ALL_SCENARIO_NAMES, default=None, help="inject a named scenario")
    parser.add_argument("--duration", type=float, default=60.0, help="seconds; used with --scenario")
    parser.add_argument("--log-dir", type=Path, default=DEFAULT_LOG_DIR)
    parser.add_argument("--control-file", type=Path, default=DEFAULT_CONTROL_FILE)
    parser.add_argument("--seed", type=int, default=None, help="for reproducible output")
    args = parser.parse_args(argv)

    rng = random.Random(args.seed)

    if args.backfill_hours is not None:
        end = datetime.now(timezone.utc)
        start = end - timedelta(hours=args.backfill_hours)
        app_events, audit_events = generate_batch(None, args.backfill_hours * 3600, args.rate, start, rng)
        _append_lines(args.log_dir / "app.log", app_events)
        _append_lines(args.log_dir / "audit.log", audit_events)
        print(
            f"Backfilled {len(app_events)} app events and {len(audit_events)} audit events "
            f"over {args.backfill_hours}h -> {args.log_dir}"
        )
        return

    if args.scenario is not None:
        app_events, audit_events = generate_batch(
            args.scenario, args.duration, args.rate, datetime.now(timezone.utc), rng
        )
        _append_lines(args.log_dir / "app.log", app_events)
        _append_lines(args.log_dir / "audit.log", audit_events)
        print(
            f"Injected '{args.scenario}' for {args.duration}s: "
            f"{len(app_events)} app events, {len(audit_events)} audit events -> {args.log_dir}"
        )
        return

    print(f"Streaming ~{args.rate} events/sec to {args.log_dir} (Ctrl+C to stop)...")
    try:
        run_live(args.rate, args.log_dir, args.control_file, rng)
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
