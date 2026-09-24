"""API tests for options chain and updated chart batch."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from volta.__main__ import app


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def authed_client(client: TestClient) -> TestClient:
    with patch(
        "volta.auth.middleware.is_authenticated_session",
        return_value=True,
    ):
        yield client


def _mock_db(snapshot_methods: dict) -> MagicMock:
    repo = MagicMock()
    for name, value in snapshot_methods.items():
        setattr(repo, name, value)
    db = MagicMock()
    db.snapshots = repo
    return db


def test_options_chain_200(authed_client: TestClient) -> None:
    chain = {
        "base": "ETH",
        "expiry": "2025-09-09T08:00:00+00:00",
        "expiry_label": "9 SEP 25",
        "spot": 2513.45,
        "calls": [
            {
                "symbol": "ETH-9SEP25-2520-C-USDT",
                "strike": 2520,
                "ask_price": 12.5,
                "otm": True,
            }
        ],
        "puts": [],
    }
    mock_db = _mock_db({"get_options_chain": AsyncMock(return_value=chain)})
    with patch("volta.api.routes_options.Database.session_context") as ctx:
        ctx.return_value.__aenter__ = AsyncMock(return_value=mock_db)
        ctx.return_value.__aexit__ = AsyncMock(return_value=None)
        resp = authed_client.get("/api/options/chain?base=ETH")
    assert resp.status_code == 200
    data = resp.json()
    assert data["base"] == "ETH"
    assert data["expiry"] == chain["expiry"]
    assert data["calls"][0]["symbol"] == "ETH-9SEP25-2520-C-USDT"


def test_options_chain_400_invalid_base(authed_client: TestClient) -> None:  # noqa: ARG001
    resp = authed_client.get("/api/options/chain?base=INVALID")
    assert resp.status_code == 400


def test_chart_batch_with_symbols(authed_client: TestClient) -> None:
    batch = {
        "base": "ETH",
        "interval": "5m",
        "futures": {"candles": [], "has_more": False},
        "options": {
            "expiry": "2025-09-09T08:00:00+00:00",
            "series": [
                {
                    "symbol": "ETH-9SEP25-2520-C-USDT",
                    "strike": 2520,
                    "option_type": "call",
                    "label": "$2,520 C",
                    "points": [{"time": 1725800400, "value": 12.5}],
                }
            ],
            "has_more": False,
        },
        "polymarket": {"series": [], "event_slug": None, "event_url": None, "has_more": False},
    }
    mock_get = AsyncMock(return_value=batch)
    mock_db = _mock_db({"get_chart_batch": mock_get})
    with patch("volta.api.routes_candles.Database.session_context") as ctx:
        ctx.return_value.__aenter__ = AsyncMock(return_value=mock_db)
        ctx.return_value.__aexit__ = AsyncMock(return_value=None)
        resp = authed_client.get(
            "/api/chart/batch?base=ETH&symbols=ETH-9SEP25-2520-C-USDT"
        )
    assert resp.status_code == 200
    data = resp.json()
    assert "call" not in data
    assert "put" not in data
    assert len(data["options"]["series"]) == 1
    mock_get.assert_awaited_once()
    assert mock_get.await_args.args[5] == ["ETH-9SEP25-2520-C-USDT"]


def test_chart_batch_passes_from_param(authed_client: TestClient) -> None:
    batch = {
        "base": "ETH",
        "interval": "5m",
        "futures": {"candles": [], "has_more": False},
        "options": {"expiry": None, "series": [], "has_more": False},
        "polymarket": {"series": [], "event_slug": None, "event_url": None, "has_more": False},
    }
    mock_get = AsyncMock(return_value=batch)
    mock_db = _mock_db({"get_chart_batch": mock_get})
    with patch("volta.api.routes_candles.Database.session_context") as ctx:
        ctx.return_value.__aenter__ = AsyncMock(return_value=mock_db)
        ctx.return_value.__aexit__ = AsyncMock(return_value=None)
        resp = authed_client.get("/api/chart/batch?base=ETH&from=1725800000")
    assert resp.status_code == 200
    mock_get.assert_awaited_once()
    assert mock_get.await_args.args[2] == 1725800000


def test_chart_batch_without_symbols(authed_client: TestClient) -> None:
    batch = {
        "base": "ETH",
        "interval": "5m",
        "futures": {"candles": [], "has_more": False},
        "options": {"expiry": None, "series": [], "has_more": False},
        "polymarket": {"series": [], "event_slug": None, "event_url": None, "has_more": False},
    }
    mock_get = AsyncMock(return_value=batch)
    mock_db = _mock_db({"get_chart_batch": mock_get})
    with patch("volta.api.routes_candles.Database.session_context") as ctx:
        ctx.return_value.__aenter__ = AsyncMock(return_value=mock_db)
        ctx.return_value.__aexit__ = AsyncMock(return_value=None)
        resp = authed_client.get("/api/chart/batch?base=ETH")
    assert resp.status_code == 200
    assert resp.json()["options"]["series"] == []


def test_candles_option_series(authed_client: TestClient) -> None:
    mock_agg = AsyncMock(
        return_value=(
            [
                {
                    "symbol": "ETH-9SEP25-2520-C-USDT",
                    "strike": 2520,
                    "option_type": "call",
                    "label": "$2,520 C",
                    "points": [{"time": 1725800400, "value": 12.5}],
                }
            ],
            "2025-09-09T08:00:00+00:00",
            False,
        )
    )
    mock_db = _mock_db({"aggregate_option_series": mock_agg})
    with patch("volta.api.routes_candles.Database.session_context") as ctx:
        ctx.return_value.__aenter__ = AsyncMock(return_value=mock_db)
        ctx.return_value.__aexit__ = AsyncMock(return_value=None)
        resp = authed_client.get(
            "/api/candles?base=ETH&series=option&symbol=ETH-9SEP25-2520-C-USDT"
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["series"] == "option"
    assert data["symbol"] == "ETH-9SEP25-2520-C-USDT"
    assert data["points"][0]["value"] == 12.5


def test_candles_option_requires_symbol(authed_client: TestClient) -> None:
    resp = authed_client.get("/api/candles?base=ETH&series=option")
    assert resp.status_code == 400


def test_chart_batch_rejects_invalid_symbols(authed_client: TestClient) -> None:
    resp = authed_client.get("/api/chart/batch?base=ETH&symbols=not-a-symbol")
    assert resp.status_code == 400


def test_panel_latest_includes_options_expiry(authed_client: TestClient) -> None:
    panel = MagicMock()
    panel.ts = MagicMock()
    panel.ts.timestamp.return_value = 1725800400
    panel.futures_symbol = "ETHUSDT"
    panel.futures_price = 2513.45
    panel.call_price = 12.5
    panel.put_price = 14.3
    panel.call_symbol = "ETH-9SEP25-2520-C-USDT"
    panel.put_symbol = "ETH-9SEP25-2510-P-USDT"

    mock_db = _mock_db(
        {
            "get_latest_panel": AsyncMock(return_value=panel),
            "get_latest_polymarket": AsyncMock(return_value=None),
            "get_options_chain": AsyncMock(
                return_value={"expiry": "2025-09-09T08:00:00+00:00"}
            ),
        }
    )
    with patch("volta.api.routes_candles.Database.session_context") as ctx:
        ctx.return_value.__aenter__ = AsyncMock(return_value=mock_db)
        ctx.return_value.__aexit__ = AsyncMock(return_value=None)
        resp = authed_client.get("/api/panel/latest?base=ETH")
    assert resp.status_code == 200
    assert resp.json()["panel"]["options_expiry"] == "2025-09-09T08:00:00+00:00"
