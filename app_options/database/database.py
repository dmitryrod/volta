"""Database session and engine."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app_options.config import config
from app_options.database.models import Base
from app_options.database.repositories.candle_repository import CandleRepository
from app_options.database.repositories.snapshot_repository import SnapshotRepository

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    """Return singleton async engine."""
    global _engine
    if _engine is None:
        _engine = create_async_engine(config.db.url, echo=False, pool_pre_ping=True)
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    """Return singleton session factory."""
    global _sessionmaker
    if _sessionmaker is None:
        _sessionmaker = async_sessionmaker(bind=get_engine(), expire_on_commit=False)
    return _sessionmaker


class Database:
    """High-level database wrapper."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.snapshots = SnapshotRepository(session)
        self.candles = CandleRepository(session)

    @classmethod
    @asynccontextmanager
    async def session_context(cls) -> AsyncGenerator[Database]:
        """Yield Database with auto-commit on success."""
        sm = get_sessionmaker()
        async with sm() as session:
            db = cls(session)
            try:
                yield db
                await session.commit()
            except Exception:
                await session.rollback()
                raise


async def init_db() -> None:
    """Ensure metadata exists (migrations preferred in prod)."""
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
