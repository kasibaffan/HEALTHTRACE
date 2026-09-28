"""SQLite persistence, aiosqlite-backed (SPEC.md section 6.10).

The full schema is created now so it's stable across milestones. Milestone 3
only exercises the ``baselines`` table (EWMA persistence: SPEC.md 6.4 —
"every 60 seconds and on shutdown, reload on startup"). The other tables get
their read/write methods in Milestone 4 (incidents, access_stats) and
Milestone 5 (metrics history, alerts).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import aiosqlite

from app.models import Alert, Incident, IncidentEvent, WindowMetrics

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
    malformed_lines INTEGER NOT NULL DEFAULT 0,
    baseline_mean REAL,
    baseline_std REAL
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

-- Byte position of each tailed log file, saved together with the baselines so
-- a restart resumes exactly where the learned state left off.
CREATE TABLE IF NOT EXISTS tail_positions (
    path TEXT PRIMARY KEY,
    file_id INTEGER,
    offset INTEGER NOT NULL,
    updated_at TEXT NOT NULL
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
        self._last_prune_cutoff: Optional[datetime] = None

    async def connect(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self.db_path)
        # WAL + NORMAL: commits no longer fsync, which is what capped the
        # pipeline at ~100 writes/sec during replay and alert bursts.
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.execute("PRAGMA synchronous=NORMAL")
        await self._conn.executescript(SCHEMA)
        await self._migrate()
        await self._conn.commit()

    async def _migrate(self) -> None:
        cursor = await self.conn.execute("PRAGMA table_info(metrics)")
        columns = {row[1] for row in await cursor.fetchall()}
        for column in ("baseline_mean", "baseline_std"):
            if column not in columns:
                await self.conn.execute(f"ALTER TABLE metrics ADD COLUMN {column} REAL")

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
        ts = datetime.now(timezone.utc).isoformat()
        await self.conn.executemany(
            """
            INSERT INTO baselines (service, hour_of_day, metric, mean, variance, count, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(service, hour_of_day, metric)
            DO UPDATE SET mean=excluded.mean, variance=excluded.variance,
                          count=excluded.count, updated_at=excluded.updated_at
            """,
            [(r.service, r.hour_of_day, r.metric, r.mean, r.variance, r.count, ts) for r in rows],
        )
        await self.conn.commit()

    # -- tail positions --------------------------------------------------------

    async def save_tail_position(self, path: str, file_id: Optional[int], offset: int) -> None:
        await self.conn.execute(
            """
            INSERT INTO tail_positions (path, file_id, offset, updated_at) VALUES (?, ?, ?, ?)
            ON CONFLICT(path) DO UPDATE SET file_id=excluded.file_id, offset=excluded.offset,
                                            updated_at=excluded.updated_at
            """,
            (path, file_id, offset, datetime.now(timezone.utc).isoformat()),
        )
        await self.conn.commit()

    async def load_tail_positions(self) -> dict[str, tuple[Optional[int], int]]:
        cursor = await self.conn.execute("SELECT path, file_id, offset FROM tail_positions")
        return {row[0]: (row[1], row[2]) for row in await cursor.fetchall()}

    async def load_baselines(self) -> list[BaselineRow]:
        cursor = await self.conn.execute(
            "SELECT service, hour_of_day, metric, mean, variance, count FROM baselines"
        )
        rows = await cursor.fetchall()
        return [BaselineRow(*row) for row in rows]

    # -- metrics (Milestone 5): 24h retention per SPEC.md 6.10 ----------------

    async def save_metrics(self, metrics: WindowMetrics) -> None:
        await self.conn.execute(
            """
            INSERT INTO metrics
                (service, window_end, total, errors, error_rate, p95_latency_ms,
                 urgent_errors, affected_patients_urgent, affected_patients_routine, malformed_lines,
                 baseline_mean, baseline_std)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                metrics.service, metrics.window_end.isoformat(), metrics.total, metrics.errors,
                metrics.error_rate, metrics.p95_latency_ms, metrics.urgent_errors,
                metrics.affected_patients_urgent, metrics.affected_patients_routine, metrics.malformed_lines,
                metrics.baseline_mean, metrics.baseline_std,
            ),
        )
        cutoff = metrics.window_end - timedelta(hours=24)
        if self._last_prune_cutoff is None or cutoff - self._last_prune_cutoff >= timedelta(minutes=1):
            await self.conn.execute("DELETE FROM metrics WHERE window_end < ?", (cutoff.isoformat(),))
            self._last_prune_cutoff = cutoff
        await self.conn.commit()

    async def list_metrics(self, *, service: str, minutes: int = 15, before: Optional[datetime] = None) -> list[WindowMetrics]:
        end = before or datetime.now(timezone.utc)
        since = (end - timedelta(minutes=minutes)).isoformat()
        cursor = await self.conn.execute(
            """
            SELECT service, window_end, total, errors, error_rate, p95_latency_ms,
                   urgent_errors, affected_patients_urgent, affected_patients_routine, malformed_lines,
                   baseline_mean, baseline_std
            FROM metrics WHERE service = ? AND window_end >= ? ORDER BY window_end ASC
            """,
            (service, since),
        )
        rows = await cursor.fetchall()
        return [
            WindowMetrics(
                service=r[0], window_end=datetime.fromisoformat(r[1]), total=r[2], errors=r[3], error_rate=r[4],
                p95_latency_ms=r[5], urgent_errors=r[6], affected_patients_urgent=r[7],
                affected_patients_routine=r[8], malformed_lines=r[9], baseline_mean=r[10], baseline_std=r[11],
            )
            for r in rows
        ]

    # -- alerts (Milestone 4) -------------------------------------------------

    async def save_alert(self, alert: Alert) -> int:
        cursor = await self.conn.execute(
            """
            INSERT INTO alerts (ts, kind, service, user_id, severity, score, explanation, metrics_json, incident_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                alert.ts.isoformat(), alert.kind, alert.service, alert.user_id, alert.severity, alert.score,
                alert.explanation, json.dumps(alert.metrics), alert.incident_id,
            ),
        )
        await self.conn.commit()
        assert cursor.lastrowid is not None
        return cursor.lastrowid

    async def list_alerts(
        self,
        *,
        limit: int = 100,
        severity: Optional[str] = None,
        service: Optional[str] = None,
        kind: Optional[str] = None,
        incident_id: Optional[int] = None,
        user_id: Optional[str] = None,
    ) -> list[Alert]:
        query = "SELECT id, ts, kind, service, user_id, severity, score, explanation, metrics_json, incident_id FROM alerts"
        clauses: list[str] = []
        params: list[object] = []
        for column, value in (
            ("severity", severity), ("service", service), ("kind", kind),
            ("incident_id", incident_id), ("user_id", user_id),
        ):
            if value is not None:
                clauses.append(f"{column} = ?")
                params.append(value)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY ts DESC, id DESC LIMIT ?"
        params.append(limit)
        cursor = await self.conn.execute(query, params)
        rows = await cursor.fetchall()
        return [_row_to_alert(row) for row in rows]

    # -- incidents (Milestone 4) -----------------------------------------------

    async def upsert_incident(self, incident: Incident) -> None:
        await self.conn.execute(
            """
            INSERT INTO incidents
                (id, fingerprint, kind, service, user_id, state, peak_severity, alert_count,
                 opened_at, acknowledged_at, resolved_at, mttr_seconds)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                state=excluded.state, peak_severity=excluded.peak_severity, alert_count=excluded.alert_count,
                acknowledged_at=excluded.acknowledged_at, resolved_at=excluded.resolved_at,
                mttr_seconds=excluded.mttr_seconds
            """,
            (
                incident.id, incident.fingerprint, incident.kind, incident.service, incident.user_id,
                incident.state, incident.peak_severity, incident.alert_count, incident.opened_at.isoformat(),
                _iso_or_none(incident.acknowledged_at), _iso_or_none(incident.resolved_at), incident.mttr_seconds,
            ),
        )
        await self.conn.commit()

    async def get_incident(self, incident_id: int) -> Optional[Incident]:
        cursor = await self.conn.execute(
            """
            SELECT id, fingerprint, kind, service, user_id, state, peak_severity, alert_count,
                   opened_at, acknowledged_at, resolved_at, mttr_seconds
            FROM incidents WHERE id = ?
            """,
            (incident_id,),
        )
        row = await cursor.fetchone()
        return _row_to_incident(row) if row else None

    async def list_incidents(self, *, state: Optional[str] = None, limit: Optional[int] = None) -> list[Incident]:
        query = (
            "SELECT id, fingerprint, kind, service, user_id, state, peak_severity, alert_count, "
            "opened_at, acknowledged_at, resolved_at, mttr_seconds FROM incidents"
        )
        params: list[object] = []
        if state is not None:
            query += " WHERE state = ?"
            params.append(state)
        query += " ORDER BY opened_at DESC, id DESC"
        if limit is not None:
            query += " LIMIT ?"
            params.append(limit)
        cursor = await self.conn.execute(query, params)
        rows = await cursor.fetchall()
        return [_row_to_incident(row) for row in rows]

    async def max_incident_id(self) -> int:
        cursor = await self.conn.execute("SELECT COALESCE(MAX(id), 0) FROM incidents")
        row = await cursor.fetchone()
        return int(row[0]) if row else 0

    async def last_alert_ts_by_incident(self, incident_ids: list[int]) -> dict[int, datetime]:
        if not incident_ids:
            return {}
        marks = ",".join("?" for _ in incident_ids)
        cursor = await self.conn.execute(
            f"SELECT incident_id, MAX(ts) FROM alerts WHERE incident_id IN ({marks}) GROUP BY incident_id",
            incident_ids,
        )
        return {row[0]: datetime.fromisoformat(row[1]) for row in await cursor.fetchall()}

    # -- analytics ---------------------------------------------------------------

    async def alert_counts(self, *, since: datetime) -> list[tuple[str, str, str, int]]:
        """(hour bucket 'YYYY-MM-DDTHH', severity, service-or-'hipaa', count) for alerts since ``since``."""
        cursor = await self.conn.execute(
            """
            SELECT substr(ts, 1, 13) AS hour, severity, COALESCE(service, 'hipaa'), COUNT(*)
            FROM alerts WHERE ts >= ? GROUP BY hour, severity, COALESCE(service, 'hipaa') ORDER BY hour
            """,
            (since.isoformat(),),
        )
        return [(r[0], r[1], r[2], r[3]) for r in await cursor.fetchall()]

    async def alert_kind_counts(self, *, since: datetime) -> list[tuple[str, int]]:
        cursor = await self.conn.execute(
            "SELECT kind, COUNT(*) FROM alerts WHERE ts >= ? GROUP BY kind ORDER BY COUNT(*) DESC",
            (since.isoformat(),),
        )
        return [(r[0], r[1]) for r in await cursor.fetchall()]

    async def metrics_hourly(self, *, since: datetime) -> list[tuple[str, str, int, int, float]]:
        """(hour bucket, service, summed total, summed errors, avg p95) from stored windows.

        Each 60s window is re-emitted every 5s, so raw sums over-count events
        by window/step; callers divide by that factor."""
        cursor = await self.conn.execute(
            """
            SELECT substr(window_end, 1, 13) AS hour, service, SUM(total), SUM(errors), AVG(p95_latency_ms)
            FROM metrics WHERE window_end >= ? GROUP BY hour, service ORDER BY hour
            """,
            (since.isoformat(),),
        )
        return [(r[0], r[1], r[2] or 0, r[3] or 0, r[4] or 0.0) for r in await cursor.fetchall()]

    async def save_incident_event(self, event: IncidentEvent) -> int:
        cursor = await self.conn.execute(
            "INSERT INTO incident_events (incident_id, ts, event_type, severity, detail) VALUES (?, ?, ?, ?, ?)",
            (event.incident_id, event.ts.isoformat(), event.event_type, event.severity, event.detail),
        )
        await self.conn.commit()
        assert cursor.lastrowid is not None
        return cursor.lastrowid

    async def list_incident_events(self, incident_id: int) -> list[IncidentEvent]:
        cursor = await self.conn.execute(
            "SELECT id, incident_id, ts, event_type, severity, detail FROM incident_events "
            "WHERE incident_id = ? ORDER BY ts ASC",
            (incident_id,),
        )
        rows = await cursor.fetchall()
        return [
            IncidentEvent(id=r[0], incident_id=r[1], ts=datetime.fromisoformat(r[2]), event_type=r[3],
                          severity=r[4], detail=r[5])
            for r in rows
        ]

    # -- access_stats (Milestone 4: per-user access baseline persistence) ----

    async def save_access_stat(
        self, user_id: str, metric: str, mean: float, variance: float, count: int,
        *, updated_at: Optional[datetime] = None,
    ) -> None:
        ts = (updated_at or datetime.now(timezone.utc)).isoformat()
        await self.conn.execute(
            """
            INSERT INTO access_stats (user_id, metric, mean, variance, count, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id, metric)
            DO UPDATE SET mean=excluded.mean, variance=excluded.variance,
                          count=excluded.count, updated_at=excluded.updated_at
            """,
            (user_id, metric, mean, variance, count, ts),
        )
        await self.conn.commit()

    async def load_access_stats(self) -> list[tuple[str, str, float, float, int]]:
        cursor = await self.conn.execute("SELECT user_id, metric, mean, variance, count FROM access_stats")
        return list(await cursor.fetchall())


def _iso_or_none(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat() if value is not None else None


def _row_to_alert(row) -> Alert:
    return Alert(
        id=row[0], ts=datetime.fromisoformat(row[1]), kind=row[2], service=row[3], user_id=row[4],
        severity=row[5], score=row[6], explanation=row[7], metrics=json.loads(row[8]), incident_id=row[9],
    )


def _row_to_incident(row) -> Incident:
    return Incident(
        id=row[0], fingerprint=row[1], kind=row[2], service=row[3], user_id=row[4], state=row[5],
        peak_severity=row[6], alert_count=row[7], opened_at=datetime.fromisoformat(row[8]),
        acknowledged_at=datetime.fromisoformat(row[9]) if row[9] else None,
        resolved_at=datetime.fromisoformat(row[10]) if row[10] else None, mttr_seconds=row[11],
    )
