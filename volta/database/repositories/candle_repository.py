"""Futures candle persistence (closed bars only)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from volta.config.chart_intervals import MAX_CLOSED_CANDLES_PER_SERIES
from volta.database.models import FuturesCandle


class CandleRepository:
    """CRUD for futures_candles."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert_closed_candle(
        self,
        base_asset: str,
        interval: str,
        open_time: int,
        open_: float,
        high: float,
        low: float,
        close: float,
        volume: float | None = None,
    ) -> None:
        """Insert or update a closed candle."""
        stmt = pg_insert(FuturesCandle).values(
            base_asset=base_asset,
            interval=interval,
            open_time=open_time,
            open=open_,
            high=high,
            low=low,
            close=close,
            volume=volume,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["base_asset", "interval", "open_time"],
            set_={
                "open": stmt.excluded.open,
                "high": stmt.excluded.high,
                "low": stmt.excluded.low,
                "close": stmt.excluded.close,
                "volume": stmt.excluded.volume,
            },
        )
        await self._session.execute(stmt)

    async def bulk_upsert_closed(self, rows: list[dict[str, Any]]) -> None:
        """Bulk upsert closed candles."""
        for row in rows:
            await self.upsert_closed_candle(
                row["base_asset"],
                row["interval"],
                int(row["open_time"]),
                float(row["open"]),
                float(row["high"]),
                float(row["low"]),
                float(row["close"]),
                float(row["volume"]) if row.get("volume") is not None else None,
            )

    async def max_open_time(self, base_asset: str, interval: str) -> int | None:
        """Return latest closed candle open_time or None."""
        result = await self._session.execute(
            select(func.max(FuturesCandle.open_time)).where(
                FuturesCandle.base_asset == base_asset,
                FuturesCandle.interval == interval,
            )
        )
        value = result.scalar_one_or_none()
        return int(value) if value is not None else None

    async def list_candles(
        self,
        base_asset: str,
        interval: str,
        from_ts: int | None,
        to_ts: int | None,
        limit: int,
    ) -> tuple[list[dict[str, Any]], bool]:
        """List closed candles ascending by time. Returns (candles, has_more)."""
        clauses = [
            FuturesCandle.base_asset == base_asset,
            FuturesCandle.interval == interval,
        ]
        if from_ts is not None:
            clauses.append(FuturesCandle.open_time >= from_ts)
        if to_ts is not None:
            clauses.append(FuturesCandle.open_time <= to_ts)

        stmt = (
            select(FuturesCandle)
            .where(*clauses)
            .order_by(FuturesCandle.open_time.desc())
            .limit(limit + 1)
        )
        result = await self._session.execute(stmt)
        rows = list(result.scalars().all())
        has_more = len(rows) > limit
        rows = rows[:limit]
        candles = [
            {
                "time": int(r.open_time),
                "open": float(r.open),
                "high": float(r.high),
                "low": float(r.low),
                "close": float(r.close),
            }
            for r in reversed(rows)
        ]
        return candles, has_more

    async def prune_older_than(
        self,
        base_asset: str,
        interval: str,
        keep: int = MAX_CLOSED_CANDLES_PER_SERIES,
    ) -> int:
        """Delete oldest candles beyond keep most recent. Returns deleted count."""
        if keep <= 0:
            return 0
        sql = text(
            """
            DELETE FROM futures_candles
            WHERE base_asset = :base
              AND interval = :interval
              AND open_time < (
                SELECT open_time FROM futures_candles
                WHERE base_asset = :base AND interval = :interval
                ORDER BY open_time DESC
                OFFSET :keep LIMIT 1
              )
            """
        )
        result = await self._session.execute(
            sql,
            {"base": base_asset, "interval": interval, "keep": keep},
        )
        return int(result.rowcount or 0)

    async def count_candles(self, base_asset: str, interval: str) -> int:
        """Count stored closed candles for a series."""
        result = await self._session.execute(
            select(func.count())
            .select_from(FuturesCandle)
            .where(
                FuturesCandle.base_asset == base_asset,
                FuturesCandle.interval == interval,
            )
        )
        return int(result.scalar_one() or 0)
