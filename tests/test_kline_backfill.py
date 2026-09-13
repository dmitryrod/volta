"""Tests for KlineBackfillService unicex client lifecycle."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app_options.database.models import AssetConfig
from app_options.ingestor.kline_backfill import KlineBackfillService


@pytest.mark.asyncio
async def test_run_for_assets_awaits_uni_client_create() -> None:
    """create() is a coroutine; must be awaited before async-with client."""
    mock_client = AsyncMock()
    mock_client.futures_klines = AsyncMock(return_value=[])

    mock_cm = AsyncMock()
    mock_cm.__aenter__.return_value = mock_client
    mock_cm.__aexit__.return_value = None

    mock_factory = MagicMock()
    mock_factory.create = AsyncMock(return_value=mock_cm)

    assets = [
        AssetConfig(
            base_asset="ETH",
            futures_symbol="ETHUSDT",
            enabled=True,
        )
    ]

    with patch(
        "app_options.ingestor.kline_backfill.get_uni_client",
        return_value=mock_factory,
    ):
        service = KlineBackfillService()
        await service.run_for_assets(assets)

    mock_factory.create.assert_awaited_once()
    mock_cm.__aenter__.assert_awaited_once()
