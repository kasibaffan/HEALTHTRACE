import asyncio
import logging
import time

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.concurrency import run_in_threadpool

from app.auth.deps import authenticate
from app.core.config import settings
from app.core.errors import AppError
from app.database.session import SessionLocal
from app.websocket.manager import Conn, hub, make_event

log = logging.getLogger("healthtrace.ws")
router = APIRouter()
TOKEN_GRACE_SECONDS = 20 * 60


def _authenticate(token: str):
    db = SessionLocal()
    try:
        ctx = authenticate(db, token)
        return ctx.user.id, ctx.org_id, ctx.user.full_name, ctx.user.avatar_url
    finally:
        db.close()


@router.websocket("/ws")
async def realtime(websocket: WebSocket):
    origin = websocket.headers.get("origin")
    if origin and origin not in settings.cors_origins:
        await websocket.close(code=4403)
        return
    await websocket.accept()
    conn: Conn | None = None
    try:
        first = await asyncio.wait_for(websocket.receive_json(), timeout=8)
        if first.get("type") != "auth" or not isinstance(first.get("token"), str):
            raise AppError(401, "auth required")
        user_id, org_id, name, avatar = await run_in_threadpool(_authenticate, first["token"])
        conn = Conn(websocket, user_id, org_id, name, avatar)
        authed_at = time.monotonic()
        await hub.add(conn)
        await websocket.send_json(make_event("CONNECTED", payload={"userId": str(user_id)}))
        while True:
            try:
                msg = await asyncio.wait_for(websocket.receive_json(), timeout=30)
            except asyncio.TimeoutError:
                if time.monotonic() - authed_at > TOKEN_GRACE_SECONDS:
                    await websocket.close(code=4401)
                    return
                continue
            kind = msg.get("type")
            if kind == "ping":
                await websocket.send_json({"type": "pong"})
            elif kind == "auth" and isinstance(msg.get("token"), str):
                await run_in_threadpool(_authenticate, msg["token"])  # token refresh: re-validates the session
                authed_at = time.monotonic()
            elif kind == "presence":
                previous, current = conn.case_id, msg.get("caseId") if isinstance(msg.get("caseId"), str) else None
                conn.case_id = current
                for cid in {c for c in (previous, current) if c}:
                    await hub.broadcast_presence(org_id, cid)
    except (WebSocketDisconnect, asyncio.TimeoutError):
        pass
    except AppError:
        await _close(websocket, 4401)
    except Exception:  # noqa: BLE001
        log.exception("websocket error")
        await _close(websocket, 1011)
    finally:
        if conn:
            await hub.remove(conn)


async def _close(ws: WebSocket, code: int) -> None:
    try:
        await ws.close(code=code)
    except Exception:  # noqa: BLE001
        pass
