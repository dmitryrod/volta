"""Tests for Polymarket strike selection."""

from app_options.polymarket.gamma_client import parse_event_end_date, select_strike_markets


def test_parse_event_end_date() -> None:
    assert parse_event_end_date({"endDate": "2026-09-09T16:00:00Z"}) == "2026-09-09T16:00:00Z"
    assert parse_event_end_date({}) is None
    assert parse_event_end_date({"endDate": ""}) is None


def _market(strike: str, market_id: str) -> dict:
    return {
        "id": market_id,
        "active": True,
        "closed": False,
        "groupItemTitle": strike,
        "question": f"Ethereum above {strike}?",
        "outcomePrices": '["0.5","0.5"]',
    }


def test_select_three_below_and_above_spot() -> None:
    markets = [
        _market("2,100", "1"),
        _market("2,200", "2"),
        _market("2,300", "3"),
        _market("2,400", "4"),
        _market("2,500", "5"),
        _market("2,600", "6"),
        _market("2,700", "7"),
        _market("2,800", "8"),
        _market("2,900", "9"),
    ]
    selected = select_strike_markets(markets, spot_price=2501.0)
    strikes = [s.strike for s in selected]
    assert strikes == [2300.0, 2400.0, 2500.0, 2600.0, 2700.0, 2800.0]


def test_skips_inactive_markets() -> None:
    markets = [
        _market("2,400", "4"),
        {**_market("2,500", "5"), "active": False},
        _market("2,600", "6"),
    ]
    selected = select_strike_markets(markets, spot_price=2500.0, below_count=1, above_count=1)
    strikes = [s.strike for s in selected]
    assert strikes == [2400.0, 2600.0]
