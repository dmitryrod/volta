__all__ = ["FundingRateParser"]

import asyncio
import time
from collections import defaultdict

from unicex import Exchange, IUniClient, MarketType

from app.config import get_logger
from .abstract import Parser


class FundingRateParser(Parser):
    """Парсер ставки финансирования."""

    _PARSE_INTERVAL: int = 5
    """Интервал парсинга данных."""

    _CHUNK_SIZE = {Exchange.OKX: 50}
    """Кастомный размер чанка для одновременного запроса данных."""

    _DEFAULT_CHUNK_SIZE = 20
    """Размер чанка для одновременного запроса данных по умолчанию."""

    _CHUNK_INTERVAL = {}
    """Кастомный интервал между запросами данных в секундах."""

    _DEFAULT_CHUNK_INTERVAL = 0.1
    """Интервал между запросами данных в секундах по умолчанию."""

    def __init__(self, exchange: Exchange, **_) -> None:
        """Инициализирует парсер ставки финансирования.

        Args:
            exchange (Exchange): На какой бирже парсить данные.
            _ (dict): Дополнительные аргументы, для отказоустойчивости.
        """
        super().__init__(exchange, MarketType.FUTURES)

        self._logger = get_logger("fr")
        self._funding_rate_lock = asyncio.Lock()
        self._funding_rate: dict[str, float] = defaultdict()

    async def start(self) -> None:
        """Запускает парсер данных."""
        self._logger.info(f"FundingRateParser started for {self._exchange.value}:{self._market_type.value}")
        while self._is_running:
            try:
                start_time = time.perf_counter()
                async with self._client_context() as client:
                    ticker_daily = await self._fetch_funding_rate(client)
                    async with self._funding_rate_lock:
                        self._funding_rate = ticker_daily
                self._mark_updated()
                # Короткий снапшот: сколько значений фандинга пришло и пример ключей
                self._logger.info(
                    "Funding rate data fetched: count={}, sample={}, took={:.2f}s",
                    len(self._funding_rate),
                    list(self._funding_rate.items())[:3],
                    time.perf_counter() - start_time,
                )
            except Exception as e:
                self._logger.error(f"Error fetching data ({type(e)}): {e}")
            await self._safe_sleep(self._PARSE_INTERVAL)

    async def _fetch_funding_rate(self, client: IUniClient) -> dict[str, float]:
        """Получает данные о тикере за последние 24 часа."""
        if self._exchange in [Exchange.OKX]:
            return await self._fetch_funding_rate_batched(client)
        return await client.funding_rate()

    async def _fetch_funding_rate_batched(self, client: IUniClient) -> dict[str, float]:
        """Получает текущие значения открытого интереса итерируясь по каждому тикеру.
        Используется для бирж, на которых невозможно получить все данные одним запросом."""
        chunk_size = self._CHUNK_SIZE.get(self._exchange, self._DEFAULT_CHUNK_SIZE)
        chunk_interval = self._CHUNK_INTERVAL.get(self._exchange, self._DEFAULT_CHUNK_INTERVAL)
        chunked_tickers_list = await client.futures_tickers_batched(batch_size=chunk_size)
        
        results = {}
        for chunk in chunked_tickers_list:
            tasks = [client.funding_rate(ticker) for ticker in chunk]
            responses = await asyncio.gather(*tasks, return_exceptions=True)
            for ticker, response in zip(chunk, responses, strict=False):
                if isinstance(response, Exception):
                    self._logger.error(f"Failed to fetch open interest for {ticker}: {response}")
                    continue
                if response is None:
                    self._logger.warning(f"Empty open interest for {ticker}")
                    continue
                results[ticker] = response
            await asyncio.sleep(chunk_interval)
    
        return results

    async def stop(self) -> None:
        """Останавливает парсер данных."""
        self._logger.info("Parser stopped")
        self._is_running = False

    async def fetch_collected_data(self) -> dict[str, float]:
        """Возвращает накопленные данные. Возвращает ссылку на объект в котором хранятся данные"""
        async with self._funding_rate_lock:
            return self._funding_rate