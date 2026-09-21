from __future__ import annotations

from .abstract import Filter, FilterResult


class FundingRateFilterResult(FilterResult):
    """Результат фильтра по ставке финансирования."""


class FundingRateFilter(Filter):
    """Фильтр по ставке финансирования."""

    @staticmethod
    def process(
        funding_rate: float,
        fr_min_value_pct: float | None,
        fr_max_value_pct: float | None,
    ) -> FundingRateFilterResult:
        """Проверяет, что ставка финансирования в заданном диапазоне."""
        value = float(funding_rate)

        ok = True
        if fr_min_value_pct is not None and value < fr_min_value_pct:
            ok = False
        if fr_max_value_pct is not None and value > fr_max_value_pct:
            ok = False

        return FundingRateFilterResult(
            ok=ok,
            metadata={
                "funding_rate_pct": value,
                "fr_min_value_pct": fr_min_value_pct,
                "fr_max_value_pct": fr_max_value_pct,
            },
        )

