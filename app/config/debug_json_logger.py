from __future__ import annotations

import asyncio
import json
import logging
import queue
import traceback
from logging.handlers import QueueHandler, QueueListener
from pathlib import Path
from typing import Any

from .moscow_rotating import moscow_iso_timestamp
from .moscow_size_rotating_handler import MoscowSizeRotatingFileHandler


LOG_DIR = Path(__file__).resolve().parents[1] / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

DEBUG_LOG_PATH = LOG_DIR / "debug.log"


class _SafeMoscowSizeRotatingFileHandler(MoscowSizeRotatingFileHandler):
    """Ротация на bind-mount/Docker: при сбое rename не роняем QueueListener."""

    def doRollover(self) -> None:  # noqa: A003
        try:
            super().doRollover()
        except OSError as exc:
            logging.getLogger(__name__).warning(
                "debug.log rollover failed (%s); reopening stream", exc
            )
            with self._rotate_lock:
                if self.stream:
                    try:
                        self.stream.close()
                    except OSError:
                        pass
                    self.stream = None  # type: ignore[assignment]
                self.stream = self._open()


_queue: queue.Queue[logging.LogRecord] = queue.Queue(maxsize=250_000)
_listener: QueueListener | None = None


class _JsonLineFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:  # noqa: A003
        msg = record.getMessage()
        # Если msg уже JSON (строка) — просто отдаем как есть.
        # Но гарантируем 1 строку.
        return msg.replace("\n", "\\n")


def _ensure_listener_started() -> None:
    global _listener
    if _listener is not None:
        return

    file_handler = _SafeMoscowSizeRotatingFileHandler(
        DEBUG_LOG_PATH,
        max_bytes=100 * 1024 * 1024,  # 100MB
        backup_count=10,
        encoding="utf-8",
        delay=True,
    )
    file_handler.setFormatter(_JsonLineFormatter())

    _listener = QueueListener(_queue, file_handler, respect_handler_level=True)
    _listener.daemon = True
    _listener.start()


def get_debug_json_logger() -> logging.Logger:
    _ensure_listener_started()
    logger = logging.getLogger("debug_json")
    if not any(isinstance(h, QueueHandler) for h in logger.handlers):
        logger.setLevel(logging.INFO)
        logger.propagate = False
        logger.addHandler(QueueHandler(_queue))
    return logger


def log_debug_event(
    *,
    level: str,
    screener_name: str,
    screener_id: int,
    exchange: str,
    market_type: str,
    event: str,
    symbol: str | None,
    payload: dict[str, Any] | None,
    run_id: str,
    cycle_id: int,
    exc: BaseException | None = None,
) -> None:
    """
    Пишет 1 строку в app/logs/debug.log: в начале — дата/время (Москва), таб, затем JSON.
    Поля JSON: ts (Москва, ISO), screener_name, screener_id, level, …
    """
    logger = get_debug_json_logger()

    ts = moscow_iso_timestamp()
    data: dict[str, Any] = {
        "ts": ts,
        "screener_name": screener_name,
        "screener_id": screener_id,
        "level": level,
        "exchange": exchange,
        "market_type": market_type,
        "event": event,
        "symbol": symbol,
        "payload": payload or {},
        "run_id": run_id,
        "cycle_id": cycle_id,
    }

    if exc is not None:
        data["payload"] = dict(data["payload"] or {})
        data["payload"]["exception"] = {
            "type": type(exc).__name__,
            "message": str(exc),
            "stacktrace": "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)),
        }

    try:
        line = f"{ts}\t{json.dumps(data, ensure_ascii=False, default=str)}"
    except Exception as dump_exc:
        fallback = {
            "ts": ts,
            "screener_name": screener_name,
            "screener_id": screener_id,
            "level": "error",
            "exchange": exchange,
            "market_type": market_type,
            "event": "debug_log_dump_error",
            "symbol": symbol,
            "payload": {
                "original_event": event,
                "dump_error": str(dump_exc),
            },
            "run_id": run_id,
            "cycle_id": cycle_id,
        }
        line = f"{ts}\t{json.dumps(fallback, ensure_ascii=False, default=str)}"

    try:
        logger.info(line)
    except Exception:
        # Очередь QueueHandler переполнена или запись сломалась — не роняем consumer.
        logging.getLogger(__name__).exception("debug_json logger.info failed")


async def log_debug_event_async(**kwargs: Any) -> None:
    """Тяжёлый json.dumps + запись в очередь — вне event loop, чтобы не голодали websocket-коллбеки."""

    def _run() -> None:
        log_debug_event(**kwargs)

    await asyncio.to_thread(_run)

