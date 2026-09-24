"""Tests for KlineHub live merge and SSE payload."""

import pytest

from volta.ingestor.kline_hub import KlineHub, LiveCandle, current_bucket_open_time


def test_merge_series_with_live_appends_new_bar() -> None:
    hub = KlineHub()
    hub.set_live(
        "ETH",
        "5m",
        LiveCandle(time=200, open=10.0, high=11.0, low=9.5, close=10.5),
    )
    closed = [{"time": 100, "open": 9.0, "high": 10.0, "low": 8.0, "close": 9.5}]
    merged = hub.merge_series_with_live(closed, "ETH", "5m")
    assert len(merged) == 2
    assert merged[-1]["time"] == 200
    assert merged[-1]["close"] == 10.5


def test_merge_series_with_live_replaces_same_time() -> None:
    hub = KlineHub()
    hub.set_live(
        "ETH",
        "5m",
        LiveCandle(time=100, open=9.0, high=10.5, low=8.5, close=10.0),
    )
    closed = [{"time": 100, "open": 9.0, "high": 9.5, "low": 8.0, "close": 9.0}]
    merged = hub.merge_series_with_live(closed, "ETH", "5m")
    assert len(merged) == 1
    assert merged[0]["high"] == 10.5


def test_current_bucket_open_time_aligns() -> None:
    ts = 1_700_000_300
    assert current_bucket_open_time("5m", ts) == 1_700_000_100


@pytest.mark.asyncio
async def test_apply_ws_update_broadcasts_to_subscriber() -> None:
    hub = KlineHub()
    sub = hub.subscribe("ETH", "5m")
    await hub.apply_ws_update("ETH", "5m", 100, 1.0, 2.0, 0.5, 1.5, 10.0, False)
    payload = sub.queue.get_nowait()
    assert payload["type"] == "kline"
    assert payload["candle"]["close"] == 1.5
    hub.unsubscribe(sub)
