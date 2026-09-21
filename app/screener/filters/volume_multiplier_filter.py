from __future__ import annotations

import time

from app.unicex.types import KlineDict, TickerDailyItem  # type: ignore[attr-defined]

from .abstract import Filter, FilterResult


class VolumeMultiplierFilterResult(FilterResult):
    """Результат фильтра по множителю объёма."""

    multiplier: float | None = None


class VolumeMultiplierFilter(Filter):
    """Фильтр по аномальному объёму за короткий интервал."""

    @staticmethod
    def process(
        klines: list[KlineDict],
        ticker_daily: TickerDailyItem,
        vl_interval_sec: int | None,
        vl_min_multiplier: float | None,
    ) -> VolumeMultiplierFilterResult:
        """Считает множитель объёма и сверяет с порогом."""
        if not vl_interval_sec or vl_min_multiplier is None:
            return VolumeMultiplierFilterResult(ok=False, metadata={})

        if not klines:
            return VolumeMultiplierFilterResult(ok=False, metadata={"reason": "no_klines"})

        now_ms = int(time.time() * 1000)
        threshold_ms = now_ms - vl_interval_sec * 1000

        window = [k for k in klines if k["t"] >= threshold_ms]
        if not window:
            return VolumeMultiplierFilterResult(ok=False, metadata={"reason": "empty_window"})

        # объём за интервал в quote (q)
        interval_quote_volume = sum(float(k["q"]) for k in window)
        daily_quote_volume = float(ticker_daily["q"])
        if daily_quote_volume <= 0:
            return VolumeMultiplierFilterResult(
                ok=False,
                metadata={
                    "reason": "zero_daily_volume",
                    "daily_quote_volume": daily_quote_volume,
                },
            )

        # формула из README:
        # (объём за интервал / длительность интервала) / (суточный объём / 86400)
        per_sec_interval = interval_quote_volume / vl_interval_sec
        per_sec_daily = daily_quote_volume / 86400.0
        multiplier = per_sec_interval / per_sec_daily if per_sec_daily > 0 else 0.0

        ok = multiplier >= vl_min_multiplier

        result = VolumeMultiplierFilterResult(
            ok=ok,
            metadata={
                "multiplier": multiplier,
                "interval_quote_volume": interval_quote_volume,
                "daily_quote_volume": daily_quote_volume,
                "vl_interval_sec": vl_interval_sec,
                "vl_min_multiplier": vl_min_multiplier,
            },
        )
        result.multiplier = multiplier
        return result

