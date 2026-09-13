"""Bybit multiplex kline WebSocket collector."""

from __future__ import annotations

import json
from typing import Any

from unicex import Exchange, Websocket
from unicex.bybit.adapter import Adapter

from app_options.config.chart_intervals import (
    CHART_INTERVALS,
    bybit_interval_to_chart,
    chart_interval_to_bybit,
    parse_kline_topic,
)
from app_options.ingestor.collectors.abstract import Collector
from app_options.ingestor.kline_backfill import KlineBackfillService
from app_options.ingestor.kline_hub import get_kline_hub
from app_options.ingestor.writer import SnapshotWriter

_BYBIT_LINEAR_WS = "wss://stream.bybit.com/v5/public/linear"


class KlineWsCollector(Collector):
    """Subscribe all chart intervals and symbols on one Bybit WS."""

    def __init__(self, writer: SnapshotWriter, exchange_name: str = "bybit") -> None:
        exchange = Exchange.BYBIT if exchange_name == "bybit" else Exchange.BYBIT
        super().__init__(exchange, "kline_ws")
        self._writer = writer
        self._websocket: Websocket | None = None
        self._symbol_to_base: dict[str, str] = {}
        self._backfill = KlineBackfillService()

    async def start(self) -> None:
        assets = await self._writer.get_enabled_assets()
        self._symbol_to_base = {
            a.futures_symbol.upper(): a.base_asset for a in assets
        }
        await self._backfill.run_for_assets(assets)
        topics = self._build_topics(assets)
        if not topics:
            self._logger.warning("No kline topics to subscribe")
            return

        subscription = [json.dumps({"op": "subscribe", "args": topics})]
        self._websocket = Websocket(
            callback=self._on_ws_message,
            url=_BYBIT_LINEAR_WS,
            subscription_messages=subscription,
        )
        try:
            await self._websocket.start()
        except Exception as exc:
            if self._is_running:
                self._logger.exception("Kline WS error: {}", exc)
                raise

    async def stop(self) -> None:
        self._is_running = False
        if self._websocket and self._websocket.running:
            await self._websocket.stop()

    def _build_topics(self, assets: list[Any]) -> list[str]:
        topics: list[str] = []
        for interval in CHART_INTERVALS:
            bybit_iv = chart_interval_to_bybit(interval)
            for asset in assets:
                topics.append(f"kline.{bybit_iv}.{asset.futures_symbol.upper()}")
        return topics

    async def _on_ws_message(self, raw_msg: dict[str, Any]) -> None:
        if raw_msg.get("op") == "subscribe":
            return
        topic = raw_msg.get("topic")
        if not topic or not str(topic).startswith("kline."):
            return
        try:
            bybit_iv, symbol = parse_kline_topic(str(topic))
        except ValueError:
            return
        chart_interval = bybit_interval_to_chart(bybit_iv)
        if chart_interval is None:
            return
        base = self._symbol_to_base.get(symbol.upper())
        if base is None:
            return

        for kline in Adapter.Klines_message(raw_msg):
            open_sec = int(kline["t"]) // 1000
            confirmed = bool(kline.get("x"))
            hub = get_kline_hub()
            await hub.apply_ws_update(
                base,
                chart_interval,
                open_sec,
                float(kline["o"]),
                float(kline["h"]),
                float(kline["l"]),
                float(kline["c"]),
                float(kline["v"]) if kline.get("v") is not None else None,
                confirmed,
            )
            if confirmed:
                from app_options.database import Database

                async with Database.session_context() as db:
                    await db.candles.upsert_closed_candle(
                        base,
                        chart_interval,
                        open_sec,
                        float(kline["o"]),
                        float(kline["h"]),
                        float(kline["l"]),
                        float(kline["c"]),
                        float(kline["v"]) if kline.get("v") is not None else None,
                    )
                    await db.candles.prune_older_than(base, chart_interval)
                hub.clear_live(base, chart_interval)
            self._mark_updated()
