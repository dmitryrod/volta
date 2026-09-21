"""Контракт API сигналов для UI (режим БД + card_snapshot)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import patch

from app.admin import (
    dedupe_signal_log_items_newest_first,
    parse_signals_log_line,
    signal_orm_row_to_dict,
)
from app.database.models.signal import SignalORM


def test_signal_orm_row_to_dict_render_as_scanner_with_snapshot() -> None:
    snap = {
        "mode": "test",
        "symbol": "BTCUSDT",
        "telegram_text": "body",
        "test_filters": [{"id": "pd", "ok": True}],
        "scanner_duration_at_trigger_ms": 125000,
        "scanner_snapshot_frozen": True,
    }
    row = SignalORM(
        screener_name="S",
        screener_id=1,
        exchange="bybit",
        market_type="futures",
        symbol="BTCUSDT",
        telegram_text="body",
        telegram_ok=True,
        error=None,
        tracking_id="tid-abc",
        card_snapshot_json=json.dumps(snap, ensure_ascii=False),
    )
    row.id = 100
    row.created_at = datetime(2026, 4, 1, 12, 0, 0, tzinfo=timezone.utc)

    with patch("app.admin.get_cmc_rank_for_symbol", return_value=10):
        d = signal_orm_row_to_dict(row)

    assert d["render_as_scanner"] is True
    assert d["tracking_id"] == "tid-abc"
    assert d["stat_href"] == "/admin/analytics/stat-btcusdt-tid-abc"
    assert d["card_snapshot"]["scanner_duration_at_trigger_ms"] == 125000
    assert d["card_snapshot"]["scanner_snapshot_frozen"] is True
    assert d["cmc_rank"] == 10


def test_signal_orm_row_to_dict_no_snapshot_not_scanner_layout() -> None:
    row = SignalORM(
        screener_name="S",
        screener_id=1,
        exchange="bybit",
        market_type="futures",
        symbol="ETHUSDT",
        telegram_text="x",
        telegram_ok=True,
        error=None,
        tracking_id=None,
        card_snapshot_json=None,
    )
    row.id = 1
    row.created_at = datetime(2026, 4, 1, tzinfo=timezone.utc)

    with patch("app.admin.get_cmc_rank_for_symbol", return_value=None):
        d = signal_orm_row_to_dict(row)

    assert d["render_as_scanner"] is False
    assert d["card_snapshot"] is None


def test_parse_signals_log_line_includes_card_snapshot_and_stat() -> None:
    snap = {
        "symbol": "BTCUSDT",
        "test_filters": [{"id": "pd", "ok": True}],
        "scanner_snapshot_frozen": True,
    }
    line = "2026-04-28T10:00:00+03:00\t" + json.dumps(
        {
            "kind": "signal",
            "ts_moscow": "2026-04-28T10:00:00+03:00",
            "screener_name": "S",
            "screener_id": 1,
            "exchange": "bybit",
            "market_type": "futures",
            "symbol": "BTCUSDT",
            "telegram_text": "x",
            "telegram_ok": True,
            "card_snapshot": snap,
            "tracking_id": "tid-log-1",
        },
        ensure_ascii=False,
    )
    with patch("app.admin.get_cmc_rank_for_symbol", return_value=7):
        d = parse_signals_log_line(line)
    assert d is not None
    assert d["render_as_scanner"] is True
    assert d["card_snapshot"] == snap
    assert d["tracking_id"] == "tid-log-1"
    assert d["stat_href"] == "/admin/analytics/stat-btcusdt-tid-log-1"
    assert d["cmc_rank"] == 7


def test_dedupe_signal_log_items_keeps_newest_per_tracking_id() -> None:
    """Повторные строки лога с тем же tracking_id — одна карточка (новая первой)."""
    newer = {
        "id": "2026-04-28T12:00:02+03:00",
        "symbol": "ZBTUSDT",
        "exchange": "BYBIT",
        "market_type": "FUTURES",
        "tracking_id": "71afe4b212124278a32f",
        "created_at": "2026-04-28T12:00:02+03:00",
    }
    older = {
        "id": "2026-04-28T12:00:01+03:00",
        "symbol": "ZBTUSDT",
        "exchange": "BYBIT",
        "market_type": "FUTURES",
        "tracking_id": "71afe4b212124278a32f",
        "created_at": "2026-04-28T12:00:01+03:00",
    }
    other_tid = {
        "id": "2026-04-28T12:00:03+03:00",
        "symbol": "ZBTUSDT",
        "exchange": "BYBIT",
        "market_type": "FUTURES",
        "tracking_id": "3d8764ab2dad48159eaa",
        "created_at": "2026-04-28T12:00:03+03:00",
    }
    items = [newer, older, other_tid]
    out = dedupe_signal_log_items_newest_first(items)
    assert len(out) == 2
    assert out[0]["id"] == newer["id"]
    assert out[1]["id"] == other_tid["id"]


def test_dedupe_signal_log_items_no_tracking_keeps_all() -> None:
    a = {"id": "a", "symbol": "X", "exchange": "E", "market_type": "M", "tracking_id": None}
    b = {"id": "b", "symbol": "X", "exchange": "E", "market_type": "M", "tracking_id": None}
    out = dedupe_signal_log_items_newest_first([a, b])
    assert out == [a, b]


def test_parse_signals_log_line_legacy_no_snapshot() -> None:
    line = "2026-04-28T10:00:00+03:00\t" + json.dumps(
        {
            "kind": "signal",
            "ts_moscow": "2026-04-28T10:00:00+03:00",
            "screener_name": "S",
            "screener_id": 1,
            "exchange": "bybit",
            "market_type": "futures",
            "symbol": "ETHUSDT",
            "telegram_text": "old",
            "telegram_ok": True,
        },
        ensure_ascii=False,
    )
    with patch("app.admin.get_cmc_rank_for_symbol", return_value=None):
        d = parse_signals_log_line(line)
    assert d is not None
    assert d["render_as_scanner"] is False
    assert d["card_snapshot"] is None
    assert d["tracking_id"] is None
    assert d["stat_href"] is None
