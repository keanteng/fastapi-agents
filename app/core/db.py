from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings


class Base(DeclarativeBase):
    """Shared declarative base for all slice ORM models."""


_engine: AsyncEngine | None = None
_session_maker: async_sessionmaker[AsyncSession] | None = None


def _build_engine(url: str) -> AsyncEngine:
    if url.startswith("sqlite"):
        return create_async_engine(url, echo=settings.db_echo, future=True)
    return create_async_engine(
        url,
        echo=settings.db_echo,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        future=True,
    )


def init_db(url: str | None = None) -> None:
    """Create the global engine + session maker. Idempotent.

    Tests pass an explicit ``url`` (an in-memory SQLite URL) and call this
    before patching the session maker.
    """
    global _engine, _session_maker
    if _engine is None:
        _engine = _build_engine(url or settings.database_url)
        _session_maker = async_sessionmaker(_engine, expire_on_commit=False)


async def dispose_db() -> None:
    """Dispose the global engine (called on app shutdown)."""
    global _engine, _session_maker
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _session_maker = None


def get_session_maker() -> async_sessionmaker[AsyncSession]:
    if _session_maker is None:
        init_db()
    assert _session_maker is not None  # noqa: S101 -- for type checkers
    return _session_maker


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding a per-request ``AsyncSession``."""
    factory = get_session_maker()
    async with factory() as session:
        yield session
