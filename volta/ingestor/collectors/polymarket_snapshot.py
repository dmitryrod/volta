"""Polymarket multi-strike snapshot collector."""

from __future__ import annotations

from typing import Any

from unicex import Exchange

from volta.config import config
from volta.database import Database
from volta.database.repositories.snapshot_repository import _utc_now
from volta.ingestor.collectors.abstract import Collector
from volta.ingestor.writer import SnapshotWriter
from volta.polymarket import GammaClient
from volta.utils.connectivity import is_transient_network_error, wait_for_internet


class PolymarketSnapshotCollector(Collector):
    """Poll Polymarket Gamma API for all catalog events per base."""

    def __init__(self, writer: SnapshotWriter) -> None:
        super().__init__(Exchange.BYBIT, "polymarket")
        self._writer = writer
        self._interval = config.ingestor.interval_sec
        self._retention = config.polymarket.retention_hours_after_expiry

    async def start(self) -> None:
        self._logger.info("Polymarket collector started")
        while self._is_running:
            try:
                await self._poll_once()
                self._mark_updated()
            except Exception as exc:
                if is_transient_network_error(exc):
                    self._logger.warning("Transient error: {}", exc)
                    await wait_for_internet(log_name="polymarket-collector")
                else:
                    self._logger.error("Poll failed ({}): {}", type(exc).__name__, exc)
            await self._safe_sleep(self._interval)

    async def _poll_once(self) -> None:
        assets = await self._writer.get_enabled_assets()
        ts = _utc_now()
        async with GammaClient() as client:
            for asset in assets:
                async with Database.session_context() as db:
                    events = await db.snapshots.list_polymarket_events(
                        asset.base_asset, self._retention, ts
                    )
                if not events:
                    continue
                panel = await self._latest_spot(asset.base_asset)
                if panel is None:
                    self._logger.debug("No spot for {}, skip PM", asset.base_asset)
                    continue
                spot = float(panel.futures_price or 0)
                if spot <= 0:
                    continue
                for event in events:
                    slug = event.event_slug
                    try:
                        event_title, strikes = await client.fetch_strikes_for_event(
                            slug, spot
                        )
                    except Exception as exc:
                        self._logger.warning(
                            "PM fetch failed for {} ({}): {}",
                            asset.base_asset,
                            slug,
                            exc,
                        )
                        continue
                    if not strikes:
                        self._logger.warning(
                            "No strikes selected for {} / {}", asset.base_asset, slug
                        )
                        continue
                    title = event.event_title or event_title
                    for strike in strikes:
                        row: dict[str, Any] = {
                            "ts": ts,
                            "base_asset": asset.base_asset,
                            "market_id": strike.market_id,
                            "question": strike.question,
                            "yes_probability": strike.yes_probability,
                            "meta_json": {
                                "strike": strike.strike,
                                "event_slug": slug,
                                "event_title": title,
                                "market_slug": strike.slug,
                            },
                        }
                        await self._writer.write_polymarket(row)
                    self._logger.debug(
                        "PM {} / {}: {} strikes @ spot {:.2f}",
                        asset.base_asset,
                        slug,
                        len(strikes),
                        spot,
                    )

        await self._writer.purge_expired_polymarket(ts, self._retention)

    async def _latest_spot(self, base_asset: str) -> Any:
        async with Database.session_context() as db:
            return await db.snapshots.get_latest_panel(base_asset)
