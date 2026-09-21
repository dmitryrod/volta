"""Tests for snapshot repository helpers."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app_options.database.repositories.snapshot_repository import (
    SnapshotRepository,
    _chain_flat_candles,
    _format_option_label,
)


def test_chain_flat_candles_links_open_to_previous_close() -> None:
    candles = [
        {"time": 100, "open": 10.0, "high": 12.0, "low": 9.0, "close": 11.0},
        {"time": 200, "open": 11.5, "high": 11.5, "low": 11.5, "close": 11.5},
        {"time": 300, "open": 12.0, "high": 12.0, "low": 12.0, "close": 12.0},
    ]
    result = _chain_flat_candles(candles)
    assert result[0] == candles[0]
    assert result[1]["open"] == 11.0
    assert result[1]["high"] == 11.5
    assert result[1]["low"] == 11.0
    assert result[1]["close"] == 11.5
    assert result[2]["open"] == 11.5
    assert result[2]["high"] == 12.0
    assert result[2]["low"] == 11.5
    assert result[2]["close"] == 12.0


def test_chain_flat_candles_returns_empty_for_empty_input() -> None:
    assert _chain_flat_candles([]) == []


def test_chain_flat_candles_preserves_non_flat_bucket() -> None:
    candles = [
        {"time": 100, "open": 10.0, "high": 12.0, "low": 9.0, "close": 11.0},
        {"time": 200, "open": 11.0, "high": 13.0, "low": 10.5, "close": 12.5},
    ]
    result = _chain_flat_candles(candles)
    assert result[1]["open"] == 11.0
    assert result[1]["high"] == 13.0
    assert result[1]["low"] == 10.5
    assert result[1]["close"] == 12.5


def test_chain_flat_candles_preserves_bucket_high_low() -> None:
    candles = [
        {"time": 100, "open": 10.0, "high": 12.0, "low": 9.0, "close": 10.5},
    ]
    result = _chain_flat_candles(candles)
    assert result[0]["high"] == 12.0
    assert result[0]["low"] == 9.0
    assert result[0]["open"] == 10.0
    assert result[0]["close"] == 10.5


def test_format_option_label() -> None:
    assert _format_option_label(2520, "call") == "$2,520 C"
    assert _format_option_label(2510, "put") == "$2,510 P"


@pytest.mark.asyncio
async def test_aggregate_option_series_empty_symbols() -> None:
    repo = SnapshotRepository(MagicMock())
    series, expiry, has_more = await repo.aggregate_option_series(
        "ETH", [], "5m", None, None, 100
    )
    assert series == []
    assert expiry is None
    assert has_more is False


@pytest.mark.asyncio
async def test_aggregate_option_series_groups_by_symbol() -> None:
    session = MagicMock()
    result = MagicMock()
    result.mappings.return_value.all.return_value = [
        {
            "symbol": "ETH-9SEP25-2520-C-USDT",
            "bucket_unix": 100,
            "value": 12.0,
            "meta_json": {
                "strike": 2520,
                "option_type": "call",
                "expiry": "2025-09-09T08:00:00+00:00",
            },
        },
        {
            "symbol": "ETH-9SEP25-2510-P-USDT",
            "bucket_unix": 100,
            "value": 14.0,
            "meta_json": {
                "strike": 2510,
                "option_type": "put",
                "expiry": "2025-09-09T08:00:00+00:00",
            },
        },
    ]
    session.execute = AsyncMock(return_value=result)
    repo = SnapshotRepository(session)
    series, expiry, _ = await repo.aggregate_option_series(
        "ETH",
        ["ETH-9SEP25-2520-C-USDT", "ETH-9SEP25-2510-P-USDT"],
        "5m",
        None,
        None,
        100,
    )
    assert len(series) == 2
    assert series[0]["option_type"] == "call"
    assert series[1]["option_type"] == "put"
    assert expiry == "2025-09-09T08:00:00+00:00"


@pytest.mark.asyncio
async def test_get_options_chain_latest_per_symbol() -> None:
    session = MagicMock()
    result = MagicMock()
    result.mappings.return_value.all.return_value = [
        {
            "symbol": "ETH-9SEP25-2520-C-USDT",
            "value": 12.5,
            "meta_json": {
                "strike": 2520,
                "option_type": "call",
                "expiry": "2025-09-09T08:00:00+00:00",
            },
        },
        {
            "symbol": "ETH-9SEP25-2510-P-USDT",
            "value": 14.3,
            "meta_json": {
                "strike": 2510,
                "option_type": "put",
                "expiry": "2025-09-09T08:00:00+00:00",
            },
        },
    ]
    session.execute = AsyncMock(return_value=result)
    repo = SnapshotRepository(session)
    panel = MagicMock()
    panel.futures_price = 2513.0
    repo.get_latest_panel = AsyncMock(return_value=panel)
    chain = await repo.get_options_chain("ETH")
    assert chain["expiry"] == "2025-09-09T08:00:00+00:00"
    assert len(chain["calls"]) == 1
    assert len(chain["puts"]) == 1
    assert chain["calls"][0]["otm"] is True
    assert chain["puts"][0]["otm"] is True


@pytest.mark.asyncio
async def test_get_options_chain_otm_false_when_no_spot() -> None:
    session = MagicMock()
    result = MagicMock()
    result.mappings.return_value.all.return_value = [
        {
            "symbol": "ETH-9SEP25-2520-C-USDT",
            "value": 12.5,
            "meta_json": {
                "strike": 2520,
                "option_type": "call",
                "expiry": "2025-09-09T08:00:00+00:00",
            },
        },
    ]
    session.execute = AsyncMock(return_value=result)
    repo = SnapshotRepository(session)
    repo.get_latest_panel = AsyncMock(return_value=None)
    chain = await repo.get_options_chain("ETH")
    assert chain["spot"] is None
    assert chain["calls"][0]["otm"] is False


@pytest.mark.asyncio
async def test_aggregate_polymarket_series_empty_when_no_event_slug() -> None:
    session = MagicMock()
    repo = SnapshotRepository(session)
    asset = MagicMock()
    asset.polymarket_event_slug = None
    asset.polymarket_event_url = None
    repo.get_asset_config = AsyncMock(return_value=asset)

    series, slug, url, has_more = await repo.aggregate_polymarket_series(
        "BTC", "5m", None, None, 100
    )

    assert series == []
    assert slug is None
    assert url is None
    assert has_more is False
    session.execute.assert_not_called()


@pytest.mark.asyncio
async def test_aggregate_polymarket_series_filters_by_event_slug() -> None:
    session = MagicMock()
    result = MagicMock()
    result.mappings.return_value.all.return_value = [
        {
            "market_id": "m1",
            "bucket_unix": 100,
            "value": 55.0,
            "question": "Will BTC hit $100k?",
            "meta_json": {"strike": 100000, "event_slug": "btc-100k"},
        },
    ]
    session.execute = AsyncMock(return_value=result)
    repo = SnapshotRepository(session)
    asset = MagicMock()
    asset.polymarket_event_slug = "btc-100k"
    asset.polymarket_event_url = "https://polymarket.com/event/btc-100k"
    repo.get_asset_config = AsyncMock(return_value=asset)

    repo.get_polymarket_event = AsyncMock(return_value=None)
    series, slug, url, has_more = await repo.aggregate_polymarket_series(
        "BTC", "5m", None, None, 100, "btc-100k"
    )

    assert len(series) == 1
    assert series[0]["market_id"] == "m1"
    assert slug == "btc-100k"
    assert url == "https://polymarket.com/event/btc-100k"
    assert has_more is False
    session.execute.assert_awaited_once()
    sql_text = str(session.execute.await_args.args[0].text)
    assert "meta_json->>'event_slug' = :event_slug" in sql_text
    assert "PARTITION BY market_id" in sql_text
    assert session.execute.await_args.args[1]["event_slug"] == "btc-100k"


@pytest.mark.asyncio
async def test_get_chart_batch_passes_from_ts_to_aggregators() -> None:
    session = MagicMock()
    repo = SnapshotRepository(session)
    repo.get_futures_chart_candles = AsyncMock(return_value=([], False))
    repo.aggregate_option_series = AsyncMock(return_value=([], None, False))
    repo.aggregate_polymarket_series = AsyncMock(
        return_value=([], None, None, False)
    )
    await repo.get_chart_batch("ETH", "5m", 1725800000, None, 100, [])
    repo.get_futures_chart_candles.assert_awaited_once_with(
        "ETH", "5m", 1725800000, None, 100
    )
    repo.aggregate_option_series.assert_awaited_once_with(
        "ETH", [], "5m", 1725800000, None, 100
    )
    repo.aggregate_polymarket_series.assert_awaited_once_with(
        "ETH", "5m", 1725800000, None, 100, None
    )


@pytest.mark.asyncio
async def test_purge_expired_polymarket_deletes_catalog_and_snapshots() -> None:
    session = MagicMock()
    now = datetime(2026, 9, 11, 12, 0, 0, tzinfo=timezone.utc)
    expired_result = MagicMock()
    expired_result.all.return_value = [("ETH", "old-event")]
    snap_result = MagicMock()
    snap_result.rowcount = 3
    cat_result = MagicMock()
    cat_result.rowcount = 1
    session.execute = AsyncMock(side_effect=[expired_result, snap_result, cat_result])
    repo = SnapshotRepository(session)

    catalog_deleted, snap_deleted = await repo.purge_expired_polymarket(now, 24)

    assert catalog_deleted == 1
    assert snap_deleted == 3
    assert session.execute.await_count == 3


@pytest.mark.asyncio
async def test_purge_expired_polymarket_noop_when_none_expired() -> None:
    session = MagicMock()
    expired_result = MagicMock()
    expired_result.all.return_value = []
    session.execute = AsyncMock(return_value=expired_result)
    repo = SnapshotRepository(session)
    now = datetime(2026, 9, 11, 12, 0, 0, tzinfo=timezone.utc)

    catalog_deleted, snap_deleted = await repo.purge_expired_polymarket(now, 24)

    assert catalog_deleted == 0
    assert snap_deleted == 0
    session.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_chart_batch_options_shape() -> None:
    session = MagicMock()
    repo = SnapshotRepository(session)
    repo.get_futures_chart_candles = AsyncMock(return_value=([], False))
    repo.aggregate_option_series = AsyncMock(return_value=([], None, False))
    repo.aggregate_polymarket_series = AsyncMock(
        return_value=([], None, None, False)
    )
    batch = await repo.get_chart_batch("ETH", "5m", None, None, 100, [])
    assert "call" not in batch
    assert "put" not in batch
    assert "options" in batch
    assert batch["options"]["series"] == []
