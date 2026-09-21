"""Тесты Scanner Analytics: runtime helpers и контракт JSONL sample."""

from __future__ import annotations

import time

import pytest

from app.screener import scanner_runtime


@pytest.fixture(autouse=True)
def _reset_scanner_runtime_state():
    """Изолировать глобальные кэши сессий между тестами."""
    scanner_runtime._sessions.clear()  # noqa: SLF001
    scanner_runtime._pending_signal_snapshots.clear()  # noqa: SLF001
    scanner_runtime._manual_close_ids.clear()  # noqa: SLF001
    scanner_runtime._cooldown_until.clear()  # noqa: SLF001
    yield
    scanner_runtime._sessions.clear()  # noqa: SLF001
    scanner_runtime._pending_signal_snapshots.clear()  # noqa: SLF001
    scanner_runtime._manual_close_ids.clear()  # noqa: SLF001
    scanner_runtime._cooldown_until.clear()  # noqa: SLF001


def test_stat_url_path_slug_and_tracking() -> None:
    assert scanner_runtime.stat_url_path("BTCUSDT", "tid-1") == (
        "/admin/analytics/stat-btcusdt-tid-1"
    )
    assert scanner_runtime.stat_url_path("BTC/USDT", "tid-1") == (
        "/admin/analytics/stat-btcusdt-tid-1"
    )


def test_parse_stat_page_path_split_first_hyphen() -> None:
    assert scanner_runtime.parse_stat_page_path("stat-btcusdt-tid-1") == ("btcusdt", "tid-1")
    assert scanner_runtime.parse_stat_page_path(
        "stat-btcusdt-9b27ef45-2f0f-4419-bc72"
    ) == ("btcusdt", "9b27ef45-2f0f-4419-bc72")
    assert scanner_runtime.parse_stat_page_path("stat-zkusdt-c3b6fbbe62a9475db600") == (
        "zkusdt",
        "c3b6fbbe62a9475db600",
    )
    assert scanner_runtime.parse_stat_page_path("analytics") is None
    assert scanner_runtime.parse_stat_page_path("stat-nohyphen") is None


def test_is_posttracking_false_without_session() -> None:
    assert scanner_runtime.is_posttracking(1, "ETHUSDT") is False


def test_is_posttracking_true_when_triggered_and_window_open() -> None:
    st = scanner_runtime._SessionState(  # noqa: SLF001
        tracking_id="abc",
        entered_monotonic=time.monotonic(),
        triggered=True,
        posttracking_until=time.time() + 3600.0,
    )
    scanner_runtime._sessions[(7, "SOLUSDT")] = st  # noqa: SLF001
    assert scanner_runtime.is_posttracking(7, "SOLUSDT") is True


def test_session_is_triggered() -> None:
    assert scanner_runtime.session_is_triggered(1, "XXXUSDT") is False
    st = scanner_runtime._SessionState(  # noqa: SLF001
        tracking_id="tid1",
        entered_monotonic=0.0,
        triggered=True,
        posttracking_until=None,
    )
    scanner_runtime._sessions[(3, "AAAUSDT")] = st  # noqa: SLF001
    assert scanner_runtime.session_is_triggered(3, "AAAUSDT") is True


def test_build_sample_line_kind_and_filters() -> None:
    payload = {
        "symbol": "X",
        "exchange": "bybit",
        "market_type": "futures",
        "screener_id": 3,
        "screener_name": "S",
        "score": 1.5,
        "last_price": 1.2345,
        "ok_count": 2,
        "test_filters": [{"id": "pd", "ok": True, "title": "P", "current": {}, "thresholds": {}}],
        "scanner_filter_max_list": [],
        "scanner_tracked_since": None,
    }
    line = scanner_runtime.build_sample_line(
        payload,
        tracking_id="tid",
        phase="active",
        seq=1,
        reason="heartbeat",
    )
    assert line["kind"] == "sample"
    assert line["tracking_id"] == "tid"
    assert line["phase"] == "active"
    assert line["seq"] == 1
    assert line["score"] == 1.5
    assert line["last_price"] == 1.2345
    assert line["all_filters_ok"] is True


def test_attach_tracking_meta_adds_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fake_ensure(
        screener_id: int,
        symbol: str,
        screener_name: str,
        exchange: str,
        market_type: str,
    ):
        return scanner_runtime._SessionState(  # noqa: SLF001
            tracking_id="tid-fixed",
            entered_monotonic=0.0,
        )

    monkeypatch.setattr(scanner_runtime, "_ensure_session", _fake_ensure)
    payload: dict = {}
    scanner_runtime.attach_tracking_meta(
        payload,
        screener_id=1,
        symbol="AA",
        screener_name="N",
        exchange="bybit",
        market_type="futures",
    )
    assert payload["tracking_id"] == "tid-fixed"
    assert payload["stat_href"] == "/admin/analytics/stat-aa-tid-fixed"


def test_analytics_stat_template_path_not_cwd_relative() -> None:
    """Регрессия: Admin с templates_dir=app/admin/templates ломался при cwd внутри app/."""
    from pathlib import Path

    tpl_dir = Path(__file__).resolve().parents[1] / "admin" / "templates"
    assert (tpl_dir / "analytics_stat.html").is_file()
