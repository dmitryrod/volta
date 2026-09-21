"""Ротация логов: суффикс с датой/временем по Europe/Moscow, обрезка старых архивов."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

MOSCOW_TZ = ZoneInfo("Europe/Moscow")


def moscow_file_timestamp() -> str:
    """Строка для имени архива: YYYY-MM-DD_HH-MM-SS_microseconds (6 цифр)."""
    now = datetime.now(MOSCOW_TZ)
    return now.strftime("%Y-%m-%d_%H-%M-%S_") + f"{now.microsecond:06d}"


def moscow_iso_timestamp() -> str:
    """ISO-подобная метка с оффсетом Москвы для строк логов."""
    return datetime.now(MOSCOW_TZ).isoformat(timespec="milliseconds")


def rotate_file_to_timestamped_archive(
    base_file: Path,
    *,
    archive_stem: str,
    archive_suffix: str,
) -> Path:
    """
    Переименовывает base_file в ``{archive_stem}.{moscow_ts}{archive_suffix}``.
    Возвращает путь к архиву.
    """
    dest = base_file.parent / f"{archive_stem}.{moscow_file_timestamp()}{archive_suffix}"
    base_file.rename(dest)
    return dest


def prune_timestamped_archives(
    directory: Path,
    *,
    archive_stem: str,
    archive_suffix: str,
    max_archives: int,
) -> None:
    """
    Удаляет самые старые архивы вида ``{archive_stem}.{ts}{archive_suffix}``,
    оставляя не больше max_archives файлов (по mtime).
    """
    if max_archives < 0:
        return
    candidates: list[Path] = []
    prefix = f"{archive_stem}."
    for p in directory.iterdir():
        if not p.is_file():
            continue
        if not p.name.startswith(prefix) or not p.name.endswith(archive_suffix):
            continue
        rest = p.name[len(prefix) : -len(archive_suffix)]
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}_\d{6}", rest):
            continue
        candidates.append(p)
    candidates.sort(key=lambda x: x.stat().st_mtime)
    while len(candidates) > max_archives:
        oldest = candidates.pop(0)
        try:
            oldest.unlink()
        except OSError:
            pass
