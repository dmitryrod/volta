from __future__ import annotations

import asyncio

from app.config import logger


async def _support_loop() -> None:
    """Фоновая задача для будущих сервисных штук (health-check, метрики и т.п.)."""
    logger.info("Support task started")
    try:
        while True:
            await asyncio.sleep(3600)
    except asyncio.CancelledError:
        logger.info("Support task stopped")


def start_support_task() -> asyncio.Task:
    """Запускает фоновую задачу и возвращает asyncio.Task."""
    loop = asyncio.get_running_loop()
    return loop.create_task(_support_loop(), name="support-task")

