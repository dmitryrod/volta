from __future__ import annotations

import time

from app.unicex.types import LiquidationDict  # type: ignore[attr-defined]

from .abstract import Filter, FilterResult


class LiquidationsSumFilterResult(FilterResult):
    """Результат фильтра по сумме ликвидаций."""

    amount_usdt: float | None = None


class LiquidationsSumFilter(Filter):
    """Фильтр по суммарной величине ликвидаций за интервал."""

    @staticmethod
    def process(
        liquidations: list[LiquidationDict],
        lq_interval_sec: int | None,
        lq_min_amount_usd: float | None,
        lq_min_amount_pct: float | None,
        daily_volume_usd: float | None,
    ) -> LiquidationsSumFilterResult:
        """Проверяет, что сумма ликвидаций за интервал превышает пороги по $ и/или % от суточного объема."""
        if not lq_interval_sec:
            return LiquidationsSumFilterResult(ok=False, metadata={})

        now_ms = int(time.time() * 1000)
        threshold_ms = now_ms - lq_interval_sec * 1000

        amount_usdt = 0.0
        for item in liquidations:
            if item["t"] < threshold_ms:
                continue
            # v – количество, p – цена
            amount_usdt += float(item["v"]) * float(item["p"])

        lq_pct: float | None = None
        if daily_volume_usd and daily_volume_usd > 0:
            lq_pct = amount_usdt / daily_volume_usd * 100.0

        conditions: list[bool] = []
        if lq_min_amount_usd is not None:
            conditions.append(amount_usdt >= lq_min_amount_usd)
        if lq_min_amount_pct is not None and lq_pct is not None:
            conditions.append(lq_pct >= lq_min_amount_pct)

        if not conditions:
            # Порогов нет — фильтр считается неактивным
            return LiquidationsSumFilterResult(ok=False, metadata={})

        ok = all(conditions)

        result = LiquidationsSumFilterResult(
            ok=ok,
            metadata={
                "amount_usdt": amount_usdt,
                "lq_interval_sec": lq_interval_sec,
                "lq_min_amount_usd": lq_min_amount_usd,
                "lq_min_amount_pct": lq_min_amount_pct,
                "lq_pct_of_daily_volume": lq_pct,
            },
        )
        # для удобства доступа из Consumer
        result.amount_usdt = amount_usdt
        return result

