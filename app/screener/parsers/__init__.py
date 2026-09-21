"""Пакет содержащий логику парсеров"""

from dataclasses import dataclass

__all__ = [
    "AggTradesParser",
    "FundingRateParser",
    "LiquidationsParser",
    "OpenInterestParser",
    "TickerDailyParser",
    "ParsersDTO",
]

from .agg_trades import AggTradesParser
from .funding_rate import FundingRateParser
from .liquidations import LiquidationsParser
from .open_interest import OpenInterestParser
from .ticker_daily import TickerDailyParser


@dataclass(frozen=True, slots=True)
class ParsersDTO:
    """Модель для передачи работающих экземпляров парсеров между слоями приложения."""

    agg_trades: AggTradesParser
    """Парсер аггрегированных сделок"""

    ticker_daily: TickerDailyParser
    """Парсер статистики тикеров за сутки"""

    funding_rate: FundingRateParser | None
    """Парсер ставки финансирования"""

    liquidations: LiquidationsParser | None
    """Парсер ликвидаций"""

    open_interest: OpenInterestParser | None
    """Парсер открытого интереса"""
