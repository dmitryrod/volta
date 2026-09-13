"""Meta API routes."""

from __future__ import annotations

from fastapi import APIRouter

from app_options.database import Database

router = APIRouter(tags=["meta"])


@router.get("/api/meta/assets")
async def meta_assets() -> list[dict]:
    async with Database.session_context() as db:
        return await db.snapshots.get_meta_assets()
