"""Ingestor operator with watchdog."""

from __future__ import annotations

import asyncio
import time

from loguru import logger

from app_options.config import config
from app_options.ingestor.collectors import KlineWsCollector, OptionsSnapshotCollector, PolymarketSnapshotCollector
from app_options.ingestor.writer import SnapshotWriter
from app_options.utils.connectivity import wait_for_internet


class IngestorOperator:
    """Manage collector tasks and restart stale ones."""

    def __init__(self) -> None:
        self._is_running = False
        self._writer = SnapshotWriter()
        self._collectors: list[tuple[str, object]] = []
        self._tasks: dict[str, asyncio.Task] = {}
        self._interval = config.ingestor.interval_sec
        self._stale_threshold = self._interval * 2

    async def start(self) -> None:
        if self._is_running:
            raise RuntimeError("IngestorOperator already running")
        self._is_running = True
        await wait_for_internet(log_name="ingestor-start")
        exchange = config.ingestor.exchange
        collectors = [
            KlineWsCollector(self._writer, exchange),
            OptionsSnapshotCollector(self._writer, exchange),
            PolymarketSnapshotCollector(self._writer),
        ]
        self._collectors = [(c.name, c) for c in collectors]
        for name, collector in self._collectors:
            collector.mark_running()
            self._tasks[name] = asyncio.create_task(
                collector.start(), name=f"collector-{name}"
            )
        logger.info("IngestorOperator started with {} collectors", len(self._collectors))
        while self._is_running:
            await self._watchdog()
            await asyncio.sleep(10)

    async def stop(self) -> None:
        self._is_running = False
        for name, collector in self._collectors:
            if hasattr(collector, "stop"):
                result = collector.stop()
                if hasattr(result, "__await__"):
                    await result
        for name, task in list(self._tasks.items()):
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception as exc:
                logger.warning("Collector {} stopped with error: {}", name, exc)
        self._tasks.clear()
        logger.info("IngestorOperator stopped")

    async def _watchdog(self) -> None:
        now = time.time()
        for name, collector in self._collectors:
            last = collector.last_update_ts
            if last == 0:
                age = now - collector.started_ts
            else:
                age = now - last
            if age < self._stale_threshold:
                continue
            task = self._tasks.get(name)
            if task and not task.done():
                logger.warning(
                    "Collector {} stale ({:.0f}s), restarting",
                    name,
                    age,
                )
                stop_result = collector.stop()
                if hasattr(stop_result, "__await__"):
                    await stop_result
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
            collector.mark_running()
            self._tasks[name] = asyncio.create_task(
                collector.start(), name=f"collector-{name}"
            )
