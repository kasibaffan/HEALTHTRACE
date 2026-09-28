"""FastAPI app: startup/shutdown of the pipeline tasks (SPEC.md section 3)."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator, Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router as api_router
from app.api.ws import router as ws_router
from app.config import AppConfig, Settings, get_settings, load_config
from app.pipeline import Pipeline

logging.basicConfig(level=logging.INFO)


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

    app = FastAPI(title="MedGuard", lifespan=lifespan)
    app.state.pipeline = pipeline
    app.add_middleware(
        CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"]
    )
    app.include_router(api_router, prefix="/api")
    app.include_router(ws_router)
    return app


app = create_app()
