"""Plausibility guards for chart price scales (futures right + options left).

Keep in sync with chart.js: isPlausibleLeftPriceRange / isPlausibleRightPriceRange /
isPersistablePriceRange / getLeftReferencePriceFromLayout.

Left scale shows option ask premiums (often tens–hundreds USD), not futures spot.
Use option-scale ref for left guards; futures ref is only for the right scale.
"""

from __future__ import annotations

from typing import Any

LEFT_SCALE_MAX_ABS_MULTIPLIER = 5.0
LEFT_SCALE_MAX_SPAN_MULTIPLIER = 4.0
LEFT_SCALE_MID_DEVIATION_FACTOR = 10.0
LEFT_SCALE_ABS_FALLBACK_MAX = 1_000_000.0
LEFT_SCALE_SPAN_FALLBACK_MAX = 1_000_000.0
RIGHT_SCALE_MAX_ABS_MULTIPLIER = 5.0
RIGHT_SCALE_MAX_SPAN_MULTIPLIER = 4.0
RIGHT_SCALE_MID_DEVIATION_FACTOR = 10.0
RIGHT_SCALE_ABS_FALLBACK_MAX = 1_000_000.0
RIGHT_SCALE_SPAN_FALLBACK_MAX = 1_000_000.0
PM_RANGE_MIN = -5.0
PM_RANGE_MAX = 105.0
PM_MIN_SPAN = 10.0


def is_valid_price_range(range_obj: dict[str, Any] | None) -> bool:
    if not range_obj:
        return False
    from_val = range_obj.get("from")
    to_val = range_obj.get("to")
    if not isinstance(from_val, (int, float)) or not isinstance(to_val, (int, float)):
        return False
    return bool(from_val == from_val and to_val == to_val)  # excludes NaN


def _is_plausible_price_range(
    range_obj: dict[str, float] | None,
    ref_price: float | None,
    abs_mult: float,
    span_mult: float,
    mid_factor: float,
    abs_fallback: float,
    span_fallback: float,
) -> bool:
    if not is_valid_price_range(range_obj):
        return False
    from_val = float(range_obj["from"])
    to_val = float(range_obj["to"])
    span = abs(to_val - from_val)
    if ref_price is not None and ref_price > 0:
        abs_max = ref_price * abs_mult
        max_span = ref_price * span_mult
        if abs(from_val) > abs_max or abs(to_val) > abs_max:
            return False
        if span > max_span:
            return False
        mid = (from_val + to_val) / 2.0
        if mid > ref_price * mid_factor or mid < ref_price / mid_factor:
            return False
        return True
    if max(abs(from_val), abs(to_val)) > abs_fallback:
        return False
    return span <= span_fallback


def get_left_reference_price_from_layout(
    layout: dict[str, object] | None,
) -> float | None:
    """Mid of saved left visibleRange (option premium scale), for restore/sanitize."""
    if not layout:
        return None
    price_scales = layout.get("priceScales")
    if not isinstance(price_scales, dict):
        return None
    left = price_scales.get("left")
    if not isinstance(left, dict):
        return None
    visible = left.get("visibleRange")
    if not is_valid_price_range(visible):
        return None
    mid = (float(visible["from"]) + float(visible["to"])) / 2.0
    return mid if mid > 0 else None


def is_plausible_left_price_range(
    range_obj: dict[str, float] | None,
    ref_price: float | None,
) -> bool:
    return _is_plausible_price_range(
        range_obj,
        ref_price,
        LEFT_SCALE_MAX_ABS_MULTIPLIER,
        LEFT_SCALE_MAX_SPAN_MULTIPLIER,
        LEFT_SCALE_MID_DEVIATION_FACTOR,
        LEFT_SCALE_ABS_FALLBACK_MAX,
        LEFT_SCALE_SPAN_FALLBACK_MAX,
    )


def is_plausible_right_price_range(
    range_obj: dict[str, float] | None,
    ref_price: float | None,
) -> bool:
    return _is_plausible_price_range(
        range_obj,
        ref_price,
        RIGHT_SCALE_MAX_ABS_MULTIPLIER,
        RIGHT_SCALE_MAX_SPAN_MULTIPLIER,
        RIGHT_SCALE_MID_DEVIATION_FACTOR,
        RIGHT_SCALE_ABS_FALLBACK_MAX,
        RIGHT_SCALE_SPAN_FALLBACK_MAX,
    )


def is_persistable_price_range(
    scale_id: str,
    range_obj: dict[str, float] | None,
    ref_price: float | None = None,
) -> bool:
    if not is_valid_price_range(range_obj):
        return False
    if scale_id == "left":
        return is_plausible_left_price_range(range_obj, ref_price)
    if scale_id == "right":
        return is_plausible_right_price_range(range_obj, ref_price)
    if scale_id == "pm":
        from_val = float(range_obj["from"])
        to_val = float(range_obj["to"])
        span = abs(to_val - from_val)
        return (
            from_val >= PM_RANGE_MIN
            and to_val <= PM_RANGE_MAX
            and span >= PM_MIN_SPAN
        )
    return True
