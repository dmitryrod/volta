"""Опциональный Telegram в Consumer._send_signal."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from unicex import Exchange, MarketType

from app.models import ScreeningResult, SignalDTO
from app.schemas.dtos import SettingsDTO
from app.schemas.enums import TextTemplateType
from app.screener.consumer import Consumer


def _minimal_signal() -> SignalDTO:
    return SignalDTO(
        timestamp=0,
        datetime="",
        symbol="BTCUSDT",
        ticker="BTC",
        last_price=1.0,
        funding_rate=0.0,
        daily_volume=1.0,
        daily_price=1.0,
        pd_start_price=None,
        pd_final_price=None,
        pd_price_change_pct=None,
        pd_price_change_usdt=None,
        oi_start_value=None,
        oi_final_value=None,
        oi_change_pct=None,
        oi_change_coins=None,
        oi_change_usdt=None,
        lq_amount_usdt=None,
        vl_multiplier=None,
    )


def _minimal_screening() -> ScreeningResult:
    s = _minimal_signal()
    return ScreeningResult(
        symbol=s.symbol,
        ticker=s.ticker,
        last_price=s.last_price,
        funding_rate=s.funding_rate,
        daily_volume=s.daily_volume,
        daily_price=s.daily_price,
        pd_start_price=s.pd_start_price,
        pd_final_price=s.pd_final_price,
        pd_price_change_pct=s.pd_price_change_pct,
        pd_price_change_usdt=s.pd_price_change_usdt,
        oi_start_value=s.oi_start_value,
        oi_final_value=s.oi_final_value,
        oi_change_pct=s.oi_change_pct,
        oi_change_coins=s.oi_change_coins,
        oi_change_usdt=s.oi_change_usdt,
        lq_amount_usdt=s.lq_amount_usdt,
        vl_multiplier=s.vl_multiplier,
    )


def _settings_telegram(
    *,
    bot_token: str | None,
    chat_id: int | None,
) -> SettingsDTO:
    return SettingsDTO(
        id=7,
        enabled=True,
        name="S",
        exchange=Exchange.BYBIT,
        market_type=MarketType.FUTURES,
        blacklist=None,
        whitelist=None,
        debug=False,
        pd_interval_sec=None,
        pd_min_change_pct=None,
        oi_interval_sec=None,
        oi_min_change_pct=None,
        oi_min_change_usd=None,
        fr_min_value_pct=None,
        fr_max_value_pct=None,
        vl_interval_sec=None,
        vl_min_multiplier=None,
        lq_interval_sec=None,
        lq_min_amount_usd=None,
        lq_min_amount_pct=None,
        dv_min_usd=1.0,
        dv_max_usd=None,
        dp_min_pct=None,
        dp_max_pct=None,
        max_day_alerts=None,
        timeout_sec=60,
        chat_id=chat_id,
        bot_token=bot_token,
        text_template_type=TextTemplateType.DEFAULT,
    )


def _bare_consumer(settings: SettingsDTO) -> Consumer:
    c = object.__new__(Consumer)
    c._settings = settings
    c._telegram_bot = MagicMock()
    c._telegram_bot.send_message = AsyncMock(
        return_value={"ok": True, "result": {"message_id": 1}}
    )
    c._logger = MagicMock()
    c._run_id = "run"
    c._cycle_id = 0
    c._schedule_debug_log = MagicMock()
    return c


@pytest.mark.asyncio
async def test_send_signal_skips_http_when_telegram_not_configured() -> None:
    """Без пары токен+чат не вызывается Bot API, сигнал всё равно сохраняется."""
    c = _bare_consumer(_settings_telegram(bot_token=None, chat_id=None))
    sig = _minimal_signal()
    res = _minimal_screening()

    with patch(
        "app.screener.consumer.log_signals_event_async", new_callable=AsyncMock
    ) as log_mock:
        with patch.object(c, "_save_signal_to_db", new_callable=AsyncMock) as save_mock:
            out = await c._send_signal(
                sig.symbol,
                "body",
                signal=sig,
                screening_result=res,
                calc_debug=None,
                daily_signal_count=1,
            )

    c._telegram_bot.send_message.assert_not_called()
    assert out == {}
    log_mock.assert_awaited_once()
    save_mock.assert_awaited_once()
    assert save_mock.await_args.kwargs["telegram_ok"] is False
    assert save_mock.await_args.kwargs["error"] is None


@pytest.mark.asyncio
async def test_send_signal_swallows_telegram_api_error() -> None:
    """Сбой Telegram не пробрасывается наружу."""
    c = _bare_consumer(_settings_telegram(bot_token="t", chat_id=1))
    c._telegram_bot.send_message = AsyncMock(side_effect=RuntimeError("blocked"))

    sig = _minimal_signal()
    res = _minimal_screening()

    with patch("app.screener.consumer.log_signals_event_async", new_callable=AsyncMock):
        with patch.object(c, "_save_signal_to_db", new_callable=AsyncMock) as save_mock:
            out = await c._send_signal(
                sig.symbol,
                "body",
                signal=sig,
                screening_result=res,
                calc_debug=None,
                daily_signal_count=1,
            )

    assert out == {}
    save_mock.assert_awaited_once()
    assert save_mock.await_args.kwargs["telegram_ok"] is False
    assert "blocked" in (save_mock.await_args.kwargs.get("error") or "")
    c._logger.warning.assert_called()
