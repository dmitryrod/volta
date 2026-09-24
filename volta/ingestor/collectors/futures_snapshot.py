"""Futures price snapshot collector."""

from __future__ import annotations

from datetime import datetime, timezone

from unicex import Exchange

from volta.config import config
from volta.ingestor.collectors.abstract import Collector
from volta.ingestor.writer import SnapshotWriter
from volta.utils.connectivity import is_transient_network_error, wait_for_internet


class FuturesSnapshotCollector(Collector):
    """Poll futures last prices for all enabled bases."""

    def __init__(self, writer: SnapshotWriter, exchange_name: str = "bybit") -> None:
        exchange = Exchange.BYBIT if exchange_name == "bybit" else Exchange.BYBIT
        super().__init__(exchange, "futures_snapshot")
        self._writer = writer
        self._interval = config.ingestor.interval_sec

    async def start(self) -> None:
        await wait_for_internet(log_name="futures-collector")
        while self._is_running:
            try:
                await self._collect_once()
                self._mark_updated()
            except Exception as exc:
                if is_transient_network_error(exc):
                    self._logger.warning("Transient error in futures collector: {}", exc)
                    await wait_for_internet(log_name="futures-collector")
                else:
                    self._logger.exception("Futures collector error: {}", exc)
            await self._safe_sleep(self._interval)

    async def _collect_once(self) -> None:
        assets = await self._writer.get_enabled_assets()
        if not assets:
            return
        ts = datetime.now(timezone.utc)
        async with self._client_context() as client:
            prices = await client.futures_last_price()
            rows = []
            for asset in assets:
                symbol = asset.futures_symbol
                price = prices.get(symbol)
                if price is None:
                    self._logger.warning("No futures price for {}", symbol)
                    continue
                rows.append(
                    {
                        "ts": ts,
                        "base_asset": asset.base_asset,
                        "exchange": config.ingestor.exchange,
                        "market": "linear",
                        "symbol": symbol,
                        "metric": "last_price",
                        "value": float(price),
                        "meta_json": None,
                    }
                )
            await self._writer.write_instruments(rows)
