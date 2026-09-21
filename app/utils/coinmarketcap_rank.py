import email.utils
import logging
import os
import random
import secrets
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence

import requests

logger = logging.getLogger(__name__)

_CMC_RANKS: Dict[str, int] = {}
_CMC_LOCK = threading.RLock()
_CMC_THREAD_STARTED = False
_CMC_INITIAL_FETCH_DONE = False

_LISTINGS_URL = "https://pro-api.coinmarketcap.com/v1/cryptocurrency/listings/latest"


def _parse_api_keys(raw: Optional[str]) -> List[str]:
    """
    Одна переменная окружения может содержать несколько ключей через «|».

    Пустые сегменты отбрасываются («a||b» → два ключа).

    Args:
        raw: Строка из env или None.

    Returns:
        Список непустых ключей (после strip).
    """
    if raw is None or not str(raw).strip():
        return []
    keys: List[str] = []
    for part in str(raw).split("|"):
        key = part.strip()
        if key:
            keys.append(key)
    return keys


def _get_env_api_keys() -> List[str]:
    """Ключи CMC из `X-CMC_PRO_API_KEY` или `CMC_PRO_API_KEY`; несколько ключей через `|` в одной строке."""
    raw = os.getenv("X-CMC_PRO_API_KEY") or os.getenv("CMC_PRO_API_KEY")
    return _parse_api_keys(raw)


def _pick_api_key(keys: Sequence[str]) -> str:
    """Выбор ключа для одного HTTP-запроса (равномерно по списку)."""
    return secrets.choice(list(keys))


def _http_headers_with_key(api_key: str) -> Dict[str, str]:
    return {
        "X-CMC_PRO_API_KEY": api_key,
        "Accept": "application/json",
    }


def _get_update_interval_seconds() -> int:
    raw = os.getenv("X-CMC_UPDATE_TIME") or os.getenv("CMC_UPDATE_TIME") or "90"
    try:
        minutes = int(str(raw).strip().split()[0])
    except (TypeError, ValueError):
        minutes = 90
    if minutes <= 0:
        minutes = 90
    return minutes * 60


def _get_listings_page_size() -> int:
    """Размер страницы listings/latest (1…5000). Документация CMC: max limit 5000."""
    raw = os.getenv("X-CMC_LISTINGS_PAGE_SIZE") or os.getenv("CMC_LISTINGS_PAGE_SIZE") or "5000"
    try:
        n = int(str(raw).strip().split()[0])
    except (TypeError, ValueError):
        n = 5000
    return max(1, min(n, 5000))


def _get_inter_page_sleep_seconds() -> float:
    raw = os.getenv("X-CMC_INTER_PAGE_SLEEP_SEC") or os.getenv("CMC_INTER_PAGE_SLEEP_SEC") or "1.5"
    try:
        s = float(str(raw).strip().split()[0])
    except (TypeError, ValueError):
        s = 1.5
    return max(0.0, s)


def _get_max_retries() -> int:
    raw = os.getenv("X-CMC_RETRY_MAX") or os.getenv("CMC_RETRY_MAX") or "5"
    try:
        n = int(str(raw).strip().split()[0])
    except (TypeError, ValueError):
        n = 5
    return max(0, min(n, 20))


def _get_retry_backoff_base_seconds() -> float:
    raw = (
        os.getenv("X-CMC_RETRY_BACKOFF_BASE_SEC")
        or os.getenv("CMC_RETRY_BACKOFF_BASE_SEC")
        or "2.0"
    )
    try:
        s = float(str(raw).strip().split()[0])
    except (TypeError, ValueError):
        s = 2.0
    return max(0.5, min(s, 300.0))


def _parse_retry_after_seconds(resp: requests.Response) -> Optional[float]:
    """Парсит Retry-After: секунды (int) или HTTP-date."""
    raw = (resp.headers.get("Retry-After") or "").strip()
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        pass
    try:
        dt = email.utils.parsedate_to_datetime(raw)
        if dt is None:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        now = datetime.now(dt.tzinfo)
        return max(0.0, (dt - now).total_seconds())
    except Exception:
        return None


def _backoff_sleep_seconds(attempt_idx: int) -> float:
    """Экспоненциальный backoff с потолком, если Retry-After нет."""
    base = _get_retry_backoff_base_seconds()
    return min(120.0, base * (2**attempt_idx))


