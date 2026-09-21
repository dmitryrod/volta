from __future__ import annotations

import os
import threading
from pathlib import Path

from datetime import timezone as dt_timezone

from loguru import logger as _loguru_root

from .moscow_rotating import (
    MOSCOW_TZ,
    prune_timestamped_archives,
    rotate_file_to_timestamped_archive,
)

_APP_DIR = Path(__file__).resolve().parents[1]


def _load_dotenv_from_app_dir() -> bool:
    """Подставляет в os.environ ключи из app/.env, если их ещё нет (как python-dotenv).

    Без зависимости dotenv: при локальном `uvicorn` переменные из .env иначе не видны;
    в Docker env_file уже задаёт окружение до старта процесса.
    """
    path = _APP_DIR / ".env"
    if not path.is_file():
        return False
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return False
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        if not key or key in os.environ:
            continue
        val = val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
            val = val[1:-1]
        os.environ[key] = val
    return True


_load_dotenv_from_app_dir()

_LOGURU_LEVELS = frozenset(
    {"TRACE", "DEBUG", "INFO", "SUCCESS", "WARNING", "ERROR", "CRITICAL"}
)
_raw_level = os.getenv("LOG_LEVEL", "INFO").strip().upper()
LOG_LEVEL = _raw_level if _raw_level in _LOGURU_LEVELS else "INFO"

LOG_DIR = _APP_DIR / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

_APP_LOG_PATH = LOG_DIR / "app.log"
_APP_LOG_MAX_BYTES = 10 * 1024 * 1024
_APP_LOG_MAX_ARCHIVES = 10
_app_log_sink_lock = threading.Lock()


def _patch_record_time_moscow(record: dict) -> None:
    """Loguru: naive/UTC время записи → Europe/Moscow для поля {time} в format."""
    t = record["time"]
    if t.tzinfo is None:
        t = t.replace(tzinfo=dt_timezone.utc)
    record["time"] = t.astimezone(MOSCOW_TZ)


def _moscow_app_log_sink(message: str) -> None:
    """Ротация как у signals_log: архивы ``app.YYYY-MM-DD_HH-MM-SS_usecs.log`` (Москва)."""
    data = message.encode("utf-8", errors="replace")
    with _app_log_sink_lock:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        cur = _APP_LOG_PATH.stat().st_size if _APP_LOG_PATH.exists() else 0
        if cur + len(data) > _APP_LOG_MAX_BYTES:
            try:
                if _APP_LOG_PATH.stat().st_size > 0:
                    rotate_file_to_timestamped_archive(
                        _APP_LOG_PATH,
                        archive_stem=_APP_LOG_PATH.stem,
                        archive_suffix=_APP_LOG_PATH.suffix,
                    )
                prune_timestamped_archives(
                    LOG_DIR,
                    archive_stem=_APP_LOG_PATH.stem,
                    archive_suffix=_APP_LOG_PATH.suffix,
                    max_archives=_APP_LOG_MAX_ARCHIVES,
                )
            except OSError:
                pass
        with _APP_LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(message)


_LOGURU_APP = _loguru_root


def _configure_loguru() -> None:
    global _LOGURU_APP
    _loguru_root.remove()
    _LOGURU_APP = _loguru_root.patch(_patch_record_time_moscow)
    _LOGURU_APP.add(
        _moscow_app_log_sink,
        level=LOG_LEVEL,
        enqueue=True,
        backtrace=True,
        diagnose=False,
        format="{time:YYYY-MM-DD HH:mm:ss.SSS}|{level}| {message}\n",
    )


_configure_loguru()


def get_logger(name: str | None = None):
    """Возвращает объект логгера loguru."""
    if name:
        return _LOGURU_APP.bind(logger=name)
    return _LOGURU_APP


logger = get_logger()

