"""Tests for expired options purge."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from volta.ingestor.collectors.options_snapshot import OptionsSnapshotCollector
from volta.ingestor.writer import SnapshotWriter


@pytest.mark.asyncio
async def test_purge_deletes_expired_option_rows() -> None:
    repo = MagicMock()
    repo.purge_expired_options = AsyncMock(return_value=3)
    writer = SnapshotWriter()

    cutoff = datetime(2025, 9, 9, 9, 0, tzinfo=timezone.utc)
    with patch("volta.ingestor.writer.Database.session_context") as ctx:
        ctx.return_value.__aenter__ = AsyncMock(return_value=MagicMock(snapshots=repo))
        ctx.return_value.__aexit__ = AsyncMock(return_value=None)
        deleted = await writer.purge_expired_options(cutoff)

    assert deleted == 3
    repo.purge_expired_options.assert_awaited_once_with(cutoff)


@pytest.mark.asyncio
async def test_purge_idempotent() -> None:
    repo = MagicMock()
    repo.purge_expired_options = AsyncMock(side_effect=[5, 0])
    writer = SnapshotWriter()
    cutoff = datetime(2025, 9, 9, 9, 0, tzinfo=timezone.utc)

    with patch("volta.ingestor.writer.Database.session_context") as ctx:
        ctx.return_value.__aenter__ = AsyncMock(return_value=MagicMock(snapshots=repo))
        ctx.return_value.__aexit__ = AsyncMock(return_value=None)
        first = await writer.purge_expired_options(cutoff)
        second = await writer.purge_expired_options(cutoff)

    assert first == 5
    assert second == 0


@pytest.mark.asyncio
async def test_maybe_purge_not_before_08_utc() -> None:
    writer = MagicMock()
    writer.purge_expired_options = AsyncMock(return_value=0)
    collector = OptionsSnapshotCollector(writer)
    OptionsSnapshotCollector._last_purge_utc_date = None

    await collector._maybe_purge(datetime(2025, 9, 9, 7, 59, tzinfo=timezone.utc))
    writer.purge_expired_options.assert_not_called()


@pytest.mark.asyncio
async def test_maybe_purge_once_per_day() -> None:
    writer = MagicMock()
    writer.purge_expired_options = AsyncMock(return_value=2)
    collector = OptionsSnapshotCollector(writer)
    OptionsSnapshotCollector._last_purge_utc_date = None

    now = datetime(2025, 9, 9, 8, 5, tzinfo=timezone.utc)
    await collector._maybe_purge(now)
    await collector._maybe_purge(now)

    writer.purge_expired_options.assert_awaited_once()


@pytest.mark.asyncio
async def test_maybe_purge_runs_after_08_utc() -> None:
    writer = MagicMock()
    writer.purge_expired_options = AsyncMock(return_value=1)
    collector = OptionsSnapshotCollector(writer)
    OptionsSnapshotCollector._last_purge_utc_date = None

    await collector._maybe_purge(datetime(2025, 9, 9, 8, 0, tzinfo=timezone.utc))
    writer.purge_expired_options.assert_awaited_once()
