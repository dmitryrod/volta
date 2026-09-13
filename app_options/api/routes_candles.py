"""Chart and candle API routes."""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates

from app_options.config.assets import validate_base, validate_option_symbols
from app_options.database import Database
from app_options.database.repositories.snapshot_repository import INTERVAL_SECONDS
from app_options.ingestor.kline_hub import get_kline_hub

router = APIRouter(tags=["chart"])

VALID_SERIES = frozenset({"futures", "call", "put", "option"})
VALID_INTERVALS = frozenset(INTERVAL_SECONDS.keys())


def get_templates() -> Jinja2Templates:
    from app_options.__main__ import templates
    return templates


@router.get("/chart", response_class=HTMLResponse)
async def chart_page(request: Request) -> HTMLResponse:
    return get_templates().TemplateResponse(request, "chart.html", {})


def _parse_symbols_param(symbols: str | None) -> list[str]:
    if not symbols:
        return []
    return [s.strip() for s in symbols.split(",") if s.strip()]


@router.get("/api/chart/batch")
async def chart_batch(
    base: str = Query(...),
    interval: str = Query("5m"),
    from_ts: int | None = Query(None, alias="from"),
    to_ts: int | None = Query(None, alias="to"),
    limit: int = Query(500, ge=1, le=5000),
    symbols: str | None = Query(None),
    pm_event_slug: str | None = Query(None),
) -> dict:
    try:
        base_asset = validate_base(base)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if interval not in VALID_INTERVALS:
        raise HTTPException(status_code=400, detail=f"interval must be one of {sorted(VALID_INTERVALS)}")
    symbol_list = _parse_symbols_param(symbols)
    if symbol_list:
        try:
            symbol_list = validate_option_symbols(symbol_list, base_asset)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    async with Database.session_context() as db:
        return await db.snapshots.get_chart_batch(
            base_asset,
            interval,
            from_ts,
            to_ts,
            limit,
            symbol_list,
            pm_event_slug,
        )


@router.get("/api/chart/stream")
async def chart_stream(
    base: str = Query(...),
    interval: str = Query("5m"),
) -> StreamingResponse:
    try:
        base_asset = validate_base(base)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if interval not in VALID_INTERVALS:
        raise HTTPException(
            status_code=400,
            detail=f"interval must be one of {sorted(VALID_INTERVALS)}",
        )

    hub = get_kline_hub()

    async def event_generator():
        subscriber = hub.subscribe(base_asset, interval)
        try:
            initial = hub.initial_sse_payload(base_asset, interval)
            if initial:
                yield f"data: {json.dumps(initial)}\n\n"
            while True:
                try:
                    payload = await asyncio.wait_for(subscriber.queue.get(), timeout=30.0)
                    yield f"data: {json.dumps(payload)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            hub.unsubscribe(subscriber)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/api/candles")
async def candles(
    base: str = Query(...),
    series: str = Query("futures"),
    interval: str = Query("5m"),
    from_ts: int | None = Query(None, alias="from"),
    to_ts: int | None = Query(None, alias="to"),
    limit: int = Query(500, ge=1, le=5000),
    symbol: str | None = Query(None),
) -> dict:
    try:
        base_asset = validate_base(base)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if series not in VALID_SERIES:
        raise HTTPException(status_code=400, detail=f"series must be one of {sorted(VALID_SERIES)}")
    if interval not in VALID_INTERVALS:
        raise HTTPException(status_code=400, detail=f"interval must be one of {sorted(VALID_INTERVALS)}")
    if series == "option" and not symbol:
        raise HTTPException(status_code=400, detail="symbol is required when series=option")
    if series == "option" and symbol:
        try:
            symbol = validate_option_symbols([symbol.strip()], base_asset)[0]
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    async with Database.session_context() as db:
        if series == "futures":
            candles_data, has_more = await db.snapshots.get_futures_chart_candles(
                base_asset, interval, from_ts, to_ts, limit
            )
            return {
                "series": series,
                "interval": interval,
                "candles": candles_data,
                "has_more": has_more,
            }
        if series == "option":
            opt_series, _expiry, has_more = await db.snapshots.aggregate_option_series(
                base_asset, [symbol], interval, from_ts, to_ts, limit
            )
            points = opt_series[0]["points"] if opt_series else []
            return {
                "series": series,
                "symbol": symbol,
                "interval": interval,
                "points": points,
                "has_more": has_more,
            }
        points, sym, has_more = await db.snapshots.aggregate_line_points(
            base_asset, series, interval, from_ts, to_ts, limit
        )
        return {
            "series": series,
            "interval": interval,
            "symbol": sym,
            "points": points,
            "has_more": has_more,
        }


@router.get("/api/probability")
async def probability(
    base: str = Query(...),
    from_ts: int | None = Query(None, alias="from"),
    to_ts: int | None = Query(None, alias="to"),
    limit: int = Query(500, ge=1, le=5000),
) -> dict:
    try:
        base_asset = validate_base(base)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    async with Database.session_context() as db:
        points = await db.snapshots.get_probability_series(
            base_asset, from_ts, to_ts, limit
        )
    return {"base": base_asset, "points": points}


@router.get("/api/panel/latest")
async def panel_latest(base: str = Query(...)) -> dict:
    try:
        base_asset = validate_base(base)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    async with Database.session_context() as db:
        panel = await db.snapshots.get_latest_panel(base_asset)
        pm = await db.snapshots.get_latest_polymarket(base_asset)
        chain = await db.snapshots.get_options_chain(base_asset)
    if panel is None:
        return {"base": base_asset, "panel": None, "polymarket": None}
    return {
        "base": base_asset,
        "panel": {
            "ts": int(panel.ts.timestamp()),
            "futures_symbol": panel.futures_symbol,
            "futures_price": panel.futures_price,
            "call_price": panel.call_price,
            "put_price": panel.put_price,
            "call_symbol": panel.call_symbol,
            "put_symbol": panel.put_symbol,
            "options_expiry": chain.get("expiry"),
        },
        "polymarket": (
            {
                "ts": int(pm.ts.timestamp()),
                "yes_probability": pm.yes_probability,
                "question": pm.question,
            }
            if pm
            else None
        ),
    }
