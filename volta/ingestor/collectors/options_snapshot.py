"""Options multi-strike chain snapshot collector."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any

from unicex import Exchange

from volta.config import config
from volta.ingestor.collectors.abstract import Collector
from volta.ingestor.writer import SnapshotWriter
from volta.utils.connectivity import is_transient_network_error, wait_for_internet

_EXPIRY_FORMATS = ("%d%b%y", "%d%b%Y")
_BYBIT_OPTION_EXPIRY_HOUR_UTC = 8


def _normalize_option_expiry(exp: datetime) -> datetime:
    """Canonical Bybit daily option expiry: date at 08:00 UTC."""
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    else:
        exp = exp.astimezone(timezone.utc)
    return exp.replace(
        hour=_BYBIT_OPTION_EXPIRY_HOUR_UTC,
        minute=0,
        second=0,
        microsecond=0,
    )


def _parse_option_tickers(raw: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract list of option ticker dicts from Bybit API response."""
    if not isinstance(raw, dict):
        return []
    result = raw.get("result") or raw
    if isinstance(result, dict):
        lst = result.get("list") or []
        return [x for x in lst if isinstance(x, dict)]
    if isinstance(result, list):
        return [x for x in result if isinstance(x, dict)]
    return []


def _parse_option_symbol(symbol: str) -> tuple[float | None, str | None]:
    """Parse strike and option type from Bybit symbol like BTC-25DEC26-85000-C-USDT."""
    parts = symbol.split("-")
    if len(parts) < 4:
        return None, None
    opt_type = parts[-2].upper()
    if opt_type == "USDT" and len(parts) >= 5:
        opt_type = parts[-3].upper()
        strike_part = parts[-4]
    else:
        strike_part = parts[-3]
    try:
        strike = float(strike_part)
    except (TypeError, ValueError):
        return None, None
    if opt_type in ("C", "P"):
        return strike, opt_type
    return None, None


def _parse_expiry_from_symbol(symbol: str) -> datetime | None:
    """Parse expiry datetime from Bybit option symbol segment (e.g. 9SEP25, 25SEP26)."""
    parts = symbol.split("-")
    if len(parts) < 2:
        return None
    raw = parts[1].upper()
    for fmt in _EXPIRY_FORMATS:
        try:
            parsed = datetime.strptime(raw, fmt).replace(tzinfo=timezone.utc)
            return _normalize_option_expiry(parsed)
        except ValueError:
            continue
    return None


def _parse_ticker_expiry(data: dict[str, Any], symbol: str) -> datetime | None:
    """Resolve option expiry from API fields or symbol."""
    for key in ("deliveryTime", "expireDate", "expiryDate", "expDate"):
        val = data.get(key)
        if val is None:
            continue
        try:
            ts = int(val)
            if ts > 10_000_000_000:
                ts //= 1000
            return _normalize_option_expiry(datetime.fromtimestamp(ts, tz=timezone.utc))
        except (TypeError, ValueError):
            continue
    return _parse_expiry_from_symbol(symbol)


def _ticker_ask_price(data: dict[str, Any]) -> float | None:
    """Ask price from ask1Price only (no mid fallback)."""
    ask = data.get("ask1Price")
    if ask is None:
        return None
    try:
        price = float(ask)
    except (TypeError, ValueError):
        return None
    if price <= 0:
        return None
    return price


def _expiry_iso(exp: datetime) -> str:
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    return exp.isoformat()


def is_otm_call(strike: float, spot: float) -> bool:
    """Hypothesis A: call is OTM when strike > spot."""
    return strike > spot


def is_otm_put(strike: float, spot: float) -> bool:
    """Hypothesis A: put is OTM when strike <= spot."""
    return strike <= spot


@dataclass(frozen=True)
class ChainContract:
    """Single option contract with ask price."""

    symbol: str
    strike: float
    option_type: str
    ask_price: float
    expiry: datetime


