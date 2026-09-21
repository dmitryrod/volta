"""Срабатывание фильтров Scanner (false→true) и fire_meta."""

from app.screener.consumer import (
    apply_scanner_filter_fire_edges,
    attach_fire_meta_to_test_filter_rows,
)


def test_rising_edge_sets_elapsed_zero_at_start() -> None:
    prev: dict[str, bool] = {}
    fire: dict[str, dict[str, object]] = {}
    rows = [{"id": "pd", "ok": True}]
    start_ts = 1000.0
    now_sec = 1000.0
    apply_scanner_filter_fire_edges(prev, fire, rows, start_ts, now_sec)
    assert fire["pd"]["fire_elapsed_ms"] == 0
    assert isinstance(fire["pd"]["fire_at"], str)
    attach_fire_meta_to_test_filter_rows(rows, fire)
    assert rows[0]["fire_meta"]["fire_elapsed_ms"] == 0


def test_staying_ok_does_not_change_fire() -> None:
    prev = {"pd": True}
    fire: dict[str, dict[str, object]] = {
        "pd": {"fire_at": "2020-01-01T00:00:00+00:00", "fire_elapsed_ms": 0}
    }
    rows = [{"id": "pd", "ok": True}]
    apply_scanner_filter_fire_edges(prev, fire, rows, 1000.0, 2000.0)
    assert fire["pd"]["fire_elapsed_ms"] == 0
    assert fire["pd"]["fire_at"] == "2020-01-01T00:00:00+00:00"


def test_second_rising_edge_updates_elapsed() -> None:
    prev: dict[str, bool] = {}
    fire: dict[str, dict[str, object]] = {}
    apply_scanner_filter_fire_edges(prev, fire, [{"id": "pd", "ok": True}], 1000.0, 1000.0)
    apply_scanner_filter_fire_edges(prev, fire, [{"id": "pd", "ok": False}], 1000.0, 1010.0)
    apply_scanner_filter_fire_edges(prev, fire, [{"id": "pd", "ok": True}], 1000.0, 1020.0)
    assert fire["pd"]["fire_elapsed_ms"] == 20_000
