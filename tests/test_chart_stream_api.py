"""Tests for chart SSE endpoint."""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from volta.__main__ import app


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_chart_stream_requires_auth(client: TestClient) -> None:
    response = client.get("/api/chart/stream?base=ETH&interval=5m")
    assert response.status_code == 401


def test_chart_stream_invalid_base(client: TestClient) -> None:
    with patch(
        "volta.auth.middleware.is_authenticated_session",
        return_value=True,
    ):
        response = client.get("/api/chart/stream?base=INVALID&interval=5m")
    assert response.status_code == 400
