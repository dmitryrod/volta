"""SQLAlchemy ORM models."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Double,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Declarative base."""


class InstrumentSnapshot(Base):
    """Raw instrument metric point."""

    __tablename__ = "instrument_snapshots"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    base_asset: Mapped[str] = mapped_column(String(16), nullable=False)
    exchange: Mapped[str] = mapped_column(String(32), nullable=False)
    market: Mapped[str] = mapped_column(String(32), nullable=False)
    symbol: Mapped[str] = mapped_column(String(64), nullable=False)
    metric: Mapped[str] = mapped_column(String(32), nullable=False)
    value: Mapped[float] = mapped_column(Double, nullable=False)
    meta_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "ts", "base_asset", "exchange", "symbol", "metric",
            name="uq_instrument_snapshots_key",
        ),
        Index("ix_instrument_snapshots_base_ts", "base_asset", ts.desc()),
    )


class PanelSnapshot(Base):
    """Denormalized panel row per base and timestamp."""

    __tablename__ = "panel_snapshots"

    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    base_asset: Mapped[str] = mapped_column(String(16), primary_key=True)
    futures_symbol: Mapped[str | None] = mapped_column(String(64), nullable=True)
    futures_price: Mapped[float | None] = mapped_column(Double, nullable=True)
    call_price: Mapped[float | None] = mapped_column(Double, nullable=True)
    put_price: Mapped[float | None] = mapped_column(Double, nullable=True)
    call_symbol: Mapped[str | None] = mapped_column(String(64), nullable=True)
    put_symbol: Mapped[str | None] = mapped_column(String(64), nullable=True)


class PolymarketSnapshot(Base):
    """Polymarket yes probability snapshot."""

    __tablename__ = "polymarket_snapshots"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    base_asset: Mapped[str] = mapped_column(String(16), nullable=False)
    market_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    question: Mapped[str | None] = mapped_column(Text, nullable=True)
    yes_probability: Mapped[float] = mapped_column(Double, nullable=False)
    meta_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "ts", "base_asset", "market_id",
            name="uq_polymarket_snapshots_key",
        ),
        Index("ix_polymarket_snapshots_base_ts", "base_asset", ts.desc()),
    )


class PolymarketEvent(Base):
    """Polymarket event catalog entry per base asset."""

    __tablename__ = "polymarket_events"

    base_asset: Mapped[str] = mapped_column(String(16), primary_key=True)
    event_slug: Mapped[str] = mapped_column(String(256), primary_key=True)
    event_url: Mapped[str] = mapped_column(Text, nullable=False)
    event_title: Mapped[str | None] = mapped_column(Text, nullable=True)
    event_end_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    __table_args__ = (
        Index("ix_polymarket_events_base_end", "base_asset", "event_end_date"),
    )


class FuturesCandle(Base):
    """Closed exchange futures candle (OHLCV)."""

    __tablename__ = "futures_candles"

    base_asset: Mapped[str] = mapped_column(String(16), primary_key=True)
    interval: Mapped[str] = mapped_column(String(8), primary_key=True)
    open_time: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    open: Mapped[float] = mapped_column(Double, nullable=False)
    high: Mapped[float] = mapped_column(Double, nullable=False)
    low: Mapped[float] = mapped_column(Double, nullable=False)
    close: Mapped[float] = mapped_column(Double, nullable=False)
    volume: Mapped[float | None] = mapped_column(Double, nullable=True)

    __table_args__ = (
        Index(
            "ix_futures_candles_base_interval_time",
            "base_asset",
            "interval",
            open_time.desc(),
        ),
    )


class AssetConfig(Base):
    """Tracked asset configuration."""

    __tablename__ = "asset_config"

    base_asset: Mapped[str] = mapped_column(String(16), primary_key=True)
    futures_symbol: Mapped[str] = mapped_column(String(64), nullable=False)
    polymarket_market_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    polymarket_event_slug: Mapped[str | None] = mapped_column(String(256), nullable=True)
    polymarket_event_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
