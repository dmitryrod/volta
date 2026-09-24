"""API tests for Polymarket events catalog."""

from datetime import datetime, timedelta, timezone
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


def _event_row(slug: str, title: str = "Test Event") -> MagicMock:
    row = MagicMock()
    row.event_slug = slug
    row.event_url = f"https://polymarket.com/event/{slug}"
    row.event_title = title
    row.event_end_date = datetime(2026, 9, 9, 23, 59, 59, tzinfo=timezone.utc)
    return row


def test_list_polymarket_events_200(authed_client: TestClient) -> None:
    rows = [_event_row("eth-event-1")]
    mock_db = _mock_db({"list_polymarket_events": AsyncMock(return_value=rows)})
    with patch("volta.api.routes_polymarket.Database.session_context") as ctx:
        ctx.return_value.__aenter__ = AsyncMock(return_value=mock_db)
        ctx.return_value.__aexit__ = AsyncMock(return_value=None)
        resp = authed_client.get("/api/polymarket/events?base=ETH")
    assert resp.status_code == 200
    data = resp.json()
    assert data["base"] == "ETH"
    assert len(data["events"]) == 1
    assert data["events"][0]["event_slug"] == "eth-event-1"
    assert data["max_events"] == 10


def test_import_polymarket_events_dedupes(authed_client: TestClient) -> None:
    gamma_event = {
        "title": "Ethereum above",
        "endDate": "2026-09-09T23:59:59Z",
    }
    upserted = [_event_row("ethereum-above-on-september-9-2026", "Ethereum above")]
    mock_db = _mock_db(
        {
            "list_polymarket_event_slugs": AsyncMock(return_value=set()),
            "upsert_polymarket_events": AsyncMock(return_value=None),
            "list_polymarket_events": AsyncMock(return_value=upserted),
        }
    )
    with (
        patch("volta.api.routes_polymarket.Database.session_context") as ctx,
        patch("volta.api.routes_polymarket.GammaClient") as gamma_cls,
    ):
        ctx.return_value.__aenter__ = AsyncMock(return_value=mock_db)
        ctx.return_value.__aexit__ = AsyncMock(return_value=None)
        client = AsyncMock()
        client.fetch_event_by_slug = AsyncMock(return_value=gamma_event)
        gamma_cls.return_value.__aenter__ = AsyncMock(return_value=client)
        gamma_cls.return_value.__aexit__ = AsyncMock(return_value=None)
        resp = authed_client.post(
            "/api/polymarket/events/import",
            json={
                "base": "ETH",
                "urls_text": (
                    "https://polymarket.com/event/ethereum-above-on-september-9-2026\n"
                    "https://polymarket.com/event/ethereum-above-on-september-9-2026"
                ),
            },
        )
    assert resp.status_code == 200
    upsert_call = mock_db.snapshots.upsert_polymarket_events.await_args
    assert len(upsert_call.args[1]) == 1


def test_import_polymarket_events_max_cap(authed_client: TestClient) -> None:
    existing = {f"event-{i}" for i in range(10)}
    mock_db = _mock_db({"list_polymarket_event_slugs": AsyncMock(return_value=existing)})
    with patch("volta.api.routes_polymarket.Database.session_context") as ctx:
        ctx.return_value.__aenter__ = AsyncMock(return_value=mock_db)
        ctx.return_value.__aexit__ = AsyncMock(return_value=None)
        resp = authed_client.post(
            "/api/polymarket/events/import",
            json={
                "base": "ETH",
                "urls_text": "https://polymarket.com/event/new-event-slug",
            },
        )
    assert resp.status_code == 400
    assert "Max 10" in resp.json()["detail"]


def test_import_polymarket_events_invalid_url(authed_client: TestClient) -> None:
    resp = authed_client.post(
        "/api/polymarket/events/import",
        json={"base": "ETH", "urls_text": "not-a-url"},
    )
    assert resp.status_code == 400


def test_chart_batch_pm_event_slug(authed_client: TestClient) -> None:
    batch = {
        "base": "ETH",
        "interval": "5m",
        "futures": {"candles": [], "has_more": False},
        "options": {"expiry": None, "series": [], "has_more": False},
        "polymarket": {
            "series": [],
            "event_slug": "eth-event-1",
            "event_url": "https://polymarket.com/event/eth-event-1",
            "has_more": False,
        },
    }
    mock_get = AsyncMock(return_value=batch)
    mock_db = _mock_db({"get_chart_batch": mock_get})
    with patch("volta.api.routes_candles.Database.session_context") as ctx:
        ctx.return_value.__aenter__ = AsyncMock(return_value=mock_db)
        ctx.return_value.__aexit__ = AsyncMock(return_value=None)
        resp = authed_client.get(
            "/api/chart/batch?base=ETH&pm_event_slug=eth-event-1"
        )
    assert resp.status_code == 200
    mock_get.assert_awaited_once()
    assert mock_get.await_args.kwargs.get("pm_event_slug") == "eth-event-1" or (
        len(mock_get.await_args.args) > 6
        and mock_get.await_args.args[6] == "eth-event-1"
    )
