"""Polymarket Gamma API client."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import aiohttp

GAMMA_BASE = "https://gamma-api.polymarket.com"


@dataclass(frozen=True, slots=True)
class PolymarketStrikeMarket:
    """One strike market inside a multi-strike event."""

    market_id: str
    strike: float
    question: str
    yes_probability: float
    slug: str | None = None


def _parse_strike(raw: Any) -> float | None:
    if raw is None:
        return None
    text = str(raw).replace(",", "").replace(" ", "").strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def parse_event_end_date(event: dict[str, Any]) -> str | None:
    """Return ISO 8601 endDate from Gamma event payload."""
    raw = event.get("endDate")
    if raw is None:
        return None
    text = str(raw).strip()
    return text or None


def _yes_probability_pct(market: dict[str, Any]) -> float:
    """Return Yes probability as 0-100 from Gamma market payload."""
    raw_prices = market.get("outcomePrices")
    if raw_prices:
        try:
            prices = json.loads(raw_prices) if isinstance(raw_prices, str) else raw_prices
            if prices:
                return round(float(prices[0]) * 100.0, 2)
        except (TypeError, ValueError, json.JSONDecodeError):
            pass
    bid = market.get("bestBid")
    ask = market.get("bestAsk")
    if bid is not None and ask is not None:
        try:
            return round((float(bid) + float(ask)) / 2.0 * 100.0, 2)
        except (TypeError, ValueError):
            pass
    last = market.get("lastTradePrice")
    if last is not None:
        try:
            return round(float(last) * 100.0, 2)
        except (TypeError, ValueError):
            pass
    return 0.0


def select_strike_markets(
    markets: list[dict[str, Any]],
    spot_price: float,
    *,
    below_count: int = 3,
    above_count: int = 3,
) -> list[PolymarketStrikeMarket]:
    """Pick N strikes below and above spot from event markets.

    Args:
        markets: Gamma event ``markets`` list.
        spot_price: Current futures/spot reference price.
        below_count: How many strikes strictly below spot.
        above_count: How many strikes at or above spot.

    Returns:
        Parsed strike markets sorted by strike ascending.
    """
    parsed: list[tuple[float, dict[str, Any]]] = []
    for market in markets:
        if not market.get("active") or market.get("closed"):
            continue
        strike = _parse_strike(market.get("groupItemTitle"))
        if strike is None:
            continue
        parsed.append((strike, market))

    if not parsed:
        return []

    by_strike = {strike: market for strike, market in parsed}
    strikes = sorted(by_strike.keys())
    below = [s for s in strikes if s < spot_price]
    above = [s for s in strikes if s >= spot_price]

    below_pick = list(reversed(below[-below_count:])) if below else []
    above_pick = above[:above_count] if above else []

    if len(below_pick) < below_count and below:
        for s in reversed(below):
            if s not in below_pick:
                below_pick.append(s)
            if len(below_pick) >= below_count:
                break

    if len(above_pick) < above_count and above:
        for s in above:
            if s not in above_pick:
                above_pick.append(s)
            if len(above_pick) >= above_count:
                break

    selected_strikes = sorted(set(below_pick + above_pick))
    out: list[PolymarketStrikeMarket] = []
    for strike in selected_strikes:
        market = by_strike[strike]
        market_id = str(market.get("id") or "")
        if not market_id:
            continue
        out.append(
            PolymarketStrikeMarket(
                market_id=market_id,
                strike=strike,
                question=str(market.get("question") or f"Above ${strike:g}"),
                yes_probability=_yes_probability_pct(market),
                slug=market.get("slug"),
            )
        )
    return out


class GammaClient:
    """Async client for Polymarket Gamma API."""

    def __init__(self, session: aiohttp.ClientSession | None = None) -> None:
        self._session = session
        self._owns_session = session is None

    async def __aenter__(self) -> GammaClient:
        if self._session is None:
            self._session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, *args: object) -> None:
        if self._owns_session and self._session is not None:
            await self._session.close()

    async def fetch_event_by_slug(self, slug: str) -> dict[str, Any]:
        """Load event JSON by slug."""
        assert self._session is not None
        url = f"{GAMMA_BASE}/events"
        async with self._session.get(url, params={"slug": slug}, timeout=30) as resp:
            resp.raise_for_status()
            data = await resp.json()
        if not isinstance(data, list) or not data:
            raise ValueError(f"Polymarket event not found: {slug}")
        return data[0]

    async def fetch_strikes_for_event(
        self,
        event_slug: str,
        spot_price: float,
    ) -> tuple[str, list[PolymarketStrikeMarket]]:
        """Return event title and selected strike markets."""
        event = await self.fetch_event_by_slug(event_slug)
        markets = event.get("markets") or []
        if not isinstance(markets, list):
            markets = []
        title = str(event.get("title") or event_slug)
        selected = select_strike_markets(markets, spot_price)
        return title, selected
