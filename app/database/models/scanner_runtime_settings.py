"""Глобальные настройки Scanner / аналитики (одна строка id=1)."""

from __future__ import annotations

from sqlalchemy import Boolean, Float, Integer
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class ScannerRuntimeSettingsORM(Base):
    """Серверные настройки Scanner: лимит карточек, постотслежка, отлежка, сбор статистики."""

    __tablename__ = "scanner_runtime_settings"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    max_cards: Mapped[int] = mapped_column(Integer, default=10, nullable=False)
    posttracking_minutes: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    cooldown_hours: Mapped[int] = mapped_column(Integer, default=24, nullable=False)
    statistics_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    """Если True — считаем scanner snapshot (как при открытом SSE) без обязательного подписчика."""
