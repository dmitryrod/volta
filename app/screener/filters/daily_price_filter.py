from __future__ import annotations

from app.unicex.types import TickerDailyItem  # type: ignore[attr-defined]

from .abstract import Filter, FilterResult


class DailyPriceFilterResult(FilterResult):
    """Результат фильтра по изменению цены за сутки."""


class DailyPriceFilter(Filter):
    """Фильтр по изменению цены монеты за сутки."""

    @staticmethod
    def process(
        ticker_daily: TickerDailyItem,
        dp_min_pct: float | None,
        dp_max_pct: float | None,
    ) -> DailyPriceFilterResult:
        """Проверяет, что дневное изменение цены попадает в заданный диапазон."""
        change_pct: float = float(ticker_daily["p"])

        ok = True
        if dp_min_pct is not None and change_pct < dp_min_pct:
            ok = False
        if dp_max_pct is not None and change_pct > dp_max_pct:
            ok = False

        return DailyPriceFilterResult(
            ok=ok,
            metadata={
                "daily_price_change_pct": change_pct,
                "dp_min_pct": dp_min_pct,
                "dp_max_pct": dp_max_pct,
            },
        )

