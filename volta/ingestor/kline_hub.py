"""In-memory live kline state and SSE fan-out."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from volta.config.chart_intervals import INTERVAL_SECONDS


@dataclass
class LiveCandle:
    """Current forming candle."""

    time: int
    open: float
    high: float
    low: float
    close: float
    volume: float | None = None

    def to_chart_dict(self) -> dict[str, Any]:
        return {
            "time": self.time,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
        }


@dataclass
class SseSubscriber:
    """SSE client filter."""

    queue: asyncio.Queue[dict[str, Any]]
    base: str
    interval: str


@dataclass
class KlineHub:
    """Singleton hub for live candles and SSE broadcast."""

    _live: dict[tuple[str, str], LiveCandle] = field(default_factory=dict)
    _subscribers: list[SseSubscriber] = field(default_factory=list)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def get_live(self, base: str, interval: str) -> LiveCandle | None:
        return self._live.get((base.upper(), interval))

    def set_live(self, base: str, interval: str, candle: LiveCandle) -> None:
        self._live[(base.upper(), interval)] = candle

    def clear_live(self, base: str, interval: str) -> None:
        self._live.pop((base.upper(), interval), None)

    async def apply_ws_update(
        self,
        base: str,
        interval: str,
        open_time_sec: int,
        open_: float,
        high: float,
        low: float,
        close: float,
        volume: float | None,
        confirmed: bool,
    ) -> LiveCandle:
        """Update live candle from WS and broadcast."""
        base = base.upper()
        candle = LiveCandle(
            time=open_time_sec,
            open=open_,
            high=high,
            low=low,
            close=close,
            volume=volume,
        )
        async with self._lock:
            self._live[(base, interval)] = candle
        await self._broadcast(base, interval, candle, confirmed)
        return candle

    async def _broadcast(
        self,
        base: str,
        interval: str,
        candle: LiveCandle,
        confirmed: bool,
    ) -> None:
        payload = {
            "type": "kline",
            "base": base,
            "interval": interval,
            "candle": candle.to_chart_dict(),
            "confirmed": confirmed,
        }
        dead: list[SseSubscriber] = []
        for sub in self._subscribers:
            if sub.base != base or sub.interval != interval:
                continue
            try:
                sub.queue.put_nowait(payload)
            except asyncio.QueueFull:
                dead.append(sub)
        for sub in dead:
            self._subscribers.remove(sub)

    def subscribe(self, base: str, interval: str) -> SseSubscriber:
        sub = SseSubscriber(
            queue=asyncio.Queue(maxsize=64),
            base=base.upper(),
            interval=interval,
        )
        self._subscribers.append(sub)
        return sub

    def unsubscribe(self, sub: SseSubscriber) -> None:
        if sub in self._subscribers:
            self._subscribers.remove(sub)

    def initial_sse_payload(self, base: str, interval: str) -> dict[str, Any] | None:
        live = self.get_live(base, interval)
        if live is None:
            return None
        return {
            "type": "kline",
            "base": base.upper(),
            "interval": interval,
            "candle": live.to_chart_dict(),
            "confirmed": False,
        }

    def merge_series_with_live(
        self,
        closed: list[dict[str, Any]],
        base: str,
        interval: str,
    ) -> list[dict[str, Any]]:
        """Append or replace last bar with live forming candle."""
        live = self.get_live(base, interval)
        if live is None:
            return closed
        live_dict = live.to_chart_dict()
        if not closed:
            return [live_dict]
        if closed[-1]["time"] == live_dict["time"]:
            return closed[:-1] + [live_dict]
        if live_dict["time"] > closed[-1]["time"]:
            return closed + [live_dict]
        return closed


_hub: KlineHub | None = None


def get_kline_hub() -> KlineHub:
    """Return process-wide KlineHub singleton."""
    global _hub
    if _hub is None:
        _hub = KlineHub()
    return _hub


def current_bucket_open_time(interval: str, now_sec: int | None = None) -> int:
    """Aligned unix open time for the current bucket."""
    import time

    ts = now_sec if now_sec is not None else int(time.time())
    bucket = INTERVAL_SECONDS.get(interval, 300)
    return (ts // bucket) * bucket
