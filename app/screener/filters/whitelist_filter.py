__all__ = ["WhitelistFilter"]

from .abstract import Filter, FilterResult


class WhitelistFilter(Filter):
    """Фильтр для проверки наличия тикера в белом списке."""
    
    @staticmethod
    def process(ticker: str, whitelist: set[str]) -> FilterResult:
        """Если список не пустой — пропускает только тикеры из белого списка."""
        if not whitelist:
            return FilterResult(ok=True, metadata={"ticker": ticker, "whitelist_empty": True})

        is_whitelisted = ticker in whitelist
        return FilterResult(
            ok=is_whitelisted,
            metadata={"ticker": ticker, "is_whitelisted": is_whitelisted},
        )
