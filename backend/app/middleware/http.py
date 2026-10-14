import logging
import time
import uuid
from collections import defaultdict, deque
from threading import Lock

from fastapi import Depends, Request
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config import settings
from app.core.errors import AppError

log = logging.getLogger("healthtrace.http")


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Request ID, structured access log (path only, never query strings, headers, or bodies) and security headers."""

    async def dispatch(self, request: Request, call_next):
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
        request.state.request_id = rid
        start = time.perf_counter()
        response = await call_next(request)
        ms = round((time.perf_counter() - start) * 1000, 1)
        response.headers["X-Request-ID"] = rid
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store" if request.url.path.startswith("/api") else response.headers.get("Cache-Control", "")
        log.info("request", extra={"request_id": rid, "method": request.method, "path": request.url.path, "status": response.status_code,
                                   "duration_ms": ms, "user_id": getattr(request.state, "user_id", None)})
        return response


class _Limiter:
    def __init__(self) -> None:
        self.hits: dict[str, deque] = defaultdict(deque)
        self.lock = Lock()

    def check(self, key: str, limit: int, window: int) -> None:
        now = time.monotonic()
        with self.lock:
            q = self.hits[key]
            while q and now - q[0] > window:
                q.popleft()
            if len(q) >= limit:
                raise AppError(429, "Too many attempts. Please wait a moment and try again.", "rate_limited")
            q.append(now)

    def reset(self) -> None:
        with self.lock:
            self.hits.clear()


limiter = _Limiter()


def rate_limit(name: str, limit: int, window_seconds: int):
    """Dependency. In-memory per-IP sliding window; swap for Redis when running multiple instances."""

    def dependency(request: Request) -> None:
        if settings.rate_limit_enabled:
            limiter.check(f"{name}:{request.client.host if request.client else 'unknown'}", limit, window_seconds)

    return Depends(dependency)
