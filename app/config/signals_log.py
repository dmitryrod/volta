"""Единый текстовый журнал сигналов и событий: ``app/logs/signals_log.txt``."""

from __future__ import annotations

import asyncio
import json
import queue
import threading
from pathlib import Path
from typing import Any

from .moscow_rotating import moscow_iso_timestamp, prune_timestamped_archives, rotate_file_to_timestamped_archive

LOG_DIR = Path(__file__).resolve().parents[1] / "logs"
SIGNALS_LOG_PATH = LOG_DIR / "signals_log.txt"

_MAX_BYTES = 10 * 1024 * 1024
_MAX_ARCHIVES = 10
_ARCHIVE_STEM = "signals_log"
_ARCHIVE_SUFFIX = ".txt"

_queue: queue.Queue[str | None] = queue.Queue(maxsize=50_000)
_writer_thread: threading.Thread | None = None
_thread_start_lock = threading.Lock()
_file_io_lock = threading.Lock()


def _ensure_writer() -> None:
    global _writer_thread
    with _thread_start_lock:
        if _writer_thread is not None and _writer_thread.is_alive():
            return

        def _run() -> None:
            while True:
                line = _queue.get()
                if line is None:
                    break
                try:
                    _write_line_sync(line)
                except Exception:
                    pass
                finally:
                    _queue.task_done()

        t = threading.Thread(target=_run, name="signals_log_writer", daemon=True)
        t.start()
        _writer_thread = t


def _write_line_sync(line: str) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    data = (line if line.endswith("\n") else line + "\n").encode("utf-8", errors="replace")
    with _file_io_lock:
        cur = SIGNALS_LOG_PATH.stat().st_size if SIGNALS_LOG_PATH.exists() else 0
        if cur + len(data) > _MAX_BYTES:
            try:
                if SIGNALS_LOG_PATH.stat().st_size > 0:
                    rotate_file_to_timestamped_archive(
                        SIGNALS_LOG_PATH,
                        archive_stem=_ARCHIVE_STEM,
                        archive_suffix=_ARCHIVE_SUFFIX,
                    )
                prune_timestamped_archives(
                    LOG_DIR,
                    archive_stem=_ARCHIVE_STEM,
                    archive_suffix=_ARCHIVE_SUFFIX,
                    max_archives=_MAX_ARCHIVES,
                )
            except OSError:
                pass
        with SIGNALS_LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(line if line.endswith("\n") else line + "\n")


def log_signals_event(payload: dict[str, Any]) -> None:
    """Одна JSON-строка (kind, ts_moscow, …). Не бросает наружу."""
    _ensure_writer()
    row = dict(payload)
    ts = moscow_iso_timestamp()
    row.setdefault("ts_moscow", ts)
    try:
        line = f"{ts}\t{json.dumps(row, ensure_ascii=False, default=str)}"
    except Exception:
        line = f"{ts}\t{json.dumps({'kind': 'signals_log_error', 'ts_moscow': ts, 'error': 'json_dump_failed'}, ensure_ascii=False)}"
    try:
        _queue.put_nowait(line)
    except queue.Full:
        pass


async def log_signals_event_async(payload: dict[str, Any]) -> None:
    """Тот же вывод, но из async-контекста без блокировки loop."""

    def _run() -> None:
        log_signals_event(payload)

    await asyncio.to_thread(_run)


def _flatten_calc_for_line(calc: dict[str, Any] | None) -> dict[str, Any]:
    """Плоский словарь переменных для одной строки мониторинга."""
    if not calc:
        return {}
    out: dict[str, Any] = {"calc": calc}
    try:
        inputs = calc.get("inputs") or {}
        settings = calc.get("settings") or {}
        filters = calc.get("filters") or {}
        for k, v in inputs.items():
            out[f"in_{k}"] = v
        for k, v in settings.items():
            out[f"cfg_{k}"] = v
        for fname, fval in filters.items():
            if fval is None:
                continue
            if isinstance(fval, dict):
                for k, v in fval.items():
                    out[f"f_{fname}_{k}"] = v
            else:
                out[f"f_{fname}"] = fval
    except Exception:
        pass
    return out


def build_signal_log_payload(
    *,
    screener_name: str,
    screener_id: int,
    exchange: str,
    market_type: str,
    symbol: str,
    telegram_text: str,
    signal: dict[str, Any] | None,
    screening_result: dict[str, Any] | None,
    calc_debug: dict[str, Any] | None,
    daily_signal_count: int | None,
    run_id: str,
    cycle_id: int,
    telegram_ok: bool,
    telegram: dict[str, Any] | None,
    error: str | None = None,
) -> dict[str, Any]:
    """Базовый JSON для строки `signals_log.txt`. Поля ``card_snapshot`` и ``tracking_id`` добавляет ``Consumer._send_signal`` при наличии снимка в БД."""
    text_one_line = (telegram_text or "").replace("\r\n", "\n").replace("\n", "\\n")
    base: dict[str, Any] = {
        "kind": "signal",
        "screener_name": screener_name,
        "screener_id": screener_id,
        "exchange": exchange,
        "market_type": market_type,
        "symbol": symbol,
        "telegram_text": text_one_line,
        "telegram_ok": telegram_ok,
        "telegram": telegram or {},
        "run_id": run_id,
        "cycle_id": cycle_id,
        "daily_signal_count": daily_signal_count,
        "signal": signal or {},
        "screening_result": screening_result or {},
        "error": error,
    }
    base.update(_flatten_calc_for_line(calc_debug))
    return base
