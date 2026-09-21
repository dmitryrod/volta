"""Collectors package."""

from unicex import Exchange

from app_options.ingestor.collectors.abstract import Collector
from app_options.ingestor.collectors.kline_ws_collector import KlineWsCollector
from app_options.ingestor.collectors.options_snapshot import OptionsSnapshotCollector
from app_options.ingestor.collectors.polymarket_snapshot import PolymarketSnapshotCollector

__all__ = [
    "Collector",
    "KlineWsCollector",
    "OptionsSnapshotCollector",
    "PolymarketSnapshotCollector",
]
