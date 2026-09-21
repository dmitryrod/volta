"""Агрегированные данные для главной страницы админки (дашборд).

Производительность (типичные узкие места TTFB):

- Полный ``COUNT(*)`` по большой таблице ``signals`` — см. pg_stat estimate и один SQL-батч.
- ``os.walk`` размера каталога ``app/`` — для сводки используется ``record_snapshot_for_dashboard``
  (без walk; последнее значение из предыдущих снимков / страницы «Система»).
- Последовательные round-trip к Postgres — сведены к одному агрегирующему запросу + GROUP BY статусов.

In-memory TTL-кэш (несколько секунд) снижает нагрузку при частых F5; сбрасывается при рестарте воркера.
"""

from __future__ import annotations

import asyncio
import copy
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import Database
from app.database.models import (
    ScannerRuntimeSettingsORM,
    TrackingSessionORM,
)

from .monitoring_metrics import get_payload, record_snapshot_for_dashboard
from .pg_counts import signals_total_with_source

DEFAULT_SCANNER_RUNTIME: dict[str, Any] = {
    "max_cards": 10,
    "posttracking_minutes": 30,
    "cooldown_hours": 24,
    "statistics_enabled": True,
}

_DASHBOARD_CACHE_TTL_SEC = 5.0
_dashboard_cache_monotonic: float = 0.0
_dashboard_cache_payload: dict[str, Any] | None = None

_DASHBOARD_AGG_SQL = text(
    """
    SELECT
      (SELECT COUNT(*)::bigint FROM settings) AS sc_total,
      (SELECT COUNT(*)::bigint FROM settings WHERE enabled IS TRUE) AS sc_enabled,
      (SELECT COUNT(*)::bigint FROM settings WHERE debug IS TRUE) AS sc_debug,
      (SELECT COUNT(*)::bigint FROM signals WHERE created_at >= :cutoff) AS sig_24h,
      (SELECT COUNT(*)::bigint FROM signals WHERE created_at >= :cutoff AND telegram_ok IS TRUE)
        AS sig_ok,
      (SELECT COUNT(*)::bigint FROM signals WHERE created_at >= :cutoff AND telegram_ok IS FALSE)
        AS sig_fail,
      (SELECT COUNT(*)::bigint FROM tracking_sessions) AS ts_total,
      (SELECT n_live_tup::bigint FROM pg_stat_user_tables
         WHERE relname = 'signals' AND schemaname = current_schema() LIMIT 1) AS sig_live_est
    """
)


def monitoring_subset_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Узкий срез метрик процесса для дашборда (контракт API и тестов)."""
    keys = (
        "cpu",
        "memory_percent",
        "disk_percent",
        "stale",
        "server_time",
        "app_dir_bytes",
        "error",
    )
    out: dict[str, Any] = {}
    for k in keys:
        if k in payload:
            out[k] = payload[k]
    return out


def invalidate_dashboard_cache() -> None:
    """Сброс TTL-кэша сводки (тесты или будущая явная инвалидация)."""
    global _dashboard_cache_payload, _dashboard_cache_monotonic
    _dashboard_cache_payload = None
    _dashboard_cache_monotonic = 0.0


async def _fetch_aggregate_row(
    session: AsyncSession, cutoff: datetime
) -> dict[str, Any]:
    """Один round-trip: счётчики скринеров, сигналов за сутки, сессий, estimate для signals."""
    row = (await session.execute(_DASHBOARD_AGG_SQL, {"cutoff": cutoff})).mappings().first()
    if row is None:
        raise RuntimeError("dashboard aggregate query returned no row")
    d = dict(row)

    raw_est = d.get("sig_live_est")
    if raw_est is not None and int(raw_est) > 0:
        d["sig_total"] = int(raw_est)
        d["sig_total_source"] = "estimate"
    else:
        total, src = await signals_total_with_source(session)
        d["sig_total"] = total
        d["sig_total_source"] = src

    return d


async def build_dashboard_summary(*, use_cache: bool = True) -> dict[str, Any]:
    """Собирает сводку для `/admin/` и `GET /admin_api/dashboard/summary`.

    Args:
        use_cache: Если True — при повторном запросе в пределах TTL вернуть копию кэша в памяти процесса.

    Returns:
        JSON-сериализуемый dict; поле ``signals.total_source`` — ``estimate`` | ``exact``.
    """
    global _dashboard_cache_monotonic, _dashboard_cache_payload

    now_m = time.monotonic()
    if (
        use_cache
        and _dashboard_cache_payload is not None
        and (now_m - _dashboard_cache_monotonic) < _DASHBOARD_CACHE_TTL_SEC
    ):
        return copy.deepcopy(_dashboard_cache_payload)

    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)

    async with Database.session_context() as db:
        agg_row, _ = await asyncio.gather(
            _fetch_aggregate_row(db.session, cutoff),
            asyncio.to_thread(record_snapshot_for_dashboard),
        )

        status_rows = (
            await db.session.execute(
                select(TrackingSessionORM.status, func.count()).group_by(
                    TrackingSessionORM.status
                )
            )
        ).all()
        sessions_by_status = {str(row[0]): int(row[1]) for row in status_rows}

        rt_row = await db.session.get(ScannerRuntimeSettingsORM, 1)

    monitoring = monitoring_subset_from_payload(get_payload())

    if rt_row is None:
        scanner_runtime = dict(DEFAULT_SCANNER_RUNTIME)
    else:
        scanner_runtime = {
            "max_cards": rt_row.max_cards,
            "posttracking_minutes": rt_row.posttracking_minutes,
            "cooldown_hours": rt_row.cooldown_hours,
            "statistics_enabled": rt_row.statistics_enabled,
        }

    result: dict[str, Any] = {
        "screeners": {
            "total": int(agg_row["sc_total"] or 0),
            "enabled": int(agg_row["sc_enabled"] or 0),
            "debug_enabled": int(agg_row["sc_debug"] or 0),
        },
        "signals": {
            "total": int(agg_row["sig_total"]),
            "total_source": str(agg_row["sig_total_source"]),
            "last_24h": int(agg_row["sig_24h"] or 0),
            "telegram_ok_24h": int(agg_row["sig_ok"] or 0),
            "telegram_fail_24h": int(agg_row["sig_fail"] or 0),
        },
        "analytics": {
            "sessions_total": int(agg_row["ts_total"] or 0),
            "sessions_by_status": sessions_by_status,
        },
        "scanner_runtime": scanner_runtime,
        "monitoring": monitoring,
    }

    _dashboard_cache_monotonic = time.monotonic()
    _dashboard_cache_payload = copy.deepcopy(result)

    return result
