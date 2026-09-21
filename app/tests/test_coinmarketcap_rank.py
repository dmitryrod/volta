"""Юнит-тесты для ретраев CoinMarketCap (мок `requests.get`, без перезагрузки модуля)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import secrets


def test_parse_api_keys_pipe_and_trim() -> None:
    from app.utils.coinmarketcap_rank import _parse_api_keys

    assert _parse_api_keys(" a | b ") == ["a", "b"]
    assert _parse_api_keys("solo") == ["solo"]
    assert _parse_api_keys("a||c") == ["a", "c"]
    assert _parse_api_keys(None) == []
    assert _parse_api_keys("") == []


def test_http_get_retries_429_then_200(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CMC_PRO_API_KEY", "test-key")

    resp429 = MagicMock()
    resp429.status_code = 429
    resp429.headers = {"Retry-After": "0"}

    payload = {
        "data": [{"symbol": "BTC", "cmc_rank": 1}, {"symbol": "ETH", "cmc_rank": 2}],
    }
    resp200 = MagicMock()
    resp200.status_code = 200
    resp200.headers = {}
    resp200.json.return_value = payload
    resp200.raise_for_status = MagicMock()

    from app.utils import coinmarketcap_rank as cmc

    with patch.object(cmc.requests, "get", side_effect=[resp429, resp200]):
        with patch.object(cmc.time, "sleep", lambda *_a, **_k: None):
            cmc._fetch_and_update_cmc_ranks()

    assert cmc.get_cmc_rank_for_symbol("BTCUSDT") == 1
    assert cmc.get_cmc_rank_for_symbol("ETHUSDT") == 2


def test_http_get_exhausts_retries_on_429(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CMC_PRO_API_KEY", "test-key")
    monkeypatch.setenv("CMC_RETRY_MAX", "2")

    attempts = 0

    def make_429(*_args, **_kwargs) -> MagicMock:
        nonlocal attempts
        attempts += 1
        r = MagicMock()
        r.status_code = 429
        r.headers = {}
        return r

    from app.utils import coinmarketcap_rank as cmc

    cmc._CMC_RANKS.clear()
    with patch.object(cmc.requests, "get", side_effect=make_429):
        with patch.object(cmc.time, "sleep", lambda *_a, **_k: None):
            cmc._fetch_and_update_cmc_ranks()

    assert attempts == 3
    assert not cmc._CMC_RANKS


def test_choice_invoked_each_http_attempt(monkeypatch: pytest.MonkeyPatch) -> None:
    """429 + успех → два запроса, два раза вызывается secrets.choice над одним списком ключей."""
    from app.utils import coinmarketcap_rank as cmc

    monkeypatch.setenv("CMC_RETRY_MAX", "1")

    mock_choice = MagicMock(side_effect=["alice-key", "bob-key"])

    resp429 = MagicMock()
    resp429.status_code = 429
    resp429.headers = {}

    payload = {"data": [{"symbol": "BTC", "cmc_rank": 1}]}
    resp200 = MagicMock()
    resp200.status_code = 200
    resp200.json.return_value = payload
    resp200.raise_for_status = MagicMock()

    with patch.object(secrets, "choice", mock_choice):
        with patch.object(cmc.requests, "get", side_effect=[resp429, resp200]):
            with patch.object(cmc.time, "sleep", lambda *_a, **_k: None):
                out = cmc._http_get_json_with_retries(
                    "https://example.com",
                    params={},
                    api_keys=("alice", "bob"),
                    timeout=10.0,
                )

    assert out == payload
    assert mock_choice.call_count == 2
    for call in mock_choice.call_args_list:
        assert call[0][0] == ["alice", "bob"]


def test_two_http_pages_invoke_choice_per_get(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CMC_PRO_API_KEY", "ka|kb")
    monkeypatch.setenv("CMC_RETRY_MAX", "0")

    order = iter(["ka", "kb"])

    monkeypatch.setattr(secrets, "choice", lambda keys: next(order))

    from app.utils import coinmarketcap_rank as cmc

    seen_keys: list[str] = []

    btc = {"symbol": "BTC", "cmc_rank": 1}

    def capture_get(_url, params=None, headers=None, timeout=None):  # noqa: ANN001
        seen_keys.append(headers.get("X-CMC_PRO_API_KEY", ""))
        resp = MagicMock()
        resp.status_code = 200
        resp.raise_for_status = MagicMock()
        if params and int(params["start"]) == 1:
            resp.json.return_value = {"data": [btc, btc]}
        else:
            resp.json.return_value = {"data": [{"symbol": "ETH", "cmc_rank": 2}]}
        return resp

    cmc._CMC_RANKS.clear()
    with patch.object(cmc, "_get_listings_page_size", return_value=2):
        with patch.object(cmc.requests, "get", side_effect=capture_get):
            cmc._fetch_and_update_cmc_ranks()

    assert seen_keys[:2] == ["ka", "kb"]
