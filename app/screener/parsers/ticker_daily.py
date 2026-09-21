__all__ = ["TickerDailyParser"]

import asyncio
import time

from unicex import Exchange, IUniClient, MarketType, TickerDailyDict

from app.config import get_logger

from .abstract import Parser


class TickerDailyParser(Parser):
    """Парсер статистики тикеров за сутки."""

    _PARSE_INTERVAL: int = 10
    """Интервал парсинга данных."""

    def __init__(self, exchange: Exchange, market_type: MarketType) -> None:
        """Инициализирует парсер статистики тикеров за сутки.
        
        Args:
            exchange (Exchange): На какой бирже парсить данные.
            market_type (MarketType): Тип рынка.
        """
        super(). __init__(exchange, market_type)

        self._logger = get_logger("td")
        self._ticker_daily_lock = asyncio.Lock()
        self._ticker_daily: TickerDailyDict = {}

    async def start(self) -> None:
        """Запускает парсер данных."""
        self._logger.info ("Parser started")
        while self._is_running:
            try:
                start_time = time.perf_counter()
                async with self._client_context() as client:
                    ticker_daily = await self._fetch_ticker_daily(client)
                    async with self._ticker_daily_lock:
                        self._ticker_daily = ticker_daily
                    self._mark_updated()
                    self._logger.debug(
                        "Ticker daily data fetched. "
                        f"It's takes {time.perf_counter() - start_time:.2f} s"
                    )
            except Exception as e:
                self._logger.error(f"Error fetching data ({type(e)}]: {e}")
            await self._safe_sleep(self._PARSE_INTERVAL)
    
    async def stop(self) -> None:
        """Останавливает парсер данных."""
        self._logger.info ("Parser stopped")
        self._is_running = False
    
    async def fetch_collected_data(self) -> TickerDailyDict:
        """Возвращает накопленные данные. Возвращает ссылку на объект в котором хранятся данные."""
        async with self._ticker_daily_lock:
            return self._ticker_daily
    
    async def _fetch_ticker_daily(self, client: IUniClient) -> TickerDailyDict:
        """Получает данные о тикерах за последние 24 часа.

        Для MVP нам достаточно корректной работы для Bybit и большинства спотовых/фьючерсных рынков.
        Интерфейс унифицированного клиента unicex предоставляет методы ticker_24hr/ticker_daily
        и, при необходимости, futures_ticker_daily.
        """
        # Попробуем сначала наиболее общий вариант, затем fallback'и.
        # Это немного спекуляция по API unicex, но её легко поправить по логам,
        # если что-то изменится.
        if self._market_type == MarketType.FUTURES:
            # Фьючерсы: сначала специализированный метод, затем общий.
            if hasattr(client, "futures_ticker_daily"):
                return await client.futures_ticker_daily()  # type: ignore[attr-defined]
            if hasattr(client, "ticker_daily"):
                return await client.ticker_daily()  # type: ignore[attr-defined]
            return await client.ticker_24hr()  # type: ignore[attr-defined]

        # Спот
        if hasattr(client, "ticker_daily"):
            return await client.ticker_daily()  # type: ignore[attr-defined]
        return await client.ticker_24hr()  # type: ignore[attr-defined]