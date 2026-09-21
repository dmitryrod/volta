"""Пики показателей Scanner (накопление max по фильтрам)."""

from app.screener.test_mode_eval import (
    build_scanner_filter_max_list,
    extract_peak_metric_for_scanner_row,
)


def test_extract_pd_uses_abs_pct() -> None:
    fid, v = extract_peak_metric_for_scanner_row(
        {"id": "pd", "current": {"price_change_pct": -1.22}}
    )
    assert fid == "pd"
    assert v == 1.22


def test_extract_lq_prefers_pct() -> None:
    fid, v = extract_peak_metric_for_scanner_row(
        {
            "id": "lq",
            "current": {"lq_pct_of_daily_volume": 14.4, "amount_usdt": 1000.0},
        }
    )
    assert fid == "lq"
    assert v == 14.4


def test_build_max_list_order_matches_filters() -> None:
    peaks = {"pd": 1.0, "oi": 2.0}
    tf = [
        {"id": "oi", "title": "OI"},
        {"id": "pd", "title": "PD"},
    ]
    lst = build_scanner_filter_max_list(tf, peaks)
    assert [x["id"] for x in lst] == ["oi", "pd"]
    assert lst[0]["value"] == 2.0
