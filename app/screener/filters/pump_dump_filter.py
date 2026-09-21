from __future__ import annotations

import time

from app.unicex.types import KlineDict  # type: ignore[attr-defined]

from .abstract import Filter, FilterResult


class PumpDumpFilterResult(FilterResult):
    """Результат фильтра пампа/дампа."""

    start_price: float | None = None
    final_price: float | None = None
    price_change_pct: float | None = None
    price_change_usdt: float | None = None


class PumpDumpFilter(Filter):
    """Фильтр для резкого изменения цены за короткий интервал."""

    @staticmethod
    def process(
        klines: list[KlineDict],
        pd_interval_sec: int | None,
        pd_min_change_pct: float | None,
    ) -> PumpDumpFilterResult:
        """Проверяет, что цена изменилась не менее чем на pd_min_change_pct за pd_interval_sec."""
        if not pd_interval_sec or pd_min_change_pct is None:
            return PumpDumpFilterResult(ok=False, metadata={})

        if not klines:
            return PumpDumpFilterResult(ok=False, metadata={"reason": "no_klines"})

        now_ms = int(time.time() * 1000)
        threshold_ms = now_ms - pd_interval_sec * 1000

        window = [k for k in klines if k["t"] >= threshold_ms]
        if len(window) < 2:
            return PumpDumpFilterResult(ok=False, metadata={"reason": "not_enough_klines"})

        window.sort(key=lambda x: x["t"])
        start_price = float(window[0]["o"])
        final_price = float(window[-1]["c"])

        if start_price <= 0:
            return PumpDumpFilterResult(ok=False, metadata={"reason": "bad_start_price"})

        price_change_pct = (final_price / start_price - 1.0) * 100.0
        price_change_usdt = final_price - start_price

        if pd_min_change_pct >= 0:
            ok = price_change_pct >= pd_min_change_pct
        else:
            ok = price_change_pct <= pd_min_change_pct

        result = PumpDumpFilterResult(
            ok=ok,
            metadata={
                "start_price": start_price,
                "final_price": final_price,
                "price_change_pct": price_change_pct,
                "price_change_usdt": price_change_usdt,
                "pd_interval_sec": pd_interval_sec,
                "pd_min_change_pct": pd_min_change_pct,
            },
        )
        result.start_price = start_price
        result.final_price = final_price
        result.price_change_pct = price_change_pct
        result.price_change_usdt = price_change_usdt
        return result

