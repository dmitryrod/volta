__all__ = ["SettingsDTO"]

from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field
from unicex import Exchange, MarketType
from app.schemas.enums import TextTemplateType

if TYPE_CHECKING:
    pass


class SettingsDTO(BaseModel):
    """Модель для передачи настроек скринера между слоями приложения."""
    
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)
    """Конфиг pydantic-модели"""

    id: int
    """Первичный ключ."""

    enabled: bool
    """Включен ли сканер."""

    name: str
    """Название скринера."""

    exchange: Exchange
    """Биржа, на которой будет работать скринер."""

    market_type: MarketType
    """Тип рынка на котором будет работать скринер."""

    blacklist: str | None
    """Черный список тикеров."""

    whitelist: str | None
    """Белый список тикеров."""

    debug: bool = False
    """Режим отладки для скринера (включает подробное debug-логирование)."""
    
    # Пампы и дампы
    pd_interval_sec: int | None
    """Интервал для проверки пампов и дампов в секундах."""

    pd_min_change_pct: float | None
    """Процент изменения цены для пампов и дампов."""

    # Открытый интерес
    oi_interval_sec: int | None
    """Интервал для проверки открытого интереса в секундах."""

    oi_min_change_pct: float | None
    """Минимальное изменение открытого интереса в процентах."""

    oi_min_change_usd: float | None
    """Минимальное изменение открытого интереса в долларах."""

    # Ставка финансирования
    fr_min_value_pct: float | None
    """Минимальное значение ставки финансирования в процентах."""

    fr_max_value_pct: float | None
    """Максимальное значение ставки финансирования в процентах."""

    # Объем
    vl_interval_sec: int | None = Field(default=None, alias="vl_interval")
    """Интервал для проверки объема в секундах."""

    vl_min_multiplier: float | None
    """Минимальный множитель объема."""

    # Ликвидации
    lq_interval_sec: int | None
    """Интервал для проверки ликвидации в секундах."""

    lq_min_amount_usd: float | None
    """Минимальное количество ликвидаций в долларах."""

    lq_min_amount_pct: float | None
    """Минимальная сумма ликвидаций в процентах от суточного объема."""

    # Объем монеты за последние сутки
    dv_min_usd: float | None
    """Минимальный объем монеты за сутки в долларах."""

    dv_max_usd: float | None
    """Максимальный объем монеты за сутки в долларах."""

    # Изменение цены монеты за последние сутки.
    dp_min_pct: float | None
    """Минимальное изменение цены за сутки в процентах."""

    dp_max_pct: float | None
    """Максимальное изменение цены за сутки в процентах."""

    #Остальное
    max_day_alerts: int | None
    """Максимальное количество сигналов за сутки по одному тикеру."""

    timeout_sec: int
    """Таймаут между сигналами по одинаковой монете."""

    chat_id: int | None
    """ID чата для уведомлений; ``None`` — не слать в Telegram."""

    bot_token: str | None
    """Токен бота; ``None`` или пустая строка — не слать в Telegram."""

    text_template_type: TextTemplateType
    """Тип шаблона текста сигнала."""

    def parse_blacklist(self) -> set[str]:
        """Парсит черный список тикеров (Без USDT)."""
        if self.blacklist is None:
            return set()
        blacklist = self.blacklist.strip()
        if blacklist:
            return {symbol.strip().upper() for symbol in blacklist.split(",")}
        return set()

    def parse_whitelist(self) -> set[str]:
        """Парсит белый список тикеров (Без USDT)."""
        if self.whitelist is None:
            return set()
        whitelist = self.whitelist.strip()
        if whitelist:
            return {symbol.strip().upper() for symbol in whitelist.split(",")}
        return set()

    @property
    def pd_status(self) -> bool:
        """Статус фильтра по пампам и дампам."""
        return self.pd_interval_sec is not None and self.pd_min_change_pct is not None
    
    @property
    def oi_status(self) -> bool:
        """Статус фильтра по открытому интересу."""
        return self.oi_interval_sec is not None and (
            self.oi_min_change_pct is not None or self.oi_min_change_usd is not None
        )

    @property
    def fr_status(self) -> bool:
        """Статус фильтра по ставке финансирования."""
        return self.fr_min_value_pct is not None or self.fr_max_value_pct is not None

    @property
    def vl_status(self) -> bool:
        """Статус фильтра по аномальному объему."""
        return self.vl_interval_sec is not None and self.vl_min_multiplier is not None
        
    @property
    def lq_status(self) -> bool:
        """Статус фильтра по ликвидациям."""
        return self.lq_interval_sec is not None and (
            self.lq_min_amount_usd is not None or self.lq_min_amount_pct is not None
        )

    @property
    def dv_status(self) -> bool:
        """Статус фильтра по объему монеты за сутки."""
        return self.dv_min_usd is not None or self.dv_max_usd is not None

    @property
    def dp_status(self) -> bool:
        """Статус фильтра по изменению цены монеты за сутки."""
        return self.dp_min_pct is not None or self.dp_max_pct is not None

    @property
    def any_filters_status(self) -> bool:
        """Статус фильтра по любому фильтру."""
        return any(
            [
                self.pd_status,
                self.oi_status,
                self.fr_status,
                self.vl_status,
                self.lq_status,
                self.dv_status,
                self.dp_status,
            ]
        )