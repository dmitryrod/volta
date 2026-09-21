"""In-memory снимки метрик сервера для страницы «Система» и API `/admin_api/monitoring/metrics`."""

from __future__ import annotations

import os
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any

import psutil

from app.config import logger

# ~5 мин при опросе 1 Гц
_SERIES_MAXLEN = 300
# 24 ч поминутно
_DIR_SERIES_MAXLEN = 1440
# Кэш размера каталога, полный walk не чаще
_DIR_SCAN_MIN_INTERVAL_SEC = 60.0
# «Устаревшие» данные, если давно не было успешного снимка
_STALE_AFTER_SEC = 5.0

_EXCLUDE_DIR_NAMES = frozenset(
    {".git", "__pycache__", "node_modules", ".venv", "venv", ".mypy_cache", "dist", ".tox"}
)


def _default_app_root() -> Path:
    """Каталог пакета `app/` (родитель `app.admin`)."""
    return Path(__file__).resolve().parents[1]


def reset_state_for_tests() -> None:
    """Сбрасывает буферы и кэш. Только для тестов."""
    with _SnapshotState.lock:
        _SnapshotState.cpu_warmup_done = False
        _SnapshotState.cpu_series.clear()
        _SnapshotState.memory_series.clear()
        _SnapshotState.disk_series.clear()
        _SnapshotState.dir_series.clear()
        _SnapshotState.app_dir_bytes = None
        _SnapshotState._last_dir_scan_monotonic = 0.0
        _SnapshotState.last_values = {}
        _SnapshotState.memory_total = 0
        _SnapshotState.memory_used = 0
        _SnapshotState.disk_total = 0
        _SnapshotState.disk_used = 0
        _SnapshotState.last_boot_time = ""
        _SnapshotState.last_ok_time = 0.0
        _SnapshotState.last_error = None


def get_monitored_dir() -> Path:
    """Корневая директория для метрики размера: `MONITORING_APP_DIR` или каталог `app/`."""
    override = (os.environ.get("MONITORING_APP_DIR") or "").strip()
    if override:
        return Path(override).resolve()
    return _default_app_root()


def _dir_size_bytes(root: Path) -> int:
    """Суммарный размер файлов под `root` (с пропуском типичных тяжёлых подкаталогов)."""
    total = 0
    if not root.is_dir():
        return 0
    for dirpath, dirnames, filenames in os.walk(root, topdown=True, followlinks=False):
        dirnames[:] = [d for d in dirnames if d not in _EXCLUDE_DIR_NAMES]
        for name in filenames:
            fp = os.path.join(dirpath, name)
            try:
                total += os.path.getsize(fp)
            except OSError:
                pass
    return total


def _metr_psutil_values() -> tuple[Any, Any, float, str]:
    """Снимок psutil: память, диск, CPU% (неблокирующий), строка boot time."""
    memory = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    if not _SnapshotState.cpu_warmup_done:
        psutil.cpu_percent(interval=None)
        _SnapshotState.cpu_warmup_done = True
    cpu_percent = float(psutil.cpu_percent(interval=None))
    boot_time = datetime.fromtimestamp(psutil.boot_time()).strftime("%Y-%m-%d %H:%M:%S")
    return memory, disk, cpu_percent, boot_time


class _SnapshotState:
    """Глобальное состояние (один процесс uvicorn / один worker)."""

    lock = threading.Lock()
    cpu_warmup_done = False

    cpu_series: deque[tuple[float, float]] = deque(maxlen=_SERIES_MAXLEN)
    memory_series: deque[tuple[float, float]] = deque(maxlen=_SERIES_MAXLEN)
    disk_series: deque[tuple[float, float]] = deque(maxlen=_SERIES_MAXLEN)

    dir_series: deque[tuple[float, float]] = deque(maxlen=_DIR_SERIES_MAXLEN)
    app_dir_bytes: int | None = None
    _last_dir_scan_monotonic: float = 0.0

    last_values: dict[str, float] = {}
    memory_total: int = 0
    memory_used: int = 0
    disk_total: int = 0
    disk_used: int = 0
    last_boot_time: str = ""
    last_ok_time: float = 0.0
    last_error: str | None = None


def _series_to_json(deq: deque[tuple[float, float]]) -> list[dict[str, float]]:
    return [{"t": t, "v": v} for t, v in deq]


