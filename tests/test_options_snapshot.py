"""Tests for options multi-strike chain collector."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app_options.ingestor.collectors.options_snapshot import (
    ChainContract,
    OptionsSnapshotCollector,
    _collect_chain_rows,
    _default_otm_pair,
    _nearest_expiry,
    _parse_expiry_from_symbol,
    _ticker_ask_price,
    is_otm_call,
    is_otm_put,
    pick_default_call,
    pick_default_put,
)


def _eth_ticker(
    symbol: str,
    strike: float,
    opt_type: str,
    bid: str,
    ask: str,
    delivery_ms: int,
) -> dict:
    return {
        "symbol": symbol,
        "strikePrice": str(strike),
        "optionsType": opt_type,
        "bid1Price": bid,
        "ask1Price": ask,
        "deliveryTime": str(delivery_ms),
    }


def test_parse_expiry_from_symbol() -> None:
    exp = _parse_expiry_from_symbol("ETH-9SEP25-2500-C-USDT")
    assert exp == datetime(2025, 9, 9, 8, 0, tzinfo=timezone.utc)
    exp_far = _parse_expiry_from_symbol("ETH-25SEP26-2500-C-USDT")
    assert exp_far == datetime(2026, 9, 25, 8, 0, tzinfo=timezone.utc)


def test_ticker_ask_price_requires_ask1() -> None:
    assert _ticker_ask_price({"ask1Price": "12.5"}) == 12.5
    assert _ticker_ask_price({"bid1Price": "12.2", "ask1Price": "12.5"}) == 12.5
    assert _ticker_ask_price({"bid1Price": "12.2"}) is None
    assert _ticker_ask_price({"ask1Price": "0"}) is None
    assert _ticker_ask_price({"ask1Price": "-1"}) is None
    assert _ticker_ask_price({"markPrice": "12.0"}) is None


def test_collect_chain_rows_nearest_expiry_only() -> None:
    now = datetime(2025, 9, 8, 12, 0, tzinfo=timezone.utc)
    near_ms = int(datetime(2025, 9, 9, 8, 0, tzinfo=timezone.utc).timestamp() * 1000)
    far_ms = int(datetime(2026, 9, 25, 8, 0, tzinfo=timezone.utc).timestamp() * 1000)
    tickers = [
        _eth_ticker("ETH-9SEP25-2500-C-USDT", 2500, "Call", "12", "12.5", near_ms),
        _eth_ticker("ETH-25SEP26-2500-C-USDT", 2500, "Call", "60", "65", far_ms),
    ]
    rows, expiry = _collect_chain_rows(tickers, "ETH", now, "bybit")
    assert expiry == datetime(2025, 9, 9, 8, 0, tzinfo=timezone.utc)
    assert len(rows) == 1
    assert rows[0]["symbol"] == "ETH-9SEP25-2500-C-USDT"
    assert rows[0]["metric"] == "ask_price"
    assert rows[0]["value"] == 12.5


def test_collect_chain_rows_mixed_expiry_sources() -> None:
    """Symbol-only expiry (midnight) must match deliveryTime at 08:00 UTC."""
    now = datetime(2025, 9, 8, 12, 0, tzinfo=timezone.utc)
    near_ms = int(datetime(2025, 9, 9, 8, 0, tzinfo=timezone.utc).timestamp() * 1000)
    tickers = [
        _eth_ticker("ETH-9SEP25-2500-C-USDT", 2500, "Call", "12", "12.5", near_ms),
        {
            "symbol": "ETH-9SEP25-2510-P-USDT",
            "strikePrice": "2510",
            "optionsType": "Put",
            "bid1Price": "14",
            "ask1Price": "14.3",
        },
    ]
    rows, expiry = _collect_chain_rows(tickers, "ETH", now, "bybit")
    assert expiry == datetime(2025, 9, 9, 8, 0, tzinfo=timezone.utc)
    assert len(rows) == 2
    symbols = {r["symbol"] for r in rows}
    assert symbols == {"ETH-9SEP25-2500-C-USDT", "ETH-9SEP25-2510-P-USDT"}


def test_collect_chain_rows_skips_missing_ask() -> None:
    now = datetime(2025, 9, 8, 12, 0, tzinfo=timezone.utc)
    near_ms = int(datetime(2025, 9, 9, 8, 0, tzinfo=timezone.utc).timestamp() * 1000)
    tickers = [
        _eth_ticker("ETH-9SEP25-2500-C-USDT", 2500, "Call", "12", "", near_ms),
        _eth_ticker("ETH-9SEP25-2510-P-USDT", 2510, "Put", "14", "14.3", near_ms),
    ]
    rows, _ = _collect_chain_rows(tickers, "ETH", now, "bybit")
    assert len(rows) == 1
    assert rows[0]["symbol"] == "ETH-9SEP25-2510-P-USDT"


def test_collect_chain_rows_meta_json() -> None:
    now = datetime(2025, 9, 8, 12, 0, tzinfo=timezone.utc)
    near_ms = int(datetime(2025, 9, 9, 8, 0, tzinfo=timezone.utc).timestamp() * 1000)
    tickers = [_eth_ticker("ETH-9SEP25-2520-C-USDT", 2520, "Call", "12", "12.5", near_ms)]
    rows, _ = _collect_chain_rows(tickers, "ETH", now, "bybit")
    meta = rows[0]["meta_json"]
    assert meta["option_type"] == "call"
    assert meta["strike"] == 2520.0
    assert meta["symbol"] == "ETH-9SEP25-2520-C-USDT"
    assert "expiry" in meta


def test_hypothesis_a_otm_classification_spot_2513() -> None:
    assert is_otm_call(2513, 2513) is False
    assert is_otm_call(2520, 2513) is True
    assert is_otm_put(2510, 2513) is True
    assert is_otm_put(2513, 2513) is True


def test_pick_default_call_put_hypothesis_a() -> None:
    spot = 2513.0
    expiry = datetime(2025, 9, 9, 8, 0, tzinfo=timezone.utc)
    calls = [
        ChainContract("ETH-9SEP25-2513-C-USDT", 2513, "call", 10.0, expiry),
        ChainContract("ETH-9SEP25-2520-C-USDT", 2520, "call", 12.5, expiry),
    ]
    puts = [
        ChainContract("ETH-9SEP25-2510-P-USDT", 2510, "put", 14.0, expiry),
        ChainContract("ETH-9SEP25-2513-P-USDT", 2513, "put", 14.3, expiry),
    ]
    default_call = pick_default_call(calls, spot)
    default_put = pick_default_put(puts, spot)
    assert default_call is not None
    assert default_call.strike == 2520
    assert default_put is not None
    assert default_put.strike == 2513


def test_panel_reference_pair_uses_ask() -> None:
    now = datetime(2025, 9, 8, 12, 0, tzinfo=timezone.utc)
    near_ms = int(datetime(2025, 9, 9, 8, 0, tzinfo=timezone.utc).timestamp() * 1000)
    tickers = [
        _eth_ticker("ETH-9SEP25-2513-C-USDT", 2513, "Call", "10", "10.5", near_ms),
        _eth_ticker("ETH-9SEP25-2520-C-USDT", 2520, "Call", "12", "12.5", near_ms),
        _eth_ticker("ETH-9SEP25-2510-P-USDT", 2510, "Put", "14", "14.0", near_ms),
        _eth_ticker("ETH-9SEP25-2513-P-USDT", 2513, "Put", "14.2", "14.3", near_ms),
    ]
    rows, _ = _collect_chain_rows(tickers, "ETH", now, "bybit")
    call_sym, call_px, put_sym, put_px = _default_otm_pair(rows, 2513.0)
    assert call_sym == "ETH-9SEP25-2520-C-USDT"
    assert call_px == 12.5
    assert put_sym == "ETH-9SEP25-2513-P-USDT"
    assert put_px == 14.3


@pytest.mark.asyncio
async def test_collect_once_writes_multiple_instrument_rows() -> None:
    writer = MagicMock()
    writer.get_enabled_assets = AsyncMock(
        return_value=[MagicMock(base_asset="ETH", futures_symbol="ETHUSDT")]
    )
    writer.write_instruments = AsyncMock()
    writer.write_panel = AsyncMock()
    writer.purge_expired_options = AsyncMock(return_value=0)

    near_ms = int(datetime(2025, 9, 9, 8, 0, tzinfo=timezone.utc).timestamp() * 1000)
    tickers = [
        _eth_ticker("ETH-9SEP25-2520-C-USDT", 2520, "Call", "12", "12.5", near_ms),
        _eth_ticker("ETH-9SEP25-2510-P-USDT", 2510, "Put", "14", "14.3", near_ms),
    ]

    mock_client = MagicMock()
    mock_client.futures_last_price = AsyncMock(return_value={"ETHUSDT": 2513.0})
    mock_client.client.tickers = AsyncMock(return_value={"result": {"list": tickers}})

    collector = OptionsSnapshotCollector(writer)
    collector._is_running = True

    with patch.object(collector, "_client_context") as ctx:
        ctx.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        ctx.return_value.__aexit__ = AsyncMock(return_value=None)
        await collector._collect_once()

    writer.write_instruments.assert_called_once()
    rows = writer.write_instruments.call_args[0][0]
    assert len(rows) == 2
    assert all(r["metric"] == "ask_price" for r in rows)
    writer.write_panel.assert_called_once()
    panel = writer.write_panel.call_args[0][0]
    assert panel["call_price"] == 12.5
    assert panel["put_price"] == 14.3


def test_nearest_expiry_future_only() -> None:
    now = datetime(2025, 9, 8, 12, 0, tzinfo=timezone.utc)
    near_ms = int(datetime(2025, 9, 9, 8, 0, tzinfo=timezone.utc).timestamp() * 1000)
    tickers = [_eth_ticker("ETH-9SEP25-2500-C-USDT", 2500, "Call", "12", "12.5", near_ms)]
    nearest = _nearest_expiry(tickers, now)
    assert nearest == datetime(2025, 9, 9, 8, 0, tzinfo=timezone.utc)
