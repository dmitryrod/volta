"""Сборник фильтров, используемых скринером."""

from .abstract import Filter, FilterResult
from .blacklist_filter import BlacklistFilter
from .daily_price_filter import DailyPriceFilter
from .daily_volume_filter import DailyVolumeFilter
from .funding_rate_filter import FundingRateFilter
from .liquidations_sum_filter import LiquidationsSumFilter, LiquidationsSumFilterResult
from .max_day_alerts_filter import MaxDayAlertsFilter
from .only_usdt_pairs_filter import OnlyUsdtPairsFilter
from .open_interest_filter import OpenInterestFilter, OpenInterestFilterResult
from .pump_dump_filter import PumpDumpFilter, PumpDumpFilterResult
from .volume_multiplier_filter import VolumeMultiplierFilter, VolumeMultiplierFilterResult
from .whitelist_filter import WhitelistFilter

__all__ = [
    "Filter",
    "FilterResult",
    "BlacklistFilter",
    "DailyPriceFilter",
    "DailyVolumeFilter",
    "FundingRateFilter",
    "LiquidationsSumFilter",
    "LiquidationsSumFilterResult",
    "MaxDayAlertsFilter",
    "OnlyUsdtPairsFilter",
    "OpenInterestFilter",
    "OpenInterestFilterResult",
    "PumpDumpFilter",
    "PumpDumpFilterResult",
    "VolumeMultiplierFilter",
    "VolumeMultiplierFilterResult",
    "WhitelistFilter",
]

