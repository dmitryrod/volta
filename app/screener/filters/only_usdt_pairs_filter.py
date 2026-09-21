__all__ = ["OnlyUsdtPairsFilter"]

from .abstract import Filter, FilterResult


class OnlyUsdtPairsFilter(Filter):
    """Фильтр для проверки что пара к USDT."""

    @staticmethod
    def process(symbol: str) -> FilterResult:
        """Разрешает только пары к USDT (включая фьючерсные тикеры вида XXX-USDT-SWAP)."""
        is_usdt_pair = symbol.endswith("USDT") or symbol.endswith("-USDT-SWAP")
        return FilterResult(
            ok=is_usdt_pair,
            metadata={"symbol": symbol, "is_usdt_pair": is_usdt_pair},
        )