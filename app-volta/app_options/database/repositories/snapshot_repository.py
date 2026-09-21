"""Snapshot read/write repositories."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import Select, desc, func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app_options.database.models import (
    AssetConfig,
    InstrumentSnapshot,
    PanelSnapshot,
    PolymarketEvent,
    PolymarketSnapshot,
)
from app_options.database.repositories.candle_repository import CandleRepository

INTERVAL_SECONDS: dict[str, int] = {
    "1m": 60,
    "5m": 300,
    "15m": 900,
    "1h": 3600,
    "4h": 14400,
    "1d": 86400,
}

# UTC epoch seconds aligned to interval bucket (avoids naive timestamp timezone drift).
_BUCKET_UNIX_EXPR = "floor(extract(epoch FROM ts) / :bucket) * :bucket"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _time_filters(from_ts: int | None, to_ts: int | None) -> tuple[str, dict[str, int]]:
    """Build SQL time filter clause without ambiguous NULL params."""
    clauses: list[str] = []
    params: dict[str, int] = {}
    if from_ts is not None:
        clauses.append("AND ts >= to_timestamp(:from_ts)")
        params["from_ts"] = from_ts
    if to_ts is not None:
        clauses.append("AND ts <= to_timestamp(:to_ts)")
        params["to_ts"] = to_ts
    return "\n                  ".join(clauses), params


def _to_unix(ts: datetime) -> int:
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return int(ts.timestamp())


def _format_option_label(strike: float, option_type: str) -> str:
    """Human label for option series, e.g. $2,520 C."""
    strike_label = f"${strike:,.0f}" if strike == int(strike) else f"${strike:,.2f}"
    suffix = "C" if option_type == "call" else "P"
    return f"{strike_label} {suffix}"


def _format_expiry_label(expiry: datetime) -> str:
    """Expiry label like 9 SEP 25."""
    if expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=timezone.utc)
    return f"{expiry.day} {expiry.strftime('%b %y').upper()}"


def _chain_flat_candles(candles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Chain single-tick buckets from prev close; preserve bucket high/low for wicks."""
    if not candles:
        return candles
    out: list[dict[str, Any]] = []
    for i, candle in enumerate(candles):
        o = float(candle["open"])
        h = float(candle["high"])
        low = float(candle["low"])
        c = float(candle["close"])
        bucket_high = h
        bucket_low = low
        if i > 0 and o == h == low == c:
            o = float(out[i - 1]["close"])
        h = max(bucket_high, o, c)
        low = min(bucket_low, o, c)
        out.append(
            {
                "time": candle["time"],
                "open": o,
                "high": h,
                "low": low,
                "close": c,
            }
        )
    return out


