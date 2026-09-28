"""FastAPI app: startup/shutdown of the pipeline tasks (SPEC.md section 3),
the REST + WebSocket API, and (when built) the frontend on the same origin."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from app.api.routes import router as api_router
from app.api.ws import router as ws_router
from app.config import AppConfig, Settings, get_settings, load_config
from app.pipeline import Pipeline

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
}


def create_app(settings: Optional[Settings] = None, config: Optional[AppConfig] = None) -> FastAPI:
    """settings/config are injectable so tests can point the pipeline at an
    isolated temp directory instead of the real data/ directory."""
    settings = settings or get_settings()
    config = config or load_config()
    pipeline = Pipeline(settings, config)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        await pipeline.start()
        try:
            yield
        finally:
            await pipeline.stop()

    app = FastAPI(title="HEALTH TRACE (MedGuard engine)", lifespan=lifespan)
    app.state.pipeline = pipeline

    origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
    if origins:
        app.add_middleware(
            CORSMiddleware, allow_origins=origins, allow_credentials=False,
            allow_methods=["GET", "POST"], allow_headers=["Content-Type", "X-Operator-Token"],
        )

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response: Response = await call_next(request)
        for key, value in _SECURITY_HEADERS.items():
            response.headers.setdefault(key, value)
        return response

    app.include_router(api_router, prefix="/api")
    app.include_router(ws_router)
    _mount_frontend(app, settings.static_dir)
    return app


def _mount_frontend(app: FastAPI, static_dir: Path) -> None:
    index = static_dir / "index.html"
    if not index.is_file():
        return
    assets = static_dir / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    root = static_dir.resolve()

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str) -> FileResponse:
        if path.startswith(("api/", "ws")):
            raise HTTPException(status_code=404)
        candidate = (static_dir / path).resolve()
        if path and candidate.is_file() and candidate.is_relative_to(root):
            return FileResponse(candidate)
        # Client-side routes: let the SPA router handle them; never cache the shell.
        return FileResponse(index, headers={"Cache-Control": "no-cache"})


app = create_app()
