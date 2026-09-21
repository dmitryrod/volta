__all__ = ["SignalORM"]

from datetime import datetime, timezone

from sqlalchemy import DateTime, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class SignalORM(Base):
    """История сигналов, отправленных в Telegram."""

    __tablename__ = "signals"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    screener_name: Mapped[str] = mapped_column(nullable=False)
    screener_id: Mapped[int] = mapped_column(nullable=False)
    exchange: Mapped[str] = mapped_column(nullable=False)
    market_type: Mapped[str] = mapped_column(nullable=False)
    symbol: Mapped[str] = mapped_column(nullable=False)
    telegram_text: Mapped[str] = mapped_column(Text, nullable=False)
    telegram_ok: Mapped[bool] = mapped_column(nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    tracking_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    """Идентификатор сессии Scanner/аналитики; NULL для старых записей."""

    card_snapshot_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    """Frozen JSON снимка карточки Scanner на момент срабатывания (режим test)."""

    __table_args__ = (
        Index("ix_signals_created_at", "created_at"),
        Index("ix_signals_tracking_id", "tracking_id"),
    )
