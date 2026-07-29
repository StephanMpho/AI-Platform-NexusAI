from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from nexus.config import get_settings

_settings = get_settings()

engine = create_async_engine(
    _settings.database.url,
    pool_size=_settings.database.pool_size,
    pool_pre_ping=True,
    echo=_settings.database.echo,
)

sessionmaker = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency. One session per request, rolled back on error."""
    async with sessionmaker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
