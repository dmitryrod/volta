"""Трансляция снимков режима «Тест» в админку (SSE)."""

from __future__ import annotations

import asyncio
import threading
from typing import Any

_lock = threading.Lock()
_subscriber_queues: list[asyncio.Queue[dict[str, Any]]] = []


def register_test_stream_subscriber(queue: asyncio.Queue[dict[str, Any]]) -> None:
    with _lock:
        _subscriber_queues.append(queue)


def unregister_test_stream_subscriber(queue: asyncio.Queue[dict[str, Any]]) -> None:
    with _lock:
        if queue in _subscriber_queues:
            _subscriber_queues.remove(queue)


def test_stream_is_active() -> bool:
    with _lock:
        return len(_subscriber_queues) > 0


async def broadcast_test_payload(payload: dict[str, Any]) -> None:
    with _lock:
        queues = list(_subscriber_queues)
    for q in queues:
        try:
            q.put_nowait(payload)
        except asyncio.QueueFull:
            try:
                q.get_nowait()
            except asyncio.QueueEmpty:
                pass
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:
                pass
