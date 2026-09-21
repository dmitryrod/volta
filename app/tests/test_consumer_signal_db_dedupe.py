"""Дедупликация строк signals по tracking_id в Consumer._save_signal_to_db."""

from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import MagicMock, patch

import pytest

from app.schemas.dtos import SettingsDTO
from app.schemas.enums import TextTemplateType
from app.screener.consumer import Consumer
from unicex import Exchange, MarketType


def _minimal_settings() -> SettingsDTO:
    return SettingsDTO(
        id=11,
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
        chat_id=1,
        bot_token="x",
        text_template_type=TextTemplateType.DEFAULT,
    )


@pytest.mark.asyncio
async def test_save_signal_to_db_skips_second_row_same_tracking_id() -> None:
    """Вторая вставка с тем же tracking_id не добавляет запись и не коммитит."""
    tid = "dc78343d92f04a78a333"
    persisted_tids: set[str] = set()
    add_calls: list[object] = []
    commit_calls = 0

    @asynccontextmanager
    async def fake_session_context():
        db = MagicMock()

        async def scalar(_stmt):
            return 99 if tid in persisted_tids else None

        async def commit():
            nonlocal commit_calls
            commit_calls += 1

        def add(record):
            add_calls.append(record)
            if getattr(record, "tracking_id", None):
                persisted_tids.add(record.tracking_id)

        db.session.scalar = scalar
        db.session.add = add
        db.commit = commit
        yield db

    c = object.__new__(Consumer)
    c._settings = _minimal_settings()
    c._logger = MagicMock()

    with patch("app.screener.consumer.Database.session_context", fake_session_context):
        await c._save_signal_to_db(
            symbol="DRIFTUSDT",
            telegram_text="t",
            telegram_ok=True,
            error=None,
            tracking_id=tid,
            card_snapshot_json="{}",
        )
        await c._save_signal_to_db(
            symbol="DRIFTUSDT",
            telegram_text="t",
            telegram_ok=True,
            error=None,
            tracking_id=tid,
            card_snapshot_json="{}",
        )

    assert len(add_calls) == 1
    assert commit_calls == 1
    assert getattr(add_calls[0], "tracking_id", None) == tid


@pytest.mark.asyncio
async def test_save_signal_to_db_no_tracking_id_allows_multiple_rows() -> None:
    add_calls: list[object] = []

    @asynccontextmanager
    async def fake_session_context():
        db = MagicMock()

        async def scalar(_stmt):
            return None

        def add(record):
            add_calls.append(record)

        db.session.scalar = scalar
        db.session.add = add
        db.commit = MagicMock()
        yield db

    c = object.__new__(Consumer)
    c._settings = _minimal_settings()
    c._logger = MagicMock()

    with patch("app.screener.consumer.Database.session_context", fake_session_context):
        await c._save_signal_to_db(
            symbol="X",
            telegram_text="a",
            telegram_ok=True,
            error=None,
            tracking_id=None,
            card_snapshot_json=None,
        )
        await c._save_signal_to_db(
            symbol="X",
            telegram_text="b",
            telegram_ok=True,
            error=None,
            tracking_id=None,
            card_snapshot_json=None,
        )

    assert len(add_calls) == 2
