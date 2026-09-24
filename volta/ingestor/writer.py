"""DB writer for ingestor snapshots."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from loguru import logger

from volta.database import Database
from volta.database.models import AssetConfig
from volta.utils.connectivity import is_transient_network_error, wait_for_internet


class SnapshotWriter:
    """Persist snapshot rows to PostgreSQL."""

    async def get_enabled_assets(self) -> list[AssetConfig]:
        try:
            async with Database.session_context() as db:
                return await db.snapshots.list_enabled_assets()
        except Exception as exc:
            if is_transient_network_error(exc):
                logger.warning("DB transient error loading assets: {}", exc)
                await wait_for_internet(log_name="snapshot-writer-db")
            raise

    async def write_instruments(self, rows: list[dict[str, Any]]) -> None:
        if not rows:
            return
        try:
            async with Database.session_context() as db:
                await db.snapshots.upsert_instrument_snapshots(rows)
        except Exception as exc:
            if is_transient_network_error(exc):
                logger.warning("DB transient error writing instruments: {}", exc)
                await wait_for_internet(log_name="snapshot-writer-db")
            raise

    async def write_panel(self, row: dict[str, Any]) -> None:
        try:
            async with Database.session_context() as db:
                await db.snapshots.upsert_panel_snapshot(row)
        except Exception as exc:
            if is_transient_network_error(exc):
                logger.warning("DB transient error writing panel: {}", exc)
                await wait_for_internet(log_name="snapshot-writer-db")
            raise

    async def write_polymarket(self, row: dict[str, Any]) -> None:
        try:
            async with Database.session_context() as db:
                await db.snapshots.upsert_polymarket_snapshot(row)
        except Exception as exc:
            if is_transient_network_error(exc):
                logger.warning("DB transient error writing polymarket: {}", exc)
                await wait_for_internet(log_name="snapshot-writer-db")
            raise

    async def purge_expired_options(self, cutoff: datetime) -> int:
        """Delete expired option instrument rows (idempotent)."""
        try:
            async with Database.session_context() as db:
                return await db.snapshots.purge_expired_options(cutoff)
        except Exception as exc:
            if is_transient_network_error(exc):
                logger.warning("DB transient error purging options: {}", exc)
                await wait_for_internet(log_name="snapshot-writer-db")
            raise

    async def purge_expired_polymarket(
        self, now: datetime, retention_hours: int
    ) -> tuple[int, int]:
        """Delete PM catalog rows and snapshots past expiry + retention."""
        try:
            async with Database.session_context() as db:
                return await db.snapshots.purge_expired_polymarket(now, retention_hours)
        except Exception as exc:
            if is_transient_network_error(exc):
                logger.warning("DB transient error purging polymarket: {}", exc)
                await wait_for_internet(log_name="snapshot-writer-db")
            raise
