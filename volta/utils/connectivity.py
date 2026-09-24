"""Network connectivity helpers (adapted from money-pulso)."""

from __future__ import annotations

import asyncio
import errno
import os
import random
import ssl
from typing import Any

import aiohttp
from loguru import logger

__all__ = [
    "check_internet",
    "wait_for_internet",
    "is_transient_network_error",
]

_DEFAULT_PROBE_URLS: tuple[str, ...] = (
    "https://1.1.1.1/cdn-cgi/trace",
    "https://dns.google/resolve?name=example.com&type=A",
    "https://www.gstatic.com/generate_204",
)


def _probe_urls() -> tuple[str, ...]:
    raw = (os.getenv("CONNECTIVITY_PROBE_URLS") or "").strip()
    if raw:
        return tuple(u.strip() for u in raw.split(",") if u.strip())
    return _DEFAULT_PROBE_URLS


def is_transient_network_error(exc: BaseException, _depth: int = 0) -> bool:
    """Return True if error is likely transient (network/DB)."""
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
    """Return True if at least one HTTPS probe succeeds."""
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
    log_name: str = "volta",
    log: Any | None = None,
    initial_interval_sec: float = 5.0,
    max_interval_sec: float = 120.0,
    jitter_sec: float = 4.0,
) -> None:
    """Block until internet is available."""
    log_obj = log or logger
    interval = initial_interval_sec
    was_offline = False
    while True:
        try:
            ok = await check_internet()
        except Exception as exc:
            log_obj.warning("connectivity probe error ({}): {}", log_name, exc)
            ok = False
        if ok:
            if was_offline:
                log_obj.info("Internet restored ({})", log_name)
            return
        was_offline = True
        sleep_s = min(interval, max_interval_sec) + random.uniform(0.0, jitter_sec)
        log_obj.warning("No internet ({}), retry in {:.1f}s", log_name, sleep_s)
        await asyncio.sleep(sleep_s)
        interval = min(interval * 1.5, max_interval_sec)
