from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from nexus import __version__
from nexus.api.routers import api_keys, auth, chat, health
from nexus.config import get_settings
from nexus.telemetry import setup_telemetry

logger = logging.getLogger("nexus")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    settings.validate_for_env()  # fail fast rather than surprising us later
    logging.basicConfig(level=settings.log_level)
    setup_telemetry(settings)
    logger.info("nexus %s starting in %s", __version__, settings.env)
    yield
    logger.info("nexus shutting down")


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="NexusAI",
        version=__version__,
        description="Governed AI gateway, knowledge hub, evaluation and agent platform",
        lifespan=lifespan,
    )

    # TODO(GOV-004): exact origin allow-list from configuration, never a wildcard
    #                with credentials, and the security header middleware.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000"] if settings.env == "local" else [],
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization", "Idempotency-Key"],
    )

    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(api_keys.router)
    app.include_router(chat.router)

    @app.get("/metrics", include_in_schema=False)
    async def metrics() -> PlainTextResponse:
        return PlainTextResponse(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    return app


app = create_app()