def _collect_chain_rows(
    tickers: list[dict[str, Any]],
    base: str,
    now: datetime,
    exchange: str,
) -> tuple[list[dict[str, Any]], datetime | None]:
    """Collect instrument rows for all strikes on nearest expiry."""
    nearest = _nearest_expiry(tickers, now)
    if nearest is None:
        return [], None

    rows: list[dict[str, Any]] = []
    for data in tickers:
        symbol = data.get("symbol")
        if not symbol:
            continue
        symbol_s = str(symbol)
        exp = _parse_ticker_expiry(data, symbol_s)
        if exp != nearest:
            continue

        strike = data.get("strikePrice") or data.get("strike")
        opt_type = (
            data.get("optionsType") or data.get("optionType") or data.get("type") or ""
        ).upper()
        if strike is None or not opt_type:
            parsed_strike, parsed_type = _parse_option_symbol(symbol_s)
            if strike is None:
                strike = parsed_strike
            if not opt_type:
                opt_type = (parsed_type or "").upper()

        ask = _ticker_ask_price(data)
        if strike is None or ask is None:
            continue
        try:
            strike_f = float(strike)
        except (TypeError, ValueError):
            continue

        if opt_type in ("C", "CALL"):
            option_type = "call"
        elif opt_type in ("P", "PUT"):
            option_type = "put"
        else:
            continue

        rows.append(
            {
                "ts": now,
                "base_asset": base,
                "exchange": exchange,
                "market": "option",
                "symbol": symbol_s,
                "metric": "ask_price",
                "value": float(ask),
                "meta_json": {
                    "option_type": option_type,
                    "strike": strike_f,
                    "expiry": _expiry_iso(nearest),
                    "symbol": symbol_s,
                },
            }
        )

    return rows, nearest


def _chain_contracts_from_rows(rows: list[dict[str, Any]]) -> list[ChainContract]:
    contracts: list[ChainContract] = []
    for row in rows:
        meta = row.get("meta_json") or {}
        expiry_raw = meta.get("expiry")
        if not expiry_raw:
            continue
        try:
            expiry = datetime.fromisoformat(str(expiry_raw))
        except ValueError:
            continue
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)
        contracts.append(
            ChainContract(
                symbol=str(row["symbol"]),
                strike=float(meta["strike"]),
                option_type=str(meta["option_type"]),
                ask_price=float(row["value"]),
                expiry=expiry,
            )
        )
    return contracts


def pick_default_call(calls: list[ChainContract], spot: float) -> ChainContract | None:
    """Default OTM call: min strike among OTM; else closest to spot."""
    otm = [c for c in calls if is_otm_call(c.strike, spot)]
    if otm:
        return min(otm, key=lambda c: c.strike)
    if calls:
        return min(calls, key=lambda c: abs(c.strike - spot))
    return None


def pick_default_put(puts: list[ChainContract], spot: float) -> ChainContract | None:
    """Default OTM put: max strike among OTM; else closest to spot."""
    otm = [p for p in puts if is_otm_put(p.strike, spot)]
    if otm:
        return max(otm, key=lambda p: p.strike)
    if puts:
        return min(puts, key=lambda p: abs(p.strike - spot))
    return None


def _default_otm_pair(
    rows: list[dict[str, Any]],
    spot: float,
) -> tuple[str | None, float | None, str | None, float | None]:
    """Reference ATM pair for panel (Hypothesis A defaults)."""
    contracts = _chain_contracts_from_rows(rows)
    calls = [c for c in contracts if c.option_type == "call"]
    puts = [c for c in contracts if c.option_type == "put"]
    default_call = pick_default_call(calls, spot)
    default_put = pick_default_put(puts, spot)
    call_sym = default_call.symbol if default_call else None
    call_px = default_call.ask_price if default_call else None
    put_sym = default_put.symbol if default_put else None
    put_px = default_put.ask_price if default_put else None
    return call_sym, call_px, put_sym, put_px


