"""Options chain API routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from volta.config.assets import validate_base
from volta.database import Database

router = APIRouter(tags=["options"])


@router.get("/api/options/chain")
async def options_chain(base: str = Query(...)) -> dict:
    try:
        base_asset = validate_base(base)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    async with Database.session_context() as db:
        return await db.snapshots.get_options_chain(base_asset)
