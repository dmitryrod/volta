from __future__ import annotations

from app.unicex.types import TickerDailyItem  # type: ignore[attr-defined]

from .abstract import Filter, FilterResult


class DailyVolumeFilterResult(FilterResult):
    """Результат выполнения фильтра по дневному объему."""


class DailyVolumeFilter(Filter):
    """Фильтр для проверки дневного объема (мин/макс в USD)."""

    @staticmethod
    def process(
        ticker_daily: TickerDailyItem,
        dv_min_usd: float | None,
        dv_max_usd: float | None,
    ) -> DailyVolumeFilterResult:
        """Проверяет, что суточный объём в USD попадает в заданный диапазон."""
        volume_usd: float = float(ticker_daily["q"])

        ok = True
        if dv_min_usd is not None and volume_usd < dv_min_usd:
            ok = False
        if dv_max_usd is not None and volume_usd > dv_max_usd:
            ok = False

        return DailyVolumeFilterResult(
            ok=ok,
            metadata={
                "daily_volume_usd": volume_usd,
                "dv_min_usd": dv_min_usd,
                "dv_max_usd": dv_max_usd,
            },
        )
