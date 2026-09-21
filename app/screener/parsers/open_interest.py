__all__ =["OpenInterestParser"]

import asyncio
import time
from collections import defaultdict

from unicex import Exchange, IUniClient, MarketType, OpenInterestDict, OpenInterestItem

from app.config import get_logger

from .abstract import Parser


class OpenInterestParser(Parser):
    """Парсер открытого интереса."""

    _PARSE_INTERVAL = 5
    """Интервал парсинга данных в секундах."""

    _CHUNK_SIZE = {Exchange.BINANCE: 20, Exchange.GATE: 7}
    """Кастомный размер чанка для одновременного запроса данных."""

    _DEFAULT_CHUNK_SIZE = 20
    """Размер чанка для одновременного запроса данных по умолчанию."""

    _CHUNK_INTERVAL = {}
    """Кастомный интервал между запросами данных в секундах."""

    _DEFAULT_CHUNK_INTERVAL = 0.33
    """Интервал между запросами данных в секундах по умолчанию."""

    def __init__(self, exchange: Exchange, **_) -> None:
        """Инициализирует парсер открытого интереса.

        Args:
        exchange (Exchange): На какой бирже парсить данные.
        _ (dict): Дополнительные аргументы, для отказоустойчивости.
        """
        super().__init__(exchange, MarketType.FUTURES)

        self._logger = get_logger("oi")
        self._open_interest_lock = asyncio.Lock()
        self._open_interest: dict[str, list[OpenInterestItem]] = defaultdict(list)

    async def start(self) -> None:
        """Запускает парсер данных."""
        while self._is_running:
            try:
                start_time = time.perf_counter()
                async with self._client_context() as client:
                    snapshot = await self._fetch_open_interest_snapshot(client)
                    snapshot = await self._normalize_open_interest_snapshot(client, snapshot)
                async with self._open_interest_lock:
                    self._process_snapshot(snapshot)
                self._mark_updated()
                self._logger.debug(
                    f"Collected {len(snapshot)} elements."
                    f" It's takes {time.perf_counter() - start_time:.2f} s"
                )
            except Exception as e:
                self._logger.error(f"Error parsing data ({type(e)}): {e}")
            await self._safe_sleep(self._PARSE_INTERVAL)

    async def stop(self) -> None:
        """Останавливает парсер данных."""
        self._logger.info("Parser stopped")
        self._is_running = False

    async def fetch_collected_data(self) -> dict[str, list[OpenInterestItem]]:
        """Возвращает накопленные данные. Возвращает ссылку на объект в котором хранятся данные."""
        async with self._open_interest_lock:
            return self._open_interest

    async def _fetch_open_interest_snapshot(self, client: IUniClient) -> OpenInterestDict:
        """Получает текущие значения открытого интереса."""
        if self._exchange in {Exchange.BINANCE, Exchange.BINGX, Exchange.GATE}:
            return await self._fetch_open_interest_snapshot_batched(client)
        return await client.open_interest()

    async def _fetch_open_interest_snapshot_batched(self, client: IUniClient) -> OpenInterestDict:
        """Получает текущие значения открытого интереса итерируясь по каждому тикеру.
        Используется для бирж, на которых невозможно получить все данные одним запросом."""
        chunk_size = self._CHUNK_SIZE.get(self._exchange, self._DEFAULT_CHUNK_SIZE)
        chunk_interval = self._CHUNK_INTERVAL.get(self._exchange, self._DEFAULT_CHUNK_INTERVAL)
        chunked_tickers_list = await client.futures_tickers_batched(batch_size=chunk_size)

        results = {}
        for chunk in chunked_tickers_list:
            tasks = [client.open_interest(ticker) for ticker in chunk]
            responses = await asyncio.gather(*tasks, return_exceptions=True)
            for ticker, response in zip(chunk, responses, strict=False):
                if isinstance(response, Exception):
                    self._logger.error(f"Failed to fetch open interest for {ticker}: {response}")
                    continue
                if not response:
                    self._logger.warning(f"Empty open interest for {ticker}")
                    continue
                results[ticker] = response
            await asyncio.sleep(chunk_interval)

        return results

    async def _normalize_open_interest_snapshot(
        self, client: IUniClient, open_interest: OpenInterestDict
    )-> OpenInterestDict:
        """Нормализует открытый интерес в случае, если его нужно дополнительно обработать."""
        if self._exchange == Exchange.BINGX:
            last_prices = await client.futures_last_price()

            for ticker, open_interest_item in open_interest.items():
                last_price = last_prices.get(ticker)
                if not last_price:
                    self._logger.debug(f"Missing last price for {ticker}, keep 0I as-is")
                    continue

                try:
                    open_interest_value = open_interest_item["v"] / last_price
                except (KeyError, TypeError, ZeroDivisionError) as e:
                    self._logger.debug(
                        f"Failed to normalize 0I for {ticker} because {e}, keep 0I as-is"
                    )
                    continue

                open_interest_item["v"] = open_interest_value

        return open_interest

    def _process_snapshot(
        self, open_interest: OpenInterestDict
    ) -> dict[str, list[OpenInterestItem]]:
        """Обрабатывает полученный снапшот открытого интереса и сохраняет его в локальное хранилище."""
        threshold: float = (time.time() - self._MAX_HISTORY_LEN) * 1000
        for ticker, open_interest_item in open_interest.items():
            self._open_interest[ticker] = [
                el for el in self._open_interest[ticker] if el["t"] >= threshold
            ]
            self._open_interest[ticker].append(open_interest_item)
        return self._open_interest