"""Polymarket event catalog API."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from volta.config import config
from volta.config.assets import validate_base
from volta.database import Database
from volta.polymarket import GammaClient, parse_event_end_date, parse_event_slug_from_url

router = APIRouter(tags=["polymarket"])


class PolymarketConfigBody(BaseModel):
    base: str
    url: str | None = Field(default=None, max_length=2048)


class PolymarketImportBody(BaseModel):
    base: str
    urls_text: str = Field(..., max_length=20000)


def _parse_end_date_dt(event: dict) -> datetime | None:
    raw = parse_event_end_date(event)
    if not raw:
        return None
    text = raw.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _serialize_event(row) -> dict:
    end = row.event_end_date
    if end is not None and end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    end_iso = end.isoformat().replace("+00:00", "Z") if end else None
    return {
        "event_slug": row.event_slug,
        "event_url": row.event_url,
        "event_title": row.event_title,
        "event_end_date": end_iso,
    }


async def _gamma_event_row(url: str, slug: str, client: GammaClient) -> dict:
    event = await client.fetch_event_by_slug(slug)
    return {
        "event_slug": slug,
        "event_url": url,
        "event_title": event.get("title"),
        "event_end_date": _parse_end_date_dt(event),
    }


def _parse_urls_text(urls_text: str) -> list[tuple[str, str]]:
    seen: set[str] = set()
    out: list[tuple[str, str]] = []
    for line in urls_text.splitlines():
        raw = line.strip()
        if not raw:
            continue
        try:
            slug = parse_event_slug_from_url(raw)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if slug in seen:
            continue
        seen.add(slug)
        out.append((raw, slug))
    return out


@router.get("/api/polymarket/events")
async def list_polymarket_events(base: str = Query(...)) -> dict:
    try:
        base_asset = validate_base(base)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    retention = config.polymarket.retention_hours_after_expiry
    async with Database.session_context() as db:
        rows = await db.snapshots.list_polymarket_events(base_asset, retention)
    return {
        "base": base_asset,
        "events": [_serialize_event(row) for row in rows],
        "max_events": config.polymarket.max_events_per_base,
    }


@router.post("/api/polymarket/events/import")
async def import_polymarket_events(body: PolymarketImportBody) -> dict:
    try:
        base_asset = validate_base(body.base)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    parsed = _parse_urls_text(body.urls_text)
    if not parsed:
        raise HTTPException(status_code=400, detail="No valid URLs in import text")

    retention = config.polymarket.retention_hours_after_expiry
    max_events = config.polymarket.max_events_per_base

    async with Database.session_context() as db:
        existing_slugs = await db.snapshots.list_polymarket_event_slugs(base_asset)
        new_slugs = [slug for _url, slug in parsed if slug not in existing_slugs]
        if len(existing_slugs) + len(new_slugs) > max_events:
            raise HTTPException(
                status_code=400,
                detail=f"Max {max_events} events per base (would exceed after import)",
            )

        to_upsert: list[dict] = []
        async with GammaClient() as client:
            for url, slug in parsed:
                try:
                    to_upsert.append(await _gamma_event_row(url, slug, client))
                except Exception as exc:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Polymarket event not reachable ({slug}): {exc}",
                    ) from exc

        await db.snapshots.upsert_polymarket_events(base_asset, to_upsert)
        rows = await db.snapshots.list_polymarket_events(base_asset, retention)

    return {
        "base": base_asset,
        "events": [_serialize_event(row) for row in rows],
        "max_events": max_events,
    }


@router.get("/api/polymarket/config")
async def get_polymarket_config(base: str = Query(...)) -> dict:
    """Deprecated: use GET /api/polymarket/events. Returns first catalog event."""
    try:
        base_asset = validate_base(base)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    retention = config.polymarket.retention_hours_after_expiry
    async with Database.session_context() as db:
        rows = await db.snapshots.list_polymarket_events(base_asset, retention)
        if rows:
            first = rows[0]
            return {
                "base": base_asset,
                "event_slug": first.event_slug,
                "event_url": first.event_url,
                "event_end_date": _serialize_event(first)["event_end_date"],
            }
        asset = await db.snapshots.get_asset_config(base_asset)
    if asset is None:
        raise HTTPException(status_code=404, detail=f"asset not found: {base_asset}")

    event_end_date: str | None = None
    if asset.polymarket_event_slug:
        try:
            async with GammaClient() as client:
                event = await client.fetch_event_by_slug(asset.polymarket_event_slug)
            event_end_date = parse_event_end_date(event)
        except Exception:
            event_end_date = None

    return {
        "base": base_asset,
        "event_slug": asset.polymarket_event_slug,
        "event_url": asset.polymarket_event_url,
        "event_end_date": event_end_date,
    }


@router.post("/api/polymarket/config")
async def set_polymarket_config(body: PolymarketConfigBody) -> dict:
    """Deprecated: use POST /api/polymarket/events/import."""
    try:
        base_asset = validate_base(body.base)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    raw_url = (body.url or "").strip()
    if not raw_url:
        return {
            "base": base_asset,
            "event_slug": None,
            "event_url": None,
            "event_end_date": None,
        }

    result = await import_polymarket_events(
        PolymarketImportBody(base=base_asset, urls_text=raw_url)
    )
    first = result["events"][0] if result["events"] else None
    if not first:
        raise HTTPException(status_code=400, detail="Import produced no events")
    return {
        "base": base_asset,
        "event_slug": first["event_slug"],
        "event_url": first["event_url"],
        "event_end_date": first["event_end_date"],
    }
