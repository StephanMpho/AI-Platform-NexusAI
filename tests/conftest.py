from __future__ import annotations

import os
from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient

os.environ.setdefault("NEXUS_ENV", "local")
os.environ.setdefault("NEXUS_AUTH__DEV_BYPASS", "true")
os.environ.setdefault("NEXUS_TELEMETRY__ENABLED", "false")


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    from nexus.api.main import create_app

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
