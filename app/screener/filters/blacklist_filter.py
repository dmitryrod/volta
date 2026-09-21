__all__ = ["BlacklistFilter"]

from .abstract import Filter, FilterResult


class BlacklistFilter(Filter):
    """Фильтр для проверки наличия тикера в черном списке."""

    @staticmethod
    def process(ticker: str, blacklist: set[str]) -> FilterResult:
        """Отклоняет тикер, если он есть в чёрном списке."""
        is_blacklisted = ticker in blacklist
        return FilterResult(
            ok=not is_blacklisted,
            metadata={"ticker": ticker, "is_blacklisted": is_blacklisted},
        )