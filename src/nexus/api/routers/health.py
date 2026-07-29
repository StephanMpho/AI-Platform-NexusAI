from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from nexus import __version__
from nexus.config import Settings, get_settings
from nexus.db.session import sessionmaker
from nexus.providers import get_registry
from nexus.schemas import HealthResponse

router = APIRouter(tags=["meta"])


@router.get("/health", response_model=HealthResponse)
async def health(settings: Annotated[Settings, Depends(get_settings)]) -> HealthResponse:
    """Reports configured providers by name, never their credentials.

    Degrades rather than failing when the database is down, so the endpoint still
    tells you something useful during an incident.
    """
    db_status = "unknown"
    try:
        async with sessionmaker() as session:  # type: AsyncSession
            await session.execute(text("SELECT 1"))
        db_status = "ok"
    except Exception as exc:  # noqa: BLE001
        db_status = f"unavailable: {type(exc).__name__}"

    return HealthResponse(
        status="ok" if db_status == "ok" else "degraded",
        version=__version__,
        environment=settings.env,
        database=db_status,
        providers=get_registry().available(),
    )
