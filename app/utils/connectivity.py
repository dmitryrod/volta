"""Проверка доступности интернета и классификация «временных» сетевых сбоев.

Нужен при нестабильном канале и фильтрации трафика: несколько независимых HTTPS-проб,
экспоненциальная задержка между попытками, без падения основного процесса.
"""

from __future__ import annotations

import asyncio
import errno
import os
import random
import ssl
from typing import Any

import aiohttp

from app.config import get_logger

__all__ = [
    "check_internet",
    "wait_for_internet",
    "is_transient_network_error",
]

_logger = get_logger("connectivity")

# Разные провайдеры/домены: при блокировке одного может открыться другой.
_DEFAULT_PROBE_URLS: tuple[str, ...] = (
    "https://1.1.1.1/cdn-cgi/trace",
    "https://dns.google/resolve?name=example.com&type=A",
    "https://www.gstatic.com/generate_204",
    "https://connectivitycheck.gstatic.com/generate_204",
)


def _probe_urls() -> tuple[str, ...]:
    raw = (os.getenv("CONNECTIVITY_PROBE_URLS") or "").strip()
    if raw:
        return tuple(u.strip() for u in raw.split(",") if u.strip())
    return _DEFAULT_PROBE_URLS


def is_transient_network_error(exc: BaseException, _depth: int = 0) -> bool:
    """Ошибка, после которой имеет смысл подождать восстановления сети/БД, а не выходить."""
    if _depth > 8:
        return False

    if isinstance(exc, (asyncio.TimeoutError, ConnectionError, BrokenPipeError)):
        return True

    if isinstance(exc, OSError):
        code = getattr(exc, "errno", None)
        transient_codes = {
            errno.ECONNRESET,
            errno.ETIMEDOUT,
            errno.EHOSTUNREACH,
            errno.ENETUNREACH,
            errno.ECONNREFUSED,
            errno.EPIPE,
            errno.ENETDOWN,
            errno.ECONNABORTED,
        }
        eai = getattr(errno, "EAI_AGAIN", None)
        if eai is not None:
            transient_codes.add(eai)
        if code in transient_codes:
            return True
        if code is None and os.name == "nt":
            winerr = getattr(exc, "winerror", None)
            if winerr in {10050, 10051, 10052, 10053, 10054, 10060, 10061, 10064}:
                return True

    if isinstance(exc, ssl.SSLError):
        return True

    if isinstance(exc, aiohttp.ClientError):
        return True

    try:
        from sqlalchemy.exc import DisconnectionError, OperationalError

        if isinstance(exc, (OperationalError, DisconnectionError)):
            return True
    except ImportError:
        pass

    try:
        import asyncpg.exceptions as apg

        if isinstance(
            exc,
            (
                apg.ConnectionDoesNotExistError,
                apg.CannotConnectNowError,
                apg.ConnectionFailureError,
                apg.InterfaceError,
            ),
        ):
            return True
    except ImportError:
        pass

    if exc.__cause__ is not None:
        return is_transient_network_error(exc.__cause__, _depth + 1)
    ctx = exc.__context__
    if ctx is not None and ctx is not exc.__cause__:
        return is_transient_network_error(ctx, _depth + 1)
    return False


async def check_internet(
    *,
    timeout_per_url: float = 5.0,
    urls: tuple[str, ...] | None = None,
) -> bool:
    """Возвращает True, если хотя бы один HTTPS-запрос успешно завершился (не 5xx)."""
    probe_urls = urls or _probe_urls()
    timeout = aiohttp.ClientTimeout(total=timeout_per_url, connect=min(4.0, timeout_per_url))
    async with aiohttp.ClientSession(timeout=timeout) as session:
        for url in probe_urls:
            try:
                async with session.get(url, allow_redirects=True) as resp:
                    if resp.status < 500:
                        return True
            except Exception:
                continue
    return False


async def wait_for_internet(
    *,
    log_name: str = "app",
    logger: Any | None = None,
    initial_interval_sec: float = 5.0,
    max_interval_sec: float = 120.0,
    jitter_sec: float = 4.0,
) -> None:
    """Ждёт, пока check_internet() не вернёт True. Между попытками — растущий интервал + jitter."""
    log = logger or _logger
    interval = initial_interval_sec
    was_offline = False
    while True:
        try:
            ok = await check_internet()
        except Exception as exc:
            log.warning("connectivity probe error ({}): {} — {}", log_name, type(exc).__name__, exc)
            ok = False
        if ok:
            if was_offline:
                log.info("Интернет снова доступен ({})", log_name)
            return
        was_offline = True
        sleep_s = min(interval, max_interval_sec) + random.uniform(0.0, jitter_sec)
        log.warning(
            "Нет стабильного интернета ({}), следующая проверка через {:.1f} c",
            log_name,
            sleep_s,
        )
        await asyncio.sleep(sleep_s)
        interval = min(interval * 1.5, max_interval_sec)