class SnapshotRepository:
    """CRUD and aggregation for snapshot tables."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_enabled_assets(self) -> list[AssetConfig]:
        result = await self._session.execute(
            select(AssetConfig).where(AssetConfig.enabled.is_(True)).order_by(AssetConfig.base_asset)
        )
        return list(result.scalars().all())

    async def upsert_instrument_snapshots(self, rows: list[dict[str, Any]]) -> None:
        if not rows:
            return
        stmt = pg_insert(InstrumentSnapshot).values(rows)
        stmt = stmt.on_conflict_do_update(
            constraint="uq_instrument_snapshots_key",
            set_={"value": stmt.excluded.value, "meta_json": stmt.excluded.meta_json},
        )
        await self._session.execute(stmt)

    async def upsert_panel_snapshot(self, row: dict[str, Any]) -> None:
        stmt = pg_insert(PanelSnapshot).values(row)
        stmt = stmt.on_conflict_do_update(
            index_elements=["ts", "base_asset"],
            set_={
                "futures_symbol": stmt.excluded.futures_symbol,
                "futures_price": stmt.excluded.futures_price,
                "call_price": stmt.excluded.call_price,
                "put_price": stmt.excluded.put_price,
                "call_symbol": stmt.excluded.call_symbol,
                "put_symbol": stmt.excluded.put_symbol,
            },
        )
        await self._session.execute(stmt)

    async def upsert_polymarket_snapshot(self, row: dict[str, Any]) -> None:
        stmt = pg_insert(PolymarketSnapshot).values(row)
        stmt = stmt.on_conflict_do_update(
            constraint="uq_polymarket_snapshots_key",
            set_={
                "yes_probability": stmt.excluded.yes_probability,
                "question": stmt.excluded.question,
                "meta_json": stmt.excluded.meta_json,
            },
        )
        await self._session.execute(stmt)

    async def get_latest_panel(self, base_asset: str) -> PanelSnapshot | None:
        result = await self._session.execute(
            select(PanelSnapshot)
            .where(PanelSnapshot.base_asset == base_asset)
            .order_by(desc(PanelSnapshot.ts))
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_latest_polymarket(self, base_asset: str) -> PolymarketSnapshot | None:
        result = await self._session.execute(
            select(PolymarketSnapshot)
            .where(PolymarketSnapshot.base_asset == base_asset)
            .order_by(desc(PolymarketSnapshot.ts))
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_asset_config(self, base_asset: str) -> AssetConfig | None:
        result = await self._session.execute(
            select(AssetConfig).where(AssetConfig.base_asset == base_asset)
        )
        return result.scalar_one_or_none()

    async def update_polymarket_event(
        self,
        base_asset: str,
        *,
        event_slug: str | None,
        event_url: str | None,
    ) -> AssetConfig | None:
        asset = await self.get_asset_config(base_asset)
        if asset is None:
            return None
        asset.polymarket_event_slug = event_slug
        asset.polymarket_event_url = event_url
        await self._session.flush()
        return asset

    def _pm_retention_cutoff(self, now: datetime, retention_hours: int) -> datetime:
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        return now - timedelta(hours=retention_hours)

    async def list_polymarket_events(
        self,
        base_asset: str,
        retention_hours: int,
        now: datetime | None = None,
    ) -> list[PolymarketEvent]:
        """Active catalog events (within retention window after expiry)."""
        now = now or _utc_now()
        cutoff = self._pm_retention_cutoff(now, retention_hours)
        result = await self._session.execute(
            select(PolymarketEvent)
            .where(PolymarketEvent.base_asset == base_asset)
            .where(
                (PolymarketEvent.event_end_date.is_(None))
                | (PolymarketEvent.event_end_date >= cutoff)
            )
            .order_by(PolymarketEvent.event_end_date.asc().nulls_last())
        )
        return list(result.scalars().all())

    async def get_polymarket_event(
        self, base_asset: str, event_slug: str
    ) -> PolymarketEvent | None:
        result = await self._session.execute(
            select(PolymarketEvent).where(
                PolymarketEvent.base_asset == base_asset,
                PolymarketEvent.event_slug == event_slug,
            )
        )
        return result.scalar_one_or_none()

    async def upsert_polymarket_events(
        self, base_asset: str, events: list[dict[str, Any]]
    ) -> list[PolymarketEvent]:
        """Upsert catalog rows; returns all active rows for base after merge."""
        for row in events:
            stmt = pg_insert(PolymarketEvent).values(
                base_asset=base_asset,
                event_slug=row["event_slug"],
                event_url=row["event_url"],
                event_title=row.get("event_title"),
                event_end_date=row.get("event_end_date"),
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=["base_asset", "event_slug"],
                set_={
                    "event_url": stmt.excluded.event_url,
                    "event_title": stmt.excluded.event_title,
                    "event_end_date": stmt.excluded.event_end_date,
                },
            )
            await self._session.execute(stmt)
        await self._session.flush()

    async def count_polymarket_events(self, base_asset: str) -> int:
        result = await self._session.execute(
            select(func.count())
            .select_from(PolymarketEvent)
            .where(PolymarketEvent.base_asset == base_asset)
        )
        return int(result.scalar_one())

    async def list_polymarket_event_slugs(self, base_asset: str) -> set[str]:
        result = await self._session.execute(
            select(PolymarketEvent.event_slug).where(
                PolymarketEvent.base_asset == base_asset
            )
        )
        return set(result.scalars().all())

    async def purge_expired_polymarket(
        self, now: datetime, retention_hours: int
    ) -> tuple[int, int]:
        """Delete catalog rows and snapshots past event_end_date + retention."""
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        cutoff = self._pm_retention_cutoff(now, retention_hours)
        expired = await self._session.execute(
            select(PolymarketEvent.base_asset, PolymarketEvent.event_slug).where(
                PolymarketEvent.event_end_date.is_not(None),
                PolymarketEvent.event_end_date < cutoff,
            )
        )
        pairs = list(expired.all())
        if not pairs:
            return 0, 0
        snap_deleted = 0
        catalog_deleted = 0
        for base_asset, event_slug in pairs:
            snap_result = await self._session.execute(
                text(
                    """
                    DELETE FROM polymarket_snapshots
                    WHERE base_asset = :base
                      AND meta_json->>'event_slug' = :event_slug
                    """
                ),
                {"base": base_asset, "event_slug": event_slug},
            )
            snap_deleted += int(snap_result.rowcount or 0)
            cat_result = await self._session.execute(
                text(
                    """
                    DELETE FROM polymarket_events
                    WHERE base_asset = :base AND event_slug = :event_slug
                    """
                ),
                {"base": base_asset, "event_slug": event_slug},
            )
            catalog_deleted += int(cat_result.rowcount or 0)
        return catalog_deleted, snap_deleted

    async def get_meta_assets(self) -> list[dict[str, Any]]:
        assets = await self.list_enabled_assets()
        out: list[dict[str, Any]] = []
        for asset in assets:
            out.append(
                {
                    "base": asset.base_asset,
                    "futures_symbol": asset.futures_symbol,
                    "pm_event_slug": asset.polymarket_event_slug,
                    "pm_event_url": asset.polymarket_event_url,
                }
            )
        return out

    async def aggregate_futures_candles(
        self,
        base_asset: str,
        interval: str,
        from_ts: int | None,
        to_ts: int | None,
        limit: int,
    ) -> tuple[list[dict[str, Any]], bool]:
        bucket = INTERVAL_SECONDS.get(interval, 300)
        time_clause, time_params = _time_filters(from_ts, to_ts)
        sql = text(
            f"""
            WITH raw AS (
                SELECT ts, value
                FROM instrument_snapshots
                WHERE base_asset = :base
                  AND market = 'linear'
                  AND metric = 'last_price'
                  {time_clause}
                ORDER BY ts DESC
                LIMIT :raw_limit
            ),
            bucketed AS (
                SELECT
                    """ + _BUCKET_UNIX_EXPR + """ AS bucket_unix,
                    value,
                    ts
                FROM raw
            )
            SELECT
                bucket_unix,
                (array_agg(value ORDER BY ts ASC))[1] AS open,
                max(value) AS high,
                min(value) AS low,
                (array_agg(value ORDER BY ts DESC))[1] AS close
            FROM bucketed
            GROUP BY bucket_unix
            ORDER BY bucket_unix DESC
            LIMIT :limit
            """
        )
        raw_limit = min(limit * 20, 50000)
        result = await self._session.execute(
            sql,
            {
                "base": base_asset,
                "bucket": bucket,
                "limit": limit + 1,
                "raw_limit": raw_limit,
                **time_params,
            },
        )
        rows = result.mappings().all()
        has_more = len(rows) > limit
        rows = rows[:limit]
        candles = [
            {
                "time": int(r["bucket_unix"]),
                "open": float(r["open"]),
                "high": float(r["high"]),
                "low": float(r["low"]),
                "close": float(r["close"]),
            }
            for r in reversed(rows)
        ]
        candles = _chain_flat_candles(candles)
        return candles, has_more

    async def aggregate_line_points(
        self,
        base_asset: str,
        series: str,
        interval: str,
        from_ts: int | None,
        to_ts: int | None,
        limit: int,
    ) -> tuple[list[dict[str, Any]], str | None, bool]:
        """Aggregate call/put line from panel_snapshots."""
        bucket = INTERVAL_SECONDS.get(interval, 300)
        col_map = {"call": "call_price", "put": "put_price"}
        if series not in col_map:
            return [], None, False
        col = col_map[series]
        time_clause, time_params = _time_filters(from_ts, to_ts)
        sql = text(
            f"""
            WITH raw AS (
                SELECT ts, {col} AS value, call_symbol, put_symbol
                FROM panel_snapshots
                WHERE base_asset = :base
                  AND {col} IS NOT NULL
                  {time_clause}
                ORDER BY ts DESC
                LIMIT :raw_limit
            ),
            bucketed AS (
                SELECT
                    """ + _BUCKET_UNIX_EXPR + """ AS bucket_unix,
                    value,
                    call_symbol,
                    put_symbol
                FROM raw
            )
            SELECT
                bucket_unix,
                avg(value) AS value,
                (array_agg(call_symbol ORDER BY bucket_unix DESC))[1] AS call_symbol,
                (array_agg(put_symbol ORDER BY bucket_unix DESC))[1] AS put_symbol
            FROM bucketed
            GROUP BY bucket_unix
            ORDER BY bucket_unix DESC
            LIMIT :limit
            """
        )
        raw_limit = min(limit * 20, 50000)
        result = await self._session.execute(
            sql,
            {
                "base": base_asset,
                "bucket": bucket,
                "limit": limit + 1,
                "raw_limit": raw_limit,
                **time_params,
            },
        )
        rows = result.mappings().all()
        has_more = len(rows) > limit
        rows = rows[:limit]
        symbol = None
        if rows:
            symbol = rows[0]["call_symbol"] if series == "call" else rows[0]["put_symbol"]
        points = [
            {"time": int(r["bucket_unix"]), "value": float(r["value"])}
            for r in reversed(rows)
        ]
        return points, symbol, has_more

    async def aggregate_polymarket_series(
        self,
        base_asset: str,
        interval: str,
        from_ts: int | None,
        to_ts: int | None,
        limit: int,
        event_slug: str | None = None,
    ) -> tuple[list[dict[str, Any]], str | None, str | None, bool]:
        """Aggregate PM yes% per strike market into multiple series."""
        event_url: str | None = None
        if not event_slug:
            return [], None, None, False
        event_row = await self.get_polymarket_event(base_asset, event_slug)
        if event_row:
            event_url = event_row.event_url
        else:
            asset = await self.get_asset_config(base_asset)
            if asset and asset.polymarket_event_slug == event_slug:
                event_url = asset.polymarket_event_url

        bucket = INTERVAL_SECONDS.get(interval, 300)
        time_clause, time_params = _time_filters(from_ts, to_ts)
        per_market_limit = min(limit * 20, 10000)
        sql = text(
            f"""
            WITH ranked AS (
                SELECT
                    ts,
                    yes_probability,
                    question,
                    market_id,
                    meta_json,
                    ROW_NUMBER() OVER (
                        PARTITION BY market_id ORDER BY ts DESC
                    ) AS rn
                FROM polymarket_snapshots
                WHERE base_asset = :base
                  AND meta_json->>'event_slug' = :event_slug
                  {time_clause}
            ),
            raw AS (
                SELECT ts, yes_probability, question, market_id, meta_json
                FROM ranked
                WHERE rn <= :per_market_limit
            ),
            bucketed AS (
                SELECT
                    market_id,
                    """ + _BUCKET_UNIX_EXPR + """ AS bucket_unix,
                    avg(yes_probability) AS value,
                    (array_agg(question ORDER BY ts DESC))[1] AS question,
                    (array_agg(meta_json ORDER BY ts DESC))[1] AS meta_json
                FROM raw
                GROUP BY market_id, bucket_unix
            )
            SELECT
                market_id,
                bucket_unix,
                value,
                question,
                meta_json
            FROM bucketed
            ORDER BY market_id, bucket_unix DESC
            """
        )
        result = await self._session.execute(
            sql,
            {
                "base": base_asset,
                "event_slug": event_slug,
                "bucket": bucket,
                "per_market_limit": per_market_limit,
                **time_params,
            },
        )
        rows = result.mappings().all()

        by_market: dict[str, list[dict[str, Any]]] = {}
        meta_by_market: dict[str, dict[str, Any]] = {}
        for row in rows:
            mid = str(row["market_id"] or "")
            if not mid:
                continue
            by_market.setdefault(mid, []).append(
                {"time": int(row["bucket_unix"]), "value": float(row["value"])}
            )
            if mid not in meta_by_market:
                meta = row["meta_json"] or {}
                strike = meta.get("strike") if isinstance(meta, dict) else None
                meta_by_market[mid] = {
                    "market_id": mid,
                    "strike": strike,
                    "question": row["question"],
                    "label": f">${strike:g}" if strike else (row["question"] or mid),
                }

        series: list[dict[str, Any]] = []
        has_more = False
        for mid, points in by_market.items():
            points_sorted = sorted(points, key=lambda p: p["time"])
            if len(points_sorted) > limit:
                has_more = True
                points_sorted = points_sorted[-limit:]
            info = meta_by_market.get(mid, {"market_id": mid, "label": mid})
            series.append(
                {
                    "market_id": mid,
                    "strike": info.get("strike"),
                    "label": info.get("label"),
                    "question": info.get("question"),
                    "points": points_sorted,
                }
            )

        series.sort(key=lambda s: (s.get("strike") is None, s.get("strike") or 0))
        return series, event_slug, event_url, has_more

    async def aggregate_polymarket(
        self,
        base_asset: str,
        interval: str,
        from_ts: int | None,
        to_ts: int | None,
        limit: int,
    ) -> tuple[list[dict[str, Any]], str | None, bool]:
        bucket = INTERVAL_SECONDS.get(interval, 300)
        time_clause, time_params = _time_filters(from_ts, to_ts)
        sql = text(
            f"""
            WITH raw AS (
                SELECT ts, yes_probability, question
                FROM polymarket_snapshots
                WHERE base_asset = :base
                  {time_clause}
                ORDER BY ts DESC
                LIMIT :raw_limit
            ),
            bucketed AS (
                SELECT
                    """ + _BUCKET_UNIX_EXPR + """ AS bucket_unix,
                    yes_probability,
                    question
                FROM raw
            )
            SELECT
                bucket_unix,
                avg(yes_probability) AS value,
                (array_agg(question ORDER BY bucket_unix DESC))[1] AS question
            FROM bucketed
            GROUP BY bucket_unix
            ORDER BY bucket_unix DESC
            LIMIT :limit
            """
        )
        raw_limit = min(limit * 20, 50000)
        result = await self._session.execute(
            sql,
            {
                "base": base_asset,
                "bucket": bucket,
                "limit": limit + 1,
                "raw_limit": raw_limit,
                **time_params,
            },
        )
        rows = result.mappings().all()
        has_more = len(rows) > limit
        rows = rows[:limit]
        question = rows[0]["question"] if rows else None
        points = [
            {"time": int(r["bucket_unix"]), "value": float(r["value"])}
            for r in reversed(rows)
        ]
        return points, question, has_more

    async def purge_expired_options(self, cutoff: datetime) -> int:
        """Delete option rows with expiry before cutoff (idempotent)."""
        if cutoff.tzinfo is None:
            cutoff = cutoff.replace(tzinfo=timezone.utc)
        sql = text(
            """
            DELETE FROM instrument_snapshots
            WHERE market = 'option'
              AND meta_json->>'expiry' IS NOT NULL
              AND (meta_json->>'expiry')::timestamptz < :cutoff
            """
        )
        result = await self._session.execute(sql, {"cutoff": cutoff})
        return int(result.rowcount or 0)

    async def aggregate_option_series(
        self,
        base_asset: str,
        symbols: list[str],
        interval: str,
        from_ts: int | None,
        to_ts: int | None,
        limit: int,
    ) -> tuple[list[dict[str, Any]], str | None, bool]:
        """Aggregate ask_price time series per option symbol."""
        if not symbols:
            return [], None, False

        bucket = INTERVAL_SECONDS.get(interval, 300)
        time_clause, time_params = _time_filters(from_ts, to_ts)
        sql = text(
            f"""
            WITH raw AS (
                SELECT ts, value, symbol, meta_json
                FROM instrument_snapshots
                WHERE base_asset = :base
                  AND market = 'option'
                  AND metric = 'ask_price'
                  AND symbol = ANY(:symbols)
                  {time_clause}
                ORDER BY ts DESC
                LIMIT :raw_limit
            ),
            bucketed AS (
                SELECT
                    symbol,
                    """ + _BUCKET_UNIX_EXPR + """ AS bucket_unix,
                    avg(value) AS value,
                    (array_agg(meta_json ORDER BY ts DESC))[1] AS meta_json
                FROM raw
                GROUP BY symbol, bucket_unix
            )
            SELECT symbol, bucket_unix, value, meta_json
            FROM bucketed
            ORDER BY symbol, bucket_unix DESC
            """
        )
        raw_limit = min(limit * 20 * max(len(symbols), 1), 50000)
        result = await self._session.execute(
            sql,
            {
                "base": base_asset,
                "symbols": symbols,
                "bucket": bucket,
                "raw_limit": raw_limit,
                **time_params,
            },
        )
        rows = result.mappings().all()

        by_symbol: dict[str, list[dict[str, Any]]] = {}
        meta_by_symbol: dict[str, dict[str, Any]] = {}
        for row in rows:
            sym = str(row["symbol"] or "")
            if not sym:
                continue
            by_symbol.setdefault(sym, []).append(
                {"time": int(row["bucket_unix"]), "value": float(row["value"])}
            )
            if sym not in meta_by_symbol:
                meta = row["meta_json"] or {}
                strike = meta.get("strike") if isinstance(meta, dict) else None
                option_type = meta.get("option_type") if isinstance(meta, dict) else None
                expiry = meta.get("expiry") if isinstance(meta, dict) else None
                meta_by_symbol[sym] = {
                    "strike": strike,
                    "option_type": option_type,
                    "expiry": expiry,
                    "label": (
                        _format_option_label(float(strike), str(option_type))
                        if strike is not None and option_type
                        else sym
                    ),
                }

        series: list[dict[str, Any]] = []
        has_more = False
        expiry_iso: str | None = None
        for sym, points in by_symbol.items():
            points_sorted = sorted(points, key=lambda p: p["time"])
            if len(points_sorted) > limit:
                has_more = True
                points_sorted = points_sorted[-limit:]
            info = meta_by_symbol.get(sym, {"label": sym})
            if expiry_iso is None and info.get("expiry"):
                expiry_iso = str(info["expiry"])
            series.append(
                {
                    "symbol": sym,
                    "strike": info.get("strike"),
                    "option_type": info.get("option_type"),
                    "label": info.get("label"),
                    "points": points_sorted,
                }
            )

        series.sort(
            key=lambda s: (
                0 if s.get("option_type") == "call" else 1,
                s.get("strike") is None,
                s.get("strike") or 0,
            )
        )
        return series, expiry_iso, has_more

    async def get_options_chain(self, base_asset: str) -> dict[str, Any]:
        """Latest ask per symbol for nearest expiry chain."""
        sql = text(
            """
            SELECT DISTINCT ON (symbol)
                symbol, value, meta_json
            FROM instrument_snapshots
            WHERE base_asset = :base
              AND market = 'option'
              AND metric = 'ask_price'
            ORDER BY symbol, ts DESC
            """
        )
        result = await self._session.execute(sql, {"base": base_asset})
        rows = result.mappings().all()

        panel = await self.get_latest_panel(base_asset)
        spot = panel.futures_price if panel else None

        contracts: list[dict[str, Any]] = []
        for row in rows:
            meta = row["meta_json"] or {}
            if not isinstance(meta, dict):
                continue
            expiry_raw = meta.get("expiry")
            strike = meta.get("strike")
            option_type = meta.get("option_type")
            if expiry_raw is None or strike is None or not option_type:
                continue
            try:
                expiry = datetime.fromisoformat(str(expiry_raw))
            except ValueError:
                continue
            if expiry.tzinfo is None:
                expiry = expiry.replace(tzinfo=timezone.utc)
            contracts.append(
                {
                    "symbol": str(row["symbol"]),
                    "strike": float(strike),
                    "ask_price": float(row["value"]),
                    "option_type": str(option_type),
                    "expiry": expiry,
                }
            )

        if not contracts:
            return {
                "base": base_asset,
                "expiry": None,
                "expiry_label": None,
                "spot": spot,
                "calls": [],
                "puts": [],
            }

        now = _utc_now()
        future_expiries = [c["expiry"] for c in contracts if c["expiry"] >= now]
        nearest = min(future_expiries) if future_expiries else min(c["expiry"] for c in contracts)
        nearest_contracts = [c for c in contracts if c["expiry"] == nearest]

        calls: list[dict[str, Any]] = []
        puts: list[dict[str, Any]] = []
        for c in nearest_contracts:
            if spot is not None:
                spot_f = float(spot)
                otm = (
                    c["strike"] > spot_f
                    if c["option_type"] == "call"
                    else c["strike"] <= spot_f
                )
            else:
                otm = False
            entry = {
                "symbol": c["symbol"],
                "strike": c["strike"],
                "ask_price": c["ask_price"],
                "otm": otm,
            }
            if c["option_type"] == "call":
                calls.append(entry)
            elif c["option_type"] == "put":
                puts.append(entry)

        calls.sort(key=lambda x: x["strike"])
        puts.sort(key=lambda x: x["strike"])

        return {
            "base": base_asset,
            "expiry": nearest.isoformat(),
            "expiry_label": _format_expiry_label(nearest),
            "spot": spot,
            "calls": calls,
            "puts": puts,
        }

    async def get_futures_chart_candles(
        self,
        base_asset: str,
        interval: str,
        from_ts: int | None,
        to_ts: int | None,
        limit: int,
    ) -> tuple[list[dict[str, Any]], bool]:
        """Closed candles from DB merged with live forming bar."""
        from app_options.ingestor.kline_hub import get_kline_hub

        candle_repo = CandleRepository(self._session)
        candles, _ = await candle_repo.list_candles(
            base_asset, interval, from_ts, to_ts, limit
        )
        candles = get_kline_hub().merge_series_with_live(candles, base_asset, interval)
        return candles, False

    async def get_chart_batch(
        self,
        base_asset: str,
        interval: str,
        from_ts: int | None,
        to_ts: int | None,
        limit: int,
        symbols: list[str] | None = None,
        pm_event_slug: str | None = None,
    ) -> dict[str, Any]:
        candles, futures_more = await self.get_futures_chart_candles(
            base_asset, interval, from_ts, to_ts, limit
        )
        symbol_list = [s for s in (symbols or []) if s]
        opt_series, opt_expiry, opt_more = await self.aggregate_option_series(
            base_asset, symbol_list, interval, from_ts, to_ts, limit
        )
        pm_series, pm_slug, pm_url, pm_more = await self.aggregate_polymarket_series(
            base_asset, interval, from_ts, to_ts, limit, pm_event_slug
        )
        return {
            "base": base_asset,
            "interval": interval,
            "futures": {"candles": candles, "has_more": futures_more},
            "options": {
                "expiry": opt_expiry,
                "series": opt_series,
                "has_more": opt_more,
            },
            "polymarket": {
                "series": pm_series,
                "event_slug": pm_slug,
                "event_url": pm_url,
                "has_more": pm_more,
            },
        }

    async def get_probability_series(
        self,
        base_asset: str,
        from_ts: int | None,
        to_ts: int | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        stmt: Select = (
            select(PolymarketSnapshot)
            .where(PolymarketSnapshot.base_asset == base_asset)
            .order_by(desc(PolymarketSnapshot.ts))
            .limit(limit)
        )
        if from_ts is not None:
            stmt = stmt.where(
                PolymarketSnapshot.ts >= datetime.fromtimestamp(from_ts, tz=timezone.utc)
            )
        if to_ts is not None:
            stmt = stmt.where(
                PolymarketSnapshot.ts <= datetime.fromtimestamp(to_ts, tz=timezone.utc)
            )
        result = await self._session.execute(stmt)
        rows = list(result.scalars().all())
        return [
            {"time": _to_unix(r.ts), "value": float(r.yes_probability)}
            for r in reversed(rows)
        ]
