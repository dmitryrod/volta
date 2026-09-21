__all__ = ["SettingsORM"]

from sqlalchemy import BigInteger, Enum
from sqlalchemy.orm import Mapped, mapped_column
from unicex import Exchange, MarketType

from app.schemas import TextTemplateType

from .base import Base


class SettingsORM(Base):
    """Модель настроек скринера."""

    __tablename__ = "settings"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    """Первичный ключ."""

    enabled: Mapped[bool] = mapped_column(default=True)
    """Включен ли скринер."""
    
    name: Mapped[str] = mapped_column(nullable=False)
    """Название скринера."""
    
    exchange: Mapped[Exchange] = mapped_column(
        Enum(Exchange, create_constraint=False, native_enum=False), nullable=False
    )
    """Биржа, на которой будет работать скринер."""
    
    market_type: Mapped[MarketType] = mapped_column(
        Enum(MarketType, create_constraint=False, native_enum=False), nullable=False
    )
    """Тип рынка (спот или фьючерсы) на котором будет работать скринер."""

    blacklist: Mapped[str | None] = mapped_column(nullable=True)
    """Черный список тикеров."""

    whitelist: Mapped[str | None] = mapped_column(nullable=True)
    """Белый список тикеров."""

    #Пампы и дампы
    pd_interval_sec: Mapped[int | None]
    """Интервал для проверки пампов и дампов в секундах."""

    pd_min_change_pct: Mapped[float | None]
    """Процент изменения цены для пампов и дампов."""

    # Открытый интерес
    oi_interval_sec: Mapped[int | None]
    """Интервал для проверки открытого интереса в секундах."""

    oi_min_change_pct: Mapped[float | None]
    """Минимальное изменение открытого интереса в процентах."""

    oi_min_change_usd: Mapped[float | None]
    """Минимальное изменение открытого интереса в долларах для подтверждения сигнала."""

    # Ставка финансирования
    fr_min_value_pct: Mapped[float | None]
    """Минимальное значение ставки финансирования в процентах."""

    fr_max_value_pct: Mapped[float | None]
    """Максимальное значение ставки финансирования в процентах."""

    # Объем
    vl_interval: Mapped[int | None]
    """Интервал для проверки объема в секундах."""

    vl_min_multiplier: Mapped[float | None]
    """Минимальный множитель объема для подтверждения сигнала."""

    # Ликвидации
    lq_interval_sec: Mapped[int | None]
    """Интервал для проверки ликвидации в секундах."""

    lq_min_amount_usd: Mapped[float | None]
    """Минимальное количество ликвидаций в долларах."""

    lq_min_amount_pct: Mapped[float | None]
    """Минимальная сумма ликвидаций в процентах от суточного объема."""

    # Объем монеты за последние сутки
    dv_min_usd: Mapped[float | None]
    """Минимальный объем монеты за сутки в долларах."""

    dv_max_usd: Mapped[float | None]
    """Максимальный объем монеты за сутки в долларах."""

    # Изменение цены монеты за последние сутки.
    dp_min_pct: Mapped[float | None]
    """Минимальное изменение цены за сутки в процентах."""

    dp_max_pct: Mapped[float | None]
    """Максимальное изменение цены за сутки в процентах."""

    # Настройки уведомлений
    max_day_alerts: Mapped[int | None]
    """Максимальное количество сигналов за сутки по одному тикеру."""

    timeout_sec: Mapped[int] = mapped_column(default=60, nullable=False)
    """Таймаут в секундах между сигналами по одной монете."""

    text_template_type: Mapped[TextTemplateType] = mapped_column(
        Enum(TextTemplateType, create_constraint=False, native_enum=False), nullable=False
    )
    """Тип шаблона текста."""
    
    chat_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    """ID чата для уведомлений; ``None`` — отправка в Telegram отключена."""

    bot_token: Mapped[str | None] = mapped_column(nullable=True)
    """Токен бота; ``None`` или пусто — отправка в Telegram отключена."""

    debug: Mapped[bool] = mapped_column(default=False, nullable=False)
    """Включен ли вывод отладочного текста в уведомлениях."""