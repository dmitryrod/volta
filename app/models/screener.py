__all__ = ["ScreeningResult"]

from dataclasses import dataclass


@dataclass(slots=True)
class ScreeningResult:
    """Информация полученная при проверке тикера."""

    symbol: str
    ticker: str

    # Данные собранные с монеты
    last_price: float
    funding_rate: float
    daily_volume: float
    daily_price: float

    # Информации с фильтра пампов и дампов
    pd_start_price: float | None
    pd_final_price: float | None
    pd_price_change_pct: float | None
    pd_price_change_usdt: float | None

    # Информация с фильтра открытого интареса
    oi_start_value: float | None
    oi_final_value: float | None
    oi_change_pct: float | None
    oi_change_coins: float | None
    oi_change_usdt: float | None

    # Информация с фильтра ликвидации
    lq_amount_usdt: float | None

    # Информации с фильтра объема
    vl_multiplier: float | None