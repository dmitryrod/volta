"""Индекс сессий отслеживания Scanner для каталога Аналитика."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class TrackingSessionORM(Base):
    """Метаданные сессии tracking_id (без time-series samples — они в JSONL)."""

    __tablename__ = "tracking_sessions"
    __table_args__ = (
        Index("ix_tracking_sessions_triggered_at", "triggered_at"),
        Index("ix_tracking_sessions_screener_symbol", "screener_id", "symbol"),
    )

    tracking_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    screener_id: Mapped[int] = mapped_column(nullable=False)
    screener_name: Mapped[str] = mapped_column(String(256), default="", nullable=False)
    exchange: Mapped[str] = mapped_column(String(32), nullable=False)
    market_type: Mapped[str] = mapped_column(String(32), nullable=False)
    symbol: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), default="active", nullable=False
    )  # active | triggered | posttracking | completed | closed | abandoned
    statistics_file_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    entered_scanner_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    triggered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    closed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    cooldown_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