def _http_get_json_with_retries(
    url: str,
    *,
    params: Dict[str, Any],
    api_keys: Sequence[str],
    timeout: float,
) -> Optional[dict]:
    """
    GET JSON; при 429 повторяет с уважением Retry-After или backoff.
    На каждой попытке (каждый requests.get) выбирается случайный ключ из api_keys.

    Возвращает None после исчерпания попыток без очистки кеша выше по стеку.
    """
    keys = list(api_keys)
    if not keys:
        return None

    max_retries = _get_max_retries()
    max_attempts = 1 + max_retries

    last_error: Optional[Exception] = None
    for attempt in range(max_attempts):
        try:
            headers = _http_headers_with_key(_pick_api_key(keys))
            resp = requests.get(url, params=params, headers=headers, timeout=timeout)

            if resp.status_code == 429:
                if attempt >= max_attempts - 1:
                    logger.error(
                        "CoinMarketCap listings: HTTP 429 после %d попыток (URL параметры замаскированы)",
                        max_attempts,
                    )
                    return None
                retry_after = _parse_retry_after_seconds(resp)
                wait_sec = retry_after if retry_after is not None else _backoff_sleep_seconds(
                    attempt
                )
                logger.warning(
                    "CoinMarketCap rate limited (429), следующая попытка через %.1f с (%d/%d)",
                    wait_sec,
                    attempt + 1,
                    max_attempts - 1,
                )
                time.sleep(wait_sec)
                continue

            resp.raise_for_status()
            return resp.json()

        except requests.RequestException as exc:
            last_error = exc
            if attempt >= max_attempts - 1:
                logger.error("Failed to fetch CoinMarketCap listings after retries: %s", exc)
                return None
            wait_sec = _backoff_sleep_seconds(attempt)
            logger.warning(
                "CoinMarketCap request failed (%s), retry in %.1f s (%d/%d)",
                exc,
                wait_sec,
                attempt + 1,
                max_attempts - 1,
            )
            time.sleep(wait_sec)

    if last_error:
        logger.error("Failed to fetch CoinMarketCap listings: %s", last_error)
    return None


def _merge_listing_payload_to_ranks(new_ranks: Dict[str, int], data: Any) -> None:
    """Добавляет symbol -> cmc_rank из списка data."""
    if not isinstance(data, list):
        return
    for item in data:
        try:
            symbol = str(item.get("symbol") or "").upper()
            rank = item.get("cmc_rank")
            if not symbol or not isinstance(rank, int):
                continue
            new_ranks[symbol] = rank
        except Exception:
            continue


def _fetch_and_update_cmc_ranks() -> None:
    api_keys = _get_env_api_keys()
    if not api_keys:
        logger.warning("CoinMarketCap API key is not set; skipping CMC rank update")
        return

    page_size = _get_listings_page_size()
    inter_page_sleep = _get_inter_page_sleep_seconds()

    new_ranks: Dict[str, int] = {}
    start = 1

    try:
        while True:
            params = {
                "start": start,
                "limit": page_size,
                "convert": "USD",
            }
            payload = _http_get_json_with_retries(
                _LISTINGS_URL,
                params=params,
                api_keys=api_keys,
                timeout=30.0,
            )
            if payload is None:
                return

            data = payload.get("data") or []
            if not isinstance(data, list):
                logger.error("Unexpected CoinMarketCap payload format: %r", type(data))
                return

            _merge_listing_payload_to_ranks(new_ranks, data)

            if len(data) < page_size:
                break
            start += page_size
            if inter_page_sleep > 0:
                time.sleep(inter_page_sleep)

    except Exception as exc:
        logger.error("Failed to fetch CoinMarketCap listings: %s", exc)
        return

    if not new_ranks:
        logger.warning("CoinMarketCap returned empty ranks list")
        return

    with _CMC_LOCK:
        _CMC_RANKS.clear()
        _CMC_RANKS.update(new_ranks)

    global _CMC_INITIAL_FETCH_DONE
    _CMC_INITIAL_FETCH_DONE = True

    logger.info("CoinMarketCap ranks updated, %d entries", len(new_ranks))


def _updater_loop() -> None:
    while True:
        interval = _get_update_interval_seconds()
        jitter = random.uniform(0.0, interval * 0.05)
        try:
            _fetch_and_update_cmc_ranks()
        except Exception as exc:
            logger.exception("Unhandled error in CMC updater loop: %s", exc)
        time.sleep(interval + jitter)


def _ensure_thread_started() -> None:
    global _CMC_THREAD_STARTED
    if _CMC_THREAD_STARTED:
        return
    _CMC_THREAD_STARTED = True
    t = threading.Thread(target=_updater_loop, name="cmc-rank-updater", daemon=True)
    t.start()


def init_cmc_rank_cache() -> None:
    """
    Инициализировать кеш: блокирующий первый запрос + запуск фонового обновления.
    Вызывать как можно раньше при старте приложения.
    """
    _fetch_and_update_cmc_ranks()
    _ensure_thread_started()


def _extract_base_symbol(symbol: str) -> str:
    """
    Грубый, но практичный разбор тикера в базовый символ для CMC.
    BTCUSDT, BTC/USDT, BTC-USDT, BTCUSDT.P, BTCUSDT_PERP → BTC
    """
    s = symbol.upper().strip()
    for sep in ("/", "-", "_"):
        s = s.replace(sep, "")
    for suf in ("PERP", "F0", "FUT", "P"):
        if s.endswith(suf) and len(s) > len(suf) + 1:
            s = s[: -len(suf)]
    suffixes = (
        "USDT",
        "USD",
        "USDC",
        "FDUSD",
        "BUSD",
        "EUR",
        "BTC",
        "ETH",
    )
    for suf in suffixes:
        if s.endswith(suf) and len(s) > len(suf):
            return s[: -len(suf)]
    return s


def get_cmc_rank_for_symbol(symbol: str) -> Optional[int]:
    """
    Быстрый доступ к кешу рангов.
    Возвращает None, если данных нет (ошибка запроса, ещё не успели обновиться и т.п.).
    """
    base = _extract_base_symbol(symbol)
    with _CMC_LOCK:
        rank = _CMC_RANKS.get(base)
    return rank
