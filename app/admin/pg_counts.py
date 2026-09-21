"""Быстрые оценки числа строк через pg_stat (PostgreSQL), с fallback на COUNT."""

from __future__ import annotations

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models.signal import SignalORM


async def signals_total_for_list_ui(session: AsyncSession) -> int:
    """Число строк `signals` для UI (пагинация, дашборд): сначала `n_live_tup`, иначе точный COUNT."""
    try:
        res = await session.execute(
            text(
                "SELECT n_live_tup FROM pg_stat_user_tables "
                "WHERE relname = 'signals' AND schemaname = current_schema()"
            )
        )
        row = res.first()
        if row and row[0] is not None and int(row[0]) > 0:
            return int(row[0])
    except Exception:
        pass
    total_scalar = await session.scalar(select(func.count()).select_from(SignalORM))
    return int(total_scalar or 0)


async def signals_total_with_source(session: AsyncSession) -> tuple[int, str]:
    """Возвращает (число строк signals, ``estimate`` | ``exact``)."""
    try:
        res = await session.execute(
            text(
                "SELECT n_live_tup FROM pg_stat_user_tables "
                "WHERE relname = 'signals' AND schemaname = current_schema()"
            )
        )
        row = res.first()
        if row and row[0] is not None and int(row[0]) > 0:
            return int(row[0]), "estimate"
    except Exception:
        pass
    total_scalar = await session.scalar(select(func.count()).select_from(SignalORM))
    return int(total_scalar or 0), "exact"
