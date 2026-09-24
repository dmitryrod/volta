"""Unit tests for chart price scale plausibility guards."""

from volta.chart_price_scale_guards import (
    get_left_reference_price_from_layout,
    is_persistable_price_range,
    is_plausible_left_price_range,
    is_plausible_right_price_range,
    is_valid_price_range,
)


def test_is_valid_price_range_rejects_nan_and_missing():
    assert is_valid_price_range(None) is False
    assert is_valid_price_range({"from": 1.0}) is False
    assert is_valid_price_range({"from": float("nan"), "to": 1.0}) is False


def test_plausible_left_range_near_option_premium():
    ref = 150.0
    ok = {"from": 80.0, "to": 220.0}
    assert is_plausible_left_price_range(ok, ref) is True
    assert is_persistable_price_range("left", ok, ref) is True


def test_plausible_left_rejects_billions():
    ref = 150.0
    poisoned = {"from": -6_000_000_000.0, "to": 13_000_000_000.0}
    assert is_plausible_left_price_range(poisoned, ref) is False
    assert is_persistable_price_range("left", poisoned, ref) is False


def test_plausible_left_rejects_futures_ref_for_option_premium():
    """Regression: futures ref (~2500) must not gate option premiums (~100-200)."""
    futures_ref = 2500.0
    option_range = {"from": 100.0, "to": 200.0}
    assert is_plausible_left_price_range(option_range, futures_ref) is False
    option_ref = 150.0
    assert is_plausible_left_price_range(option_range, option_ref) is True


def test_plausible_left_saved_range_valid_with_layout_mid_not_otm_live_ref():
    """Restore/sanitize must prefer layout mid; OTM last-point ref would drop ATM zoom."""
    saved_range = {"from": 100.0, "to": 200.0}
    layout_ref = 150.0
    otm_live_ref = 5.0
    assert is_plausible_left_price_range(saved_range, layout_ref) is True
    assert is_plausible_left_price_range(saved_range, otm_live_ref) is False


def test_get_left_reference_price_from_layout():
    layout = {
        "priceScales": {
            "left": {
                "autoScale": False,
                "visibleRange": {"from": 90.0, "to": 210.0},
            }
        }
    }
    assert get_left_reference_price_from_layout(layout) == 150.0
    assert get_left_reference_price_from_layout(None) is None


def test_plausible_right_range_near_eth_futures():
    ref = 2500.0
    ok = {"from": 2360.0, "to": 2570.0}
    assert is_plausible_right_price_range(ok, ref) is True
    assert is_persistable_price_range("right", ok, ref) is True


def test_plausible_right_range_near_btc_futures():
    ref = 77992.0
    ok = {"from": 77000.0, "to": 79000.0}
    assert is_plausible_right_price_range(ok, ref) is True
    assert is_persistable_price_range("right", ok, ref) is True


def test_plausible_right_rejects_billions():
    ref = 77992.0
    poisoned = {"from": -28_000_000_000.0, "to": 36_000_000_000.0}
    assert is_plausible_right_price_range(poisoned, ref) is False
    assert is_persistable_price_range("right", poisoned, ref) is False


def test_plausible_right_rejects_scientific_garbage():
    ref = 2456.0
    poisoned = {"from": 2.45609e30, "to": 3.850513516e30}
    assert is_plausible_right_price_range(poisoned, ref) is False
    assert is_persistable_price_range("right", poisoned, ref) is False


def test_pm_scale_bounds():
    assert is_persistable_price_range("pm", {"from": 0.0, "to": 100.0}) is True
    assert is_persistable_price_range("pm", {"from": -10.0, "to": 50.0}) is False
    assert is_persistable_price_range("pm", {"from": -0.55, "to": 0.55}) is False