def record_snapshot(*, scan_app_directory: bool = True) -> None:
    """Собирает снимок, дописывает кольцевые буферы. Вызывать из thread pool (sync).

    Args:
        scan_app_directory: Если False — не выполнять ``os.walk`` по каталогу приложения
            (тяжёлый шаг). Используется для дашборда / TTL-сводки: метрики CPU/RAM/диска
            обновляются, размер ``app/`` берётся из последнего успешного скана (или «Система»
            / polling ``/admin_api/monitoring/metrics`` дополнит позже).

    Узкие места по времени ответа дашборда (типично): полный ``COUNT(*)`` по большой таблице
    ``signals`` без pg_stat; полный walk каталога при первом запросе; последовательные round-trip
    к Postgres. См. ``app/admin/dashboard_summary.py`` (один SQL-агрегат, estimate через
    pg_stat, ``scan_app_directory=False`` для SSR/API сводки).
    """
    now = time.time()
    with _SnapshotState.lock:
        try:
            memory, disk, cpu_percent, boot_time = _metr_psutil_values()
            _SnapshotState.last_boot_time = boot_time
            _SnapshotState.last_values = {
                "cpu": cpu_percent,
                "memory": float(memory.percent),
                "disk": float(disk.percent),
            }
            _SnapshotState.memory_total = int(memory.total)
            _SnapshotState.memory_used = int(memory.used)
            _SnapshotState.disk_total = int(disk.total)
            _SnapshotState.disk_used = int(disk.used)
            _SnapshotState.cpu_series.append((now, cpu_percent))
            _SnapshotState.memory_series.append((now, float(memory.percent)))
            _SnapshotState.disk_series.append((now, float(disk.percent)))
            _SnapshotState.last_ok_time = now
            _SnapshotState.last_error = None
        except Exception as exc:  # noqa: BLE001 — хотим last good values
            err = f"{type(exc).__name__}: {exc}"
            _SnapshotState.last_error = err
            logger.warning("monitoring snapshot failed: {}", err)

        if not scan_app_directory:
            return

        # Размер каталога: не чаще 60 с; поминутная точка — при новом полном скане
        mon = time.monotonic()
        if mon - _SnapshotState._last_dir_scan_monotonic >= _DIR_SCAN_MIN_INTERVAL_SEC or (
            _SnapshotState.app_dir_bytes is None
        ):
            _SnapshotState._last_dir_scan_monotonic = mon
            try:
                size_b = _dir_size_bytes(get_monitored_dir())
                _SnapshotState.app_dir_bytes = size_b
                _SnapshotState.dir_series.append((time.time(), float(size_b)))
            except Exception as exc:  # noqa: BLE001
                logger.warning("monitoring dir size failed: {}", exc)
                if _SnapshotState.app_dir_bytes is None:
                    _SnapshotState.app_dir_bytes = 0


def record_snapshot_for_dashboard() -> None:
    """Снимок без обхода дерева каталога — быстрый путь для главной админки."""
    record_snapshot(scan_app_directory=False)


def get_payload() -> dict[str, Any]:
    """JSON для API: текущие числа, серии, stale, boot_time, ошибка (если была)."""
    now = time.time()
    with _SnapshotState.lock:
        err = _SnapshotState.last_error
        last_ok = _SnapshotState.last_ok_time
        stale = (now - last_ok) > _STALE_AFTER_SEC if last_ok else True

        payload: dict[str, Any] = {
            "server_time": now,
            "stale": stale,
            "boot_time": _SnapshotState.last_boot_time,
            "cpu": _SnapshotState.last_values.get("cpu"),
            "memory_percent": _SnapshotState.last_values.get("memory"),
            "disk_percent": _SnapshotState.last_values.get("disk"),
            "cpu_series": _series_to_json(_SnapshotState.cpu_series),
            "memory_series": _series_to_json(_SnapshotState.memory_series),
            "disk_series": _series_to_json(_SnapshotState.disk_series),
            "app_dir_bytes": _SnapshotState.app_dir_bytes,
            "app_dir_series": _series_to_json(_SnapshotState.dir_series),
        }
        if err:
            payload["error"] = err
        return payload


def get_template_context() -> dict[str, Any]:
    """Контекст Jinja для первой отрисовки (согласован с API после record_snapshot)."""
    with _SnapshotState.lock:
        cpu = _SnapshotState.last_values.get("cpu")
        mem = _SnapshotState.last_values.get("memory")
        dsk = _SnapshotState.last_values.get("disk")
        m_total = _SnapshotState.memory_total
        m_used = _SnapshotState.memory_used
        d_total = _SnapshotState.disk_total
        d_used = _SnapshotState.disk_used
        boot = _SnapshotState.last_boot_time
        stale = (time.time() - _SnapshotState.last_ok_time) > _STALE_AFTER_SEC
        if not _SnapshotState.last_ok_time:
            stale = True
        app_dir = _SnapshotState.app_dir_bytes

    cpu = float(cpu) if cpu is not None else 0.0
    mem = float(mem) if mem is not None else 0.0
    dsk = float(dsk) if dsk is not None else 0.0
    app_dir_str = _format_bytes(int(app_dir)) if app_dir is not None else "—"

    return {
        "cpu_percent": f"{cpu:.0f}%",
        "cpu_val": cpu,
        "memory_percent": f"{mem:.0f}%",
        "mem_val": mem,
        "memory_total": f"{m_total / (1024**3):.2f} GB" if m_total else "—",
        "memory_used": f"{m_used / (1024**3):.2f} GB" if m_used else "—",
        "disk_percent": f"{dsk:.0f}%",
        "disk_val": dsk,
        "disk_total": f"{d_total / (1024**3):.2f} GB" if d_total else "—",
        "disk_used": f"{d_used / (1024**3):.2f} GB" if d_used else "—",
        "boot_time": boot or "—",
        "app_dir_size": app_dir_str,
        "metrics_stale": stale,
    }


def _format_bytes(n: int) -> str:
    if n < 0:
        return "—"
    if n < 1024:
        return f"{n} B"
    x = float(n)
    for unit in ("KB", "MB", "GB", "TB"):
        x /= 1024.0
        if x < 1024.0 or unit == "TB":
            return f"{x:.2f} {unit}"
    return f"{x:.2f} PB"
