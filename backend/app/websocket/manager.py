"""Org-scoped WebSocket hub. Events never cross organization boundaries."""
import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from fastapi import WebSocket

log = logging.getLogger("healthtrace.ws")

CASE_UPDATED = "CASE_UPDATED"
CASE_ASSIGNED = "CASE_ASSIGNED"
DOCUMENT_UPLOADED = "DOCUMENT_UPLOADED"
DOCUMENT_PROCESSING = "DOCUMENT_PROCESSING"
DOCUMENT_PROCESSED = "DOCUMENT_PROCESSED"
FINDING_UPDATED = "FINDING_UPDATED"
EVIDENCE_ADDED = "EVIDENCE_ADDED"
EVIDENCE_REQUESTED = "EVIDENCE_REQUESTED"
REVIEW_ACTION = "REVIEW_ACTION"
AUDIT_EVENT = "AUDIT_EVENT"
NOTIFICATION = "NOTIFICATION"
PRESENCE = "PRESENCE"


def make_event(type_: str, *, case_id: str | None = None, actor: dict | None = None, payload: dict | None = None) -> dict:
    """The single event schema used for every WebSocket message."""
    return {"type": type_, "caseId": case_id, "actor": actor, "payload": payload or {}, "timestamp": datetime.now(timezone.utc).isoformat()}


@dataclass(eq=False)
class Conn:
    ws: WebSocket
    user_id: uuid.UUID
    org_id: uuid.UUID
    name: str
    avatar_url: str | None
    case_id: str | None = None


@dataclass
class Hub:
    conns: dict[uuid.UUID, set[Conn]] = field(default_factory=dict)
    loop: asyncio.AbstractEventLoop | None = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self.loop = loop

    def connection_count(self) -> int:
        return sum(len(s) for s in self.conns.values())

    async def add(self, conn: Conn) -> None:
        self.conns.setdefault(conn.org_id, set()).add(conn)

    async def remove(self, conn: Conn) -> None:
        group = self.conns.get(conn.org_id)
        if group:
            group.discard(conn)
            if not group:
                self.conns.pop(conn.org_id, None)
        if conn.case_id:
            await self.broadcast_presence(conn.org_id, conn.case_id)

    async def _send(self, conn: Conn, event: dict) -> None:
        try:
            await conn.ws.send_json(event)
        except Exception:
            await self.remove_silently(conn)

    async def remove_silently(self, conn: Conn) -> None:
        group = self.conns.get(conn.org_id)
        if group:
            group.discard(conn)

    async def to_org(self, org_id: uuid.UUID, event: dict) -> None:
        await asyncio.gather(*[self._send(c, event) for c in list(self.conns.get(org_id, ()))])

    async def to_user(self, org_id: uuid.UUID, user_id: uuid.UUID, event: dict) -> None:
        await asyncio.gather(*[self._send(c, event) for c in list(self.conns.get(org_id, ())) if c.user_id == user_id])

    def presence(self, org_id: uuid.UUID, case_id: str) -> list[dict]:
        seen: dict[uuid.UUID, dict] = {}
        for c in self.conns.get(org_id, ()):
            if c.case_id == case_id:
                seen[c.user_id] = {"id": str(c.user_id), "fullName": c.name, "avatarUrl": c.avatar_url}
        return list(seen.values())

    async def broadcast_presence(self, org_id: uuid.UUID, case_id: str) -> None:
        await self.to_org(org_id, make_event(PRESENCE, case_id=case_id, payload={"users": self.presence(org_id, case_id)}))

    # Thread-safe entry points: sync request handlers and background tasks run in worker threads.
    def publish_org(self, org_id: uuid.UUID, event: dict) -> None:
        self._submit(self.to_org(org_id, event))

    def publish_user(self, org_id: uuid.UUID, user_id: uuid.UUID, event: dict) -> None:
        self._submit(self.to_user(org_id, user_id, event))

    def _submit(self, coro) -> None:
        if self.loop and self.loop.is_running():
            asyncio.run_coroutine_threadsafe(coro, self.loop)
        else:
            coro.close()


hub = Hub()


class Outbox:
    """Collects events during a transaction and publishes them only after a successful commit."""

    def __init__(self) -> None:
        self._org: list[tuple[uuid.UUID, dict]] = []
        self._user: list[tuple[uuid.UUID, uuid.UUID, dict]] = []

    def org(self, org_id: uuid.UUID, event: dict) -> None:
        self._org.append((org_id, event))

    def user(self, org_id: uuid.UUID, user_id: uuid.UUID, event: dict) -> None:
        self._user.append((org_id, user_id, event))

    def flush(self) -> None:
        for org_id, event in self._org:
            hub.publish_org(org_id, event)
        for org_id, user_id, event in self._user:
            hub.publish_user(org_id, user_id, event)
        self._org.clear()
        self._user.clear()
