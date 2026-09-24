"""Collectors package."""

from unicex import Exchange

from volta.ingestor.collectors.abstract import Collector
from volta.ingestor.collectors.kline_ws_collector import KlineWsCollector
from volta.ingestor.collectors.options_snapshot import OptionsSnapshotCollector
from volta.ingestor.collectors.polymarket_snapshot import PolymarketSnapshotCollector

__all__ = [
    "Collector",
    "KlineWsCollector",
    "OptionsSnapshotCollector",
    "PolymarketSnapshotCollector",
]
