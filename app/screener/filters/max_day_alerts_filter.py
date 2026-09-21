__all__ = ["MaxDayAlertsFilter"]

from .abstract import Filter, FilterResult


class MaxDayAlertsFilter(Filter):
    """Фильтр, ограничивающий количество сигналов по тикеру в сутки."""
    
    @staticmethod
    def process(signal_count: int, max_day_alerts: int) -> FilterResult:
        """Возвращает успешный результат, пока лимит сигналов не превышен."""
        return FilterResult(
            ok=signal_count < max_day_alerts,
            metadata={
            "max_day_alerts": max_day_alerts,
            "signal_count": signal_count,
            }
        )