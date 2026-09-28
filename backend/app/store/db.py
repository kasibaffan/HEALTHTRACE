"""SQLite persistence, aiosqlite-backed (SPEC.md section 6.10).

The full schema is created now so it's stable across milestones. Milestone 3
only exercises the ``baselines`` table (EWMA persistence: SPEC.md 6.4 —
"every 60 seconds and on shutdown, reload on startup"). The other tables get
their read/write methods in Milestone 4 (incidents, access_stats) and
Milestone 5 (metrics history, alerts).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import aiosqlite

SCHEMA = """
CREATE TABLE IF NOT EXISTS metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    service TEXT NOT NULL,
    window_end TEXT NOT NULL,
    total INTEGER NOT NULL,
    errors INTEGER NOT NULL,
    error_rate REAL NOT NULL,
    p95_latency_ms REAL NOT NULL,
    urgent_errors INTEGER NOT NULL,
    affected_patients_urgent INTEGER NOT NULL,
    affected_patients_routine INTEGER NOT NULL,
    malformed_lines INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_metrics_service_ts ON metrics(service, window_end);

CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    kind TEXT NOT NULL,
    service TEXT,
    user_id TEXT,
    severity TEXT NOT NULL,
    score REAL NOT NULL,
    explanation TEXT NOT NULL,
    metrics_json TEXT NOT NULL DEFAULT '{}',
    incident_id INTEGER
);
CREATE INDEX IF NOT EXISTS idx_alerts_ts ON alerts(ts);
CREATE INDEX IF NOT EXISTS idx_alerts_service ON alerts(service);

CREATE TABLE IF NOT EXISTS incidents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fingerprint TEXT NOT NULL,
    kind TEXT NOT NULL,
    service TEXT,
    user_id TEXT,
    state TEXT NOT NULL,
    peak_severity TEXT NOT NULL,
    alert_count INTEGER NOT NULL DEFAULT 1,
    opened_at TEXT NOT NULL,
    acknowledged_at TEXT,
    resolved_at TEXT,
    mttr_seconds REAL
);
CREATE INDEX IF NOT EXISTS idx_incidents_fingerprint ON incidents(fingerprint);
CREATE INDEX IF NOT EXISTS idx_incidents_state ON incidents(state);

CREATE TABLE IF NOT EXISTS incident_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    incident_id INTEGER NOT NULL,
    ts TEXT NOT NULL,
    event_type TEXT NOT NULL,
    severity TEXT,
    detail TEXT
);
CREATE INDEX IF NOT EXISTS idx_incident_events_incident ON incident_events(incident_id);

-- hour_of_day = -1 is the global per-service fallback baseline (SPEC.md 6.4),
-- used before an (service, hour_of_day) bucket has warmed up.
CREATE TABLE IF NOT EXISTS baselines (
    service TEXT NOT NULL,
    hour_of_day INTEGER NOT NULL,
    metric TEXT NOT NULL,
    mean REAL NOT NULL,
    variance REAL NOT NULL,
    count INTEGER NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (service, hour_of_day, metric)
);

CREATE TABLE IF NOT EXISTS access_stats (
    user_id TEXT NOT NULL,
    metric TEXT NOT NULL,
    mean REAL NOT NULL,
    variance REAL NOT NULL,
    count INTEGER NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (user_id, metric)
);
"""


@dataclass
class BaselineRow:
    service: str
    hour_of_day: int
    metric: str
    mean: float
    variance: float
    count: int


class Store:
    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path)
        self._conn: Optional[aiosqlite.Connection] = None

    async def connect(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self.db_path)
        await self._conn.executescript(SCHEMA)
        await self._conn.commit()

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("Store is not connected; call connect() first")
        return self._conn

    # -- baselines (Milestone 3) --------------------------------------------

    async def save_baseline(self, row: BaselineRow, *, updated_at: Optional[datetime] = None) -> None:
        ts = (updated_at or datetime.now(timezone.utc)).isoformat()
        await self.conn.execute(
            """
            INSERT INTO baselines (service, hour_of_day, metric, mean, variance, count, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(service, hour_of_day, metric)
            DO UPDATE SET mean=excluded.mean, variance=excluded.variance,
                          count=excluded.count, updated_at=excluded.updated_at
            """,
            (row.service, row.hour_of_day, row.metric, row.mean, row.variance, row.count, ts),
        )
        await self.conn.commit()

    async def save_baselines(self, rows: list[BaselineRow]) -> None:
        for row in rows:
            await self.save_baseline(row)

    async def load_baselines(self) -> list[BaselineRow]:
        cursor = await self.conn.execute(
            "SELECT service, hour_of_day, metric, mean, variance, count FROM baselines"
        )
        rows = await cursor.fetchall()
        return [BaselineRow(*row) for row in rows]
