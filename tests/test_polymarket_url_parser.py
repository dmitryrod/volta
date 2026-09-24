"""Tests for Polymarket URL parsing."""

import pytest

from volta.polymarket.url_parser import parse_event_slug_from_url


def test_parse_ru_event_url() -> None:
    slug = parse_event_slug_from_url(
        "https://polymarket.com/ru/event/ethereum-above-on-september-9-2026"
    )
    assert slug == "ethereum-above-on-september-9-2026"


def test_parse_en_event_url() -> None:
    slug = parse_event_slug_from_url(
        "https://polymarket.com/event/bitcoin-above-on-september-9-2026"
    )
    assert slug == "bitcoin-above-on-september-9-2026"


def test_parse_empty_raises() -> None:
    with pytest.raises(ValueError, match="empty"):
        parse_event_slug_from_url("")


def test_parse_invalid_path_raises() -> None:
    with pytest.raises(ValueError, match="/event/"):
        parse_event_slug_from_url("https://polymarket.com/markets/foo")
