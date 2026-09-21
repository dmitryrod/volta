"""Парсинг опциональных Telegram-переменных окружения (без падения при импорте ``app.config``)."""

from __future__ import annotations

import logging

import pytest

from app.config.config import parse_optional_telegram_bot_token, parse_optional_telegram_chat_id


@pytest.mark.parametrize(
    "raw,expected",
    [
        (None, None),
        ("", None),
        ("   ", None),
        ("5732583758", 5732583758),
        (" -1001234567890 ", -1001234567890),
        ("#5732583758", None),
        ("not-a-number", None),
        ("12.5", None),
    ],
)
def test_parse_optional_telegram_chat_id(raw: str | None, expected: int | None) -> None:
    assert parse_optional_telegram_chat_id(raw) == expected


@pytest.mark.parametrize(
    "raw,expected",
    [
        (None, None),
        ("", None),
        ("   ", None),
        ("6106449698:AAFx", "6106449698:AAFx"),
        (" #secret ", None),
        ("#6106449698:AAFx", None),
    ],
)
def test_parse_optional_telegram_bot_token(raw: str | None, expected: str | None) -> None:
    assert parse_optional_telegram_bot_token(raw) == expected


def test_parse_chat_id_logs_warning_for_hash_prefix(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING):
        assert parse_optional_telegram_chat_id("#42") is None
    assert "TELEGRAM_CHAT_ID starts with '#'" in caplog.text


def test_parse_chat_id_logs_warning_for_garbage(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING):
        assert parse_optional_telegram_chat_id("abc") is None
    assert "not a valid integer" in caplog.text


def test_parse_token_logs_warning_for_hash_prefix(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING):
        assert parse_optional_telegram_bot_token("#tok") is None
    assert "TELEGRAM_BOT_TOKEN starts with '#'" in caplog.text
