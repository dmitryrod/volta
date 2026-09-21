__all__ = ["Parser"]

import asyncio
import time
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from unicex import Exchange, IUniClient, MarketType, get_uni_client


class Parser(ABC):
    """Базовый класс для парсеров данных."""

    _MAX_HISTORY_LEN = 60 * 15
    """Максимальная длина истории в секундах для всех парсеров."""

    _MARK_UPDATED_THROTTLE_SEC: float = 10.0
    """Троттлинг обновления last_update_ts при частых коллбеках.

    Вебсокеты по трейдам/ликвидациям могут приходить очень часто, и
    time.time() на каждый пакет может заметно грузить CPU.
    Для detection stale > 60с этого более чем достаточно.
    """

    def __init__(self, exchange: Exchange, market_type: MarketType) -> None:
        """Инициализирует парсера данных.

        Args:
            exchange (Exchange): На какой бирже парсить данные.
            market_type (MarketType): Тип рынка с которого парсить данные.
        """
        self._exchange = exchange
        self._market_type = market_type
        self._is_running = True
        self._last_update_ts: float = 0.0
        self._started_ts: float = time.time()
        self._last_mark_ts: float = 0.0

    @property
    def last_update_ts(self) -> float:
        """Unix timestamp (sec) последнего успешного обновления данных."""
        return self._last_update_ts

    @property
    def started_ts(self) -> float:
        """Unix timestamp (sec) когда парсер был создан/запущен в памяти."""
        return self._started_ts

    def mark_running(self) -> None:
        """После stop() или перед повторным start(): снова разрешить работу цикла парсера."""
        self._is_running = True
        self._started_ts = time.time()
        self._last_update_ts = 0.0
        self._last_mark_ts = 0.0

    def _mark_updated(self) -> None:
        now = time.time()
        if self._last_mark_ts and (now - self._last_mark_ts) < self._MARK_UPDATED_THROTTLE_SEC:
            return
        self._last_mark_ts = now
        self._last_update_ts = now

    @abstractmethod
    async def start(self) -> None:
        """Запускает парсер данных."""
        pass

    async def _safe_sleep(self, seconds: int) -> None:
        """Безопасное ожидание, которое может прерваться в процессе."""
        for _ in range(seconds):
            if not self._is_running:
                return
            await asyncio.sleep(1)

    @asynccontextmanager
    async def _client_context(self, **kwargs: Any) -> AsyncIterator[IUniClient]:
        """Создаёт клиента unicex и гарантированно закрывает соединение по завершении контекста.
        Args:
        **kwargs (Any): Любые параметры, которые нужно передать в UniClient.create (например, logger).
        Yields:
        AsyncIterator[Any]: Инициализированный и готовый к работе клиент.
        """
        client = await get_uni_client(self._exchange).create(**kwargs)
        async with client:
            yield client