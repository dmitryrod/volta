"""Asset symbol mapping for tracked bases."""

from __future__ import annotations

import re
from typing import Final

MAX_OPTION_SYMBOLS: Final[int] = 20
_OPTION_SYMBOL_RE: Final[re.Pattern[str]] = re.compile(
    r"^[A-Z0-9]+-\d{1,2}[A-Z]{3}\d{2}-\d+-(C|P)-USDT$"
)

DEFAULT_ASSETS: Final[dict[str, dict[str, str | None]]] = {
    "BTC": {"futures_symbol": "BTCUSDT", "polymarket_market_id": None},
    "ETH": {"futures_symbol": "ETHUSDT", "polymarket_market_id": None},
    "SOL": {"futures_symbol": "SOLUSDT", "polymarket_market_id": None},
}

VALID_BASES: Final[frozenset[str]] = frozenset(DEFAULT_ASSETS.keys())


def futures_symbol(base_asset: str) -> str:
    """Return futures symbol for base asset."""
    key = base_asset.upper()
    if key not in DEFAULT_ASSETS:
        raise ValueError(f"Unknown base asset: {base_asset}")
    return str(DEFAULT_ASSETS[key]["futures_symbol"])


def validate_base(base: str) -> str:
    """Normalize and validate base asset code."""
    key = (base or "").strip().upper()
    if key not in VALID_BASES:
        raise ValueError(f"base must be one of {sorted(VALID_BASES)}")
    return key


def validate_option_symbols(symbols: list[str], base_asset: str) -> list[str]:
    """Validate Bybit option symbols for chart API (count cap + format)."""
    if len(symbols) > MAX_OPTION_SYMBOLS:
        raise ValueError(f"At most {MAX_OPTION_SYMBOLS} option symbols allowed")
    validated: list[str] = []
    prefix = f"{base_asset}-"
    for sym in symbols:
        if not _OPTION_SYMBOL_RE.match(sym):
            raise ValueError(f"Invalid option symbol: {sym}")
        if not sym.startswith(prefix):
            raise ValueError(f"Symbol {sym} does not match base {base_asset}")
        validated.append(sym)
    return validated
