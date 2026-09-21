"""REST backfill of closed futures candles on startup."""

from __future__ import annotations

from typing import Any

from loguru import logger
from unicex import Exchange, get_uni_client

from app_options.config.chart_intervals import (
    CHART_INTERVALS,
    MAX_CLOSED_CANDLES_PER_SERIES,
    chart_interval_to_bybit,
)
from app_options.database import Database
from app_options.database.models import AssetConfig
from app_options.ingestor.kline_hub import current_bucket_open_time, get_kline_hub


class KlineBackfillService:
    """Load missing closed candles from exchange REST."""

    async def run_for_assets(self, assets: list[AssetConfig]) -> None:
        """Backfill all enabled assets and chart intervals."""
        if not assets:
            return
        client = await get_uni_client(Exchange.BYBIT).create()
        async with client:
            for asset in assets:
                for interval in CHART_INTERVALS:
                    try:
                        await self._backfill_series(
                            client,
                            asset.base_asset,
                            asset.futures_symbol,
                            interval,
                        )
                    except Exception as exc:
                        logger.exception(
                            "Backfill failed for {} {}: {}",
                            asset.base_asset,
                            interval,
                            exc,
                        )

    async def _backfill_series(
        self,
        client: Any,
        base_asset: str,
        symbol: str,
        interval: str,
    ) -> None:
        bybit_interval = chart_interval_to_bybit(interval)
        async with Database.session_context() as db:
            max_open = await db.candles.max_open_time(base_asset, interval)

        raw = await client.futures_klines(
            symbol=symbol,
            interval=bybit_interval,
            limit=MAX_CLOSED_CANDLES_PER_SERIES,
        )
        if not raw:
            return

        current_open = current_bucket_open_time(interval)
        closed_rows: list[dict[str, Any]] = []
        forming: dict[str, Any] | None = None

        for k in raw:
            open_sec = int(k["t"]) // 1000
            row = {
                "base_asset": base_asset,
                "interval": interval,
                "open_time": open_sec,
                "open": float(k["o"]),
                "high": float(k["h"]),
                "low": float(k["l"]),
                "close": float(k["c"]),
                "volume": float(k["v"]) if k.get("v") is not None else None,
            }
            if open_sec >= current_open:
                forming = row
                continue
            if max_open is not None and open_sec <= max_open:
                continue
            closed_rows.append(row)

        async with Database.session_context() as db:
            if closed_rows:
                await db.candles.bulk_upsert_closed(closed_rows)
                await db.candles.prune_older_than(
                    base_asset, interval, MAX_CLOSED_CANDLES_PER_SERIES
                )

        if forming is not None:
            hub = get_kline_hub()
            from app_options.ingestor.kline_hub import LiveCandle

            hub.set_live(
                base_asset,
                interval,
                LiveCandle(
                    time=int(forming["open_time"]),
                    open=float(forming["open"]),
                    high=float(forming["high"]),
                    low=float(forming["low"]),
                    close=float(forming["close"]),
                    volume=forming.get("volume"),
                ),
            )

        logger.info(
            "Backfill {} {}: inserted {} closed candles",
            base_asset,
            interval,
            len(closed_rows),
        )
