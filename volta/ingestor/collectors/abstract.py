"""Base collector with unicex client lifecycle."""

from __future__ import annotations

import asyncio
import time
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from loguru import logger
from unicex import Exchange, IUniClient, get_uni_client


class Collector(ABC):
    """Base class for snapshot collectors."""

    _MARK_UPDATED_THROTTLE_SEC: float = 10.0

    def __init__(self, exchange: Exchange, name: str) -> None:
        self._exchange = exchange
        self._name = name
        self._is_running = True
        self._last_update_ts: float = 0.0
        self._started_ts: float = time.time()
        self._last_mark_ts: float = 0.0
        self._logger = logger.bind(collector=name)

    @property
    def name(self) -> str:
        return self._name

    @property
    def last_update_ts(self) -> float:
        return self._last_update_ts

    @property
    def started_ts(self) -> float:
        return self._started_ts

    def mark_running(self) -> None:
        self._is_running = True
        self._started_ts = time.time()
        self._last_update_ts = 0.0
        self._last_mark_ts = 0.0

    def stop(self) -> None:
        self._is_running = False

    def _mark_updated(self) -> None:
        now = time.time()
        if self._last_mark_ts and (now - self._last_mark_ts) < self._MARK_UPDATED_THROTTLE_SEC:
            return
        self._last_mark_ts = now
        self._last_update_ts = now

    @abstractmethod
    async def start(self) -> None:
        """Run collector loop."""

    async def _safe_sleep(self, seconds: int) -> None:
        for _ in range(seconds):
            if not self._is_running:
                return
            await asyncio.sleep(1)

    @asynccontextmanager
    async def _client_context(self, **kwargs: Any) -> AsyncIterator[IUniClient]:
        client = await get_uni_client(self._exchange).create(**kwargs)
        async with client:
            yield client
