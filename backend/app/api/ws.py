"""WebSocket endpoint and broadcaster (SPEC.md section 6.11).

On connect: a snapshot, then a stream of metric/alert/incident_update/
heartbeat messages. A failed send drops that connection from the broadcast
set rather than raising into the caller (detection must never be blocked or
crashed by one dead client).
"""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

router = APIRouter()


class Broadcaster:
    def __init__(self) -> None:
        self._connections: set[WebSocket] = set()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._connections.add(ws)

    def disconnect(self, ws: WebSocket) -> None:
        self._connections.discard(ws)

    async def broadcast(self, message: dict[str, Any]) -> None:
        if not self._connections:
            return
        payload = json.dumps(message, default=str)
        dead = []
        for ws in list(self._connections):
            try:
                await ws.send_text(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)


@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    pipeline = ws.app.state.pipeline
    await pipeline.broadcaster.connect(ws)
    try:
        await ws.send_text(json.dumps(pipeline.snapshot(), default=str))
        while True:
            # This endpoint is push-only; just wait for the client to
            # disconnect (or send anything, which we ignore).
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        pipeline.broadcaster.disconnect(ws)
