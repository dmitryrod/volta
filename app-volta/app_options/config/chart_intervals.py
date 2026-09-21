"""Chart timeframe constants and Bybit mapping."""

from __future__ import annotations

CHART_INTERVALS: tuple[str, ...] = ("1m", "5m", "15m", "1h", "4h", "1d")

INTERVAL_SECONDS: dict[str, int] = {
    "1m": 60,
    "5m": 300,
    "15m": 900,
    "1h": 3600,
    "4h": 14400,
    "1d": 86400,
}

# Bybit WS / REST kline interval token
BYBIT_INTERVAL: dict[str, str] = {
    "1m": "1",
    "5m": "5",
    "15m": "15",
    "1h": "60",
    "4h": "240",
    "1d": "D",
}

MAX_CLOSED_CANDLES_PER_SERIES: int = 1000


def chart_interval_to_bybit(interval: str) -> str:
    """Map chart interval key to Bybit kline interval string."""
    if interval not in BYBIT_INTERVAL:
        raise ValueError(f"unsupported chart interval: {interval}")
    return BYBIT_INTERVAL[interval]


def parse_kline_topic(topic: str) -> tuple[str, str]:
    """Parse Bybit topic kline.{interval}.{symbol} -> (bybit_interval, symbol)."""
    parts = topic.split(".")
    if len(parts) < 3 or parts[0] != "kline":
        raise ValueError(f"invalid kline topic: {topic}")
    return parts[1], parts[2]


def bybit_interval_to_chart(bybit_interval: str) -> str | None:
    """Map Bybit interval token back to chart interval key."""
    for chart_key, token in BYBIT_INTERVAL.items():
        if token == bybit_interval:
            return chart_key
    return None