def _nearest_expiry(tickers: list[dict[str, Any]], now: datetime) -> datetime | None:
    """Earliest future expiry among tickers (Bybit nearest chain tab)."""
    expiries: set[datetime] = set()
    for data in tickers:
        symbol = data.get("symbol")
        if not symbol:
            continue
        exp = _parse_ticker_expiry(data, str(symbol))
        if exp is not None:
            expiries.add(exp)
    if not expiries:
        return None
    future = [e for e in expiries if e >= now]
    if future:
        return min(future)
    return max(expiries)


class OptionsSnapshotCollector(Collector):
    """Poll full option chain (nearest expiry) for all enabled bases."""

    _last_purge_utc_date: date | None = None

    def __init__(self, writer: SnapshotWriter, exchange_name: str = "bybit") -> None:
        exchange = Exchange.BYBIT if exchange_name == "bybit" else Exchange.BYBIT
        super().__init__(exchange, "options_snapshot")
        self._writer = writer
        self._interval = config.ingestor.interval_sec

    async def start(self) -> None:
        await wait_for_internet(log_name="options-collector")
        while self._is_running:
            try:
                await self._collect_once()
                self._mark_updated()
            except Exception as exc:
                if is_transient_network_error(exc):
                    self._logger.warning("Transient error in options collector: {}", exc)
                    await wait_for_internet(log_name="options-collector")
                else:
                    self._logger.exception("Options collector error: {}", exc)
            await self._safe_sleep(self._interval)

    async def _maybe_purge(self, now: datetime) -> None:
        """Purge expired option rows after 08:00 UTC, max once per UTC day."""
        if now.hour < 8:
            return
        today = now.date()
        if OptionsSnapshotCollector._last_purge_utc_date == today:
            return
        deleted = await self._writer.purge_expired_options(now)
        OptionsSnapshotCollector._last_purge_utc_date = today
        self._logger.info("Purged {} expired option rows (cutoff={})", deleted, now.isoformat())

    async def _collect_once(self) -> None:
        assets = await self._writer.get_enabled_assets()
        if not assets:
            return
        ts = datetime.now(timezone.utc)

        async with self._client_context() as client:
            futures_prices = await client.futures_last_price()

            for asset in assets:
                base = asset.base_asset
                futures_sym = asset.futures_symbol
                futures_px = futures_prices.get(futures_sym)
                if futures_px is None:
                    self._logger.warning("Skip options for {}: no futures price", base)
                    continue

                call_sym, call_px, put_sym, put_px = None, None, None, None
                instrument_rows: list[dict[str, Any]] = []
                nearest_expiry: datetime | None = None
                try:
                    raw = await client.client.tickers(category="option", base_coin=base)
                    tickers = _parse_option_tickers(raw)
                    instrument_rows, nearest_expiry = _collect_chain_rows(
                        tickers,
                        base,
                        ts,
                        config.ingestor.exchange,
                    )
                    call_sym, call_px, put_sym, put_px = _default_otm_pair(
                        instrument_rows, float(futures_px)
                    )
                except Exception as exc:
                    self._logger.warning("Options unavailable for {}: {}", base, exc)

                if instrument_rows:
                    await self._writer.write_instruments(instrument_rows)

                panel_row: dict[str, Any] = {
                    "ts": ts,
                    "base_asset": base,
                    "futures_symbol": futures_sym,
                    "futures_price": float(futures_px),
                    "call_price": call_px,
                    "put_price": put_px,
                    "call_symbol": call_sym,
                    "put_symbol": put_sym,
                }
                await self._writer.write_panel(panel_row)

                expiry_label = nearest_expiry.isoformat() if nearest_expiry else "none"
                self._logger.info(
                    "options {}: wrote {} chain rows, expiry={}, ref_call={}, ref_put={}",
                    base,
                    len(instrument_rows),
                    expiry_label,
                    call_sym,
                    put_sym,
                )

        await self._maybe_purge(ts)
