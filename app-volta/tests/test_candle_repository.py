"""Tests for futures candle repository."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app_options.database.repositories.candle_repository import CandleRepository


@pytest.mark.asyncio
async def test_upsert_and_list_candles() -> None:
    session = MagicMock()
    session.execute = AsyncMock()
    repo = CandleRepository(session)
    await repo.upsert_closed_candle("ETH", "5m", 100, 10.0, 12.0, 9.0, 11.0, 1.5)

    row = MagicMock()
    row.open_time = 100
    row.open = 10.0
    row.high = 12.0
    row.low = 9.0
    row.close = 11.0
    result = MagicMock()
    result.scalars.return_value.all.return_value = [row]
    session.execute = AsyncMock(return_value=result)

    candles, has_more = await repo.list_candles("ETH", "5m", None, None, 100)
    assert len(candles) == 1
    assert candles[0]["time"] == 100
    assert candles[0]["high"] == 12.0
    assert has_more is False


@pytest.mark.asyncio
async def test_max_open_time_none_when_empty() -> None:
    session = MagicMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    session.execute = AsyncMock(return_value=result)
    repo = CandleRepository(session)
    assert await repo.max_open_time("ETH", "5m") is None
