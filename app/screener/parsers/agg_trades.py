__all__ = ["AggTradesParser"]

import asyncio
from collections import defaultdict

from unicex import (
    Exchange,
    IUniClient,
    KlineDict,
    MarketType,
    TradeDict,
    Websocket,
    get_uni_websocket_manager,
)

from app.config import get_logger

from .abstract import Parser


class AggTradesParser(Parser):
    """Парсер агрегированных сделок."""

    WS_CHUNK_SIZE = {
        Exchange.BINGX: 30,
    }
    """Количество тикеров в одном вебсокет соединении."""
    
    DEFAULT_WS_CHUNK_SIZE = 20
    """Стандартное количество тикеров в одном вебсокет соединении"""

    TIMEFRAME = 1
    """Таймфрейм для аггрегации свечей из сделок в секундах"""

    def __init__(self, exchange: Exchange, market_type: MarketType) -> None:
        """Инициализирует парсер агрегированных сделок.

        Args:
            exchange (Exchange): На какой бирже парсить данные.
            market_type (MarketType): Тип рынка с которого парсить данные.
        """
        super().__init__(exchange, market_type)

        self._logger = get_logger("at")
        self._websockets: list[Websocket] = []
        self._klines_lock = asyncio.Lock()
        self._klines: dict[str, list[KlineDict]] = defaultdict(list)

    async def start(self) -> None:
        """Запускает парсер данных."""
        self._logger.info ("Parser started")
        try:
            async with self._client_context() as client:
                tickers_batched = await self._fetch_tickers_list_batched(client)
                self._websockets = self._init_websockets(tickers_batched)
                tasks = await self._start_websockets()
                await asyncio.gather(*tasks)
        except Exception as e:
            self._logger.exception(f"Error fetching data:{e}")

    async def stop(self) -> None:
        """Останавливает парсер данных."""
        self._logger.info ("Parser stopped")
        gather_results = await asyncio.gather(
            *[ws.stop() for ws in self._websockets], return_exceptions=True
        )
        for result in gather_results:
            if isinstance(result, Exception):
                self._logger.error(f"Error while stopping websocket: {result}")
        self._is_running = False

    async def fetch_collected_data(self) -> dict[str, list[KlineDict]]:
        """Возвращает накопленные данные. Возвращает ссылку на объект в котором данные."""
        async with self._klines_lock:
            return self._klines

    def _init_websockets(self, tickers_batched: list[list[str]]) -> list[Websocket]:
        """Создаёт вебсокеты для потока aggTrades по батчам тикеров."""
        manager_cls = get_uni_websocket_manager(self._exchange)
        manager = manager_cls()  # экземпляр IUniWebsocketManager

        # Для фьючерсов Bybit и других бирж нужно использовать futures_aggtrades,
        # для спота — aggtrades. Выбираем фабрику по типу рынка.
        if self._market_type == MarketType.FUTURES:
            factory = getattr(manager, "futures_aggtrades")
        else:
            factory = getattr(manager, "aggtrades")

        return [
            factory(
                callback=self._aggtrades_callback,
                symbols=batch,
            )
            for batch in tickers_batched
        ]
    
    async def _fetch_tickers_list_batched(self, client: IUniClient) -> list[list[str]]:
        """Возвращает список тикеров в батчах."""
        chunk_size = self.WS_CHUNK_SIZE.get(self._exchange, self.DEFAULT_WS_CHUNK_SIZE)
        match self._market_type:
            case MarketType.SPOT:
                return await client.tickers_batched(batch_size=chunk_size)
            case MarketType.FUTURES:
                return await client.futures_tickers_batched(batch_size=chunk_size)
            case _:
                raise ValueError(f"Unsupported market type: {self._market_type}")


































        return [
            factory(
                callback=self._aggtrades_callback,
                symbols=batch,
            )
            for batch in tickers_batched
        ]

    async def _start_websockets(self) -> list[asyncio.Task]:
        """Запускает вебсокеты."""
        tasks = []
        for websocket in self._websockets:
            if not websocket.running:
                tasks.append(websocket.start())
                self._logger.debug(f"{websocket} started")
                await asyncio.sleep(0.5)
        return tasks

    async def _aggtrades_callback(self, aggtrade: TradeDict) -> None:
        """Обработчик агрегированных сделок."""
        async with self._klines_lock:
            self._process_trade(aggtrade)

    def _process_trade(self, aggtrade: TradeDict) -> None:
        """Агрегирует сделки в свечи и очищает историю."""
        symbol = aggtrade["s"]
        trade_time = int(aggtrade["t"])
        timeframe_ms = self.TIMEFRAME * 1000
        aligned_open_time = (trade_time // timeframe_ms) * timeframe_ms
        trade_price = float(aggtrade["p"])
        trade_volume = float(aggtrade["v"])

        klines = self._klines[symbol]
        if not klines:
            klines.append(
                self._create_new_kline(symbol, aligned_open_time, trade_price, trade_volume)
            )
            return

        kline = klines[-1]
        expected_close_time = kline["t"] + timeframe_ms
        if trade_time >= expected_close_time:
            kline["T"], kline["x"] = expected_close_time, True
            klines.append(
            self._create_new_kline(symbol, aligned_open_time, trade_price, trade_volume)
            )
        else:
            kline["h"] = max(kline["h"], trade_price)
            kline["l"] = min(kline["l"], trade_price)
            kline["c"] = trade_price
            kline["v"] += trade_volume
            kline["q"] += trade_volume * trade_price

        min_open_time = aligned_open_time - self._MAX_HISTORY_LEN * 1000
        self._klines[symbol] = [k for k in klines if k["t"] >= min_open_time]
        self._mark_updated()

    def _create_new_kline(
        self, symbol: str, open_time: int, price: float, volume: float
    ) -> KlineDict:
        """Создаёт новую свечу из сделки."""
        return KlineDict(
            s=symbol,
            t=open_time,
            o=price,
            h=price,
            l=price,
            c=price,
            v=volume,
            q=volume * price,
            T=None,
            x=False,
        )