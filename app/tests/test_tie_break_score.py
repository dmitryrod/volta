"""Тесты ok_count и tie_break_score для режима «Тест»."""

from __future__ import annotations

from app.screener.test_mode_eval import (
    compute_ok_count_and_tie_score,
    enrich_fulfillment_and_score,
    _tie_margin_for_row,
)


def test_ok_count_two_filters() -> None:
    rows = [
        {"id": "dv", "ok": True, "current": {"daily_volume_usd": 2e6}, "thresholds": {"dv_min_usd": 1e6}},
        {"id": "dp", "ok": False, "current": {"daily_price_change_pct": 1.0}, "thresholds": {}},
        {"id": "vl", "ok": True, "current": {"multiplier": 3.0}, "thresholds": {"vl_min_multiplier": 2.0}},
    ]
    oc, ts = compute_ok_count_and_tie_score(rows)
    assert oc == 1
    assert ts >= 0


def test_ok_count_zero_rows() -> None:
    oc, ts = compute_ok_count_and_tie_score([])
    assert oc == 0
    assert ts == 0.0


def test_vl_margin_excess() -> None:
    m = _tie_margin_for_row(
        {
            "id": "vl",
            "ok": True,
            "current": {"multiplier": 4.0},
            "thresholds": {"vl_min_multiplier": 2.0},
        }
    )
    assert m is not None
    assert abs(m - 1.0) < 1e-6


def test_tie_margin_skips_not_ok() -> None:
    assert _tie_margin_for_row({"id": "vl", "ok": False, "current": {}, "thresholds": {}}) is None


def test_enrich_filter_score_signed_average() -> None:
    rows = [
        {
            "id": "dp",
            "ok": False,
            "current": {"daily_price_change_pct": 0.5},
            "thresholds": {"dp_min_pct": 1.0, "dp_max_pct": None},
        },
        {
            "id": "vl",
            "ok": True,
            "current": {"multiplier": 2.0},
            "thresholds": {"vl_min_multiplier": 2.0},
        },
    ]
    score = enrich_fulfillment_and_score(rows)
    assert rows[0]["filter_score"] == -0.5
    assert rows[1]["filter_score"] == 0.0
    assert score == -0.25


def test_enrich_excludes_dv_from_score() -> None:
    scoring = [
        {
            "id": "vl",
            "ok": True,
            "current": {"multiplier": 2.0},
            "thresholds": {"vl_min_multiplier": 2.0},
        },
    ]
    rows_low_dv = scoring + [
        {
            "id": "dv",
            "ok": True,
            "current": {"daily_volume_usd": 1_000_000.0},
            "thresholds": {"dv_min_usd": 100_000.0},
        },
    ]
    rows_high_dv = scoring + [
        {
            "id": "dv",
            "ok": False,
            "current": {"daily_volume_usd": 1_000.0},
            "thresholds": {"dv_min_usd": 100_000.0},
        },
    ]
    score_low = enrich_fulfillment_and_score(rows_low_dv)
    score_high = enrich_fulfillment_and_score(rows_high_dv)
    assert score_low == score_high == 0.0
    assert "filter_score" not in rows_low_dv[1]
    assert "filter_score" not in rows_high_dv[1]


def test_enrich_vl_strong_exceed_single_filter() -> None:
    rows = [
        {
            "id": "vl",
            "ok": True,
            "current": {"multiplier": 4.0},
            "thresholds": {"vl_min_multiplier": 2.0},
        },
    ]
    score = enrich_fulfillment_and_score(rows)
    assert rows[0]["filter_score"] == 1.0
    assert score == 1.0


def test_enrich_fulfillment_empty_rows() -> None:
    assert enrich_fulfillment_and_score([]) == 0.0
