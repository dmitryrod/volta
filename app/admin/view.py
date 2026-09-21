"""Пользовательские представления для админ-панели."""

__all__ = [
    "SettingsModelView",
    "DashboardCustomView",
    "MetrCustomView",
    "LogsViewerView",
    "AnalyticsCatalogView",
    "UiSettingsView",
]

import asyncio
import os
from typing import Any

from starlette.requests import Request
from starlette.responses import Response
from starlette.templating import Jinja2Templates
from starlette_admin import (
    BooleanField,
    CustomView,
    EnumField,
    FloatField,
    IntegerField,
    StringField,
)
from starlette_admin._types import RequestAction
from starlette_admin.contrib.sqla import ModelView
from starlette_admin.exceptions import FormValidationError
from unicex import Exchange, MarketType

from app.database import SettingsORM
from app.schemas import TextTemplateType
from app.config import logger, config
from .privacy_mask import mask_credential_display
from .roles import DEMO_SCREENER_NAME, is_demo_session
from app.admin.dashboard_summary import build_dashboard_summary
from app.admin.monitoring_metrics import get_template_context, record_snapshot

# Хвост файла: полный app.log за ночь может быть десятки МБ — чтение + Jinja splitlines() блокируют ответ.
_LOG_TAIL_MAX_BYTES = 512 * 1024

# Список / детали / JSON API: ``chat_id`` и ``bot_token`` маскируются для всех ролей;
# полные значения — только в формах CREATE/EDIT (см. ``serialize_field_value``).
_MASK_TELEGRAM_ACTIONS: frozenset[RequestAction] = frozenset(
    {RequestAction.API, RequestAction.LIST, RequestAction.DETAIL}
)


def _read_app_log_tail(log_path: str, max_bytes: int = _LOG_TAIL_MAX_BYTES) -> tuple[str, bool]:
    """Читает конец лог-файла. Возвращает (текст, обрезан ли начало файла)."""
    if not os.path.isfile(log_path):
        return "", False
    try:
        size = os.path.getsize(log_path)
    except OSError:
        return "", False
    if size <= max_bytes:
        try:
            with open(log_path, encoding="utf-8", errors="replace") as fh:
                return fh.read(), False
        except OSError:
            return "", False
    try:
        with open(log_path, "rb") as fh:
            fh.seek(max(0, size - max_bytes))
            chunk = fh.read()
    except OSError:
        return "", False
    text = chunk.decode("utf-8", errors="replace")
    first_nl = text.find("\n")
    if first_nl != -1:
        text = text[first_nl + 1 :]
    return text, True


class SettingsModelView(ModelView):
    """Настройки основного скринера и бизнес-логики сигналов."""

    identity = "screeners"
    name = "Скринер"

    create_template = "create_screener.html"
    edit_template = "edit_screener.html"
    exclude_fields_from_edit = ["market_type"]

    def _additional_css_links(self, request: Request, action: str) -> list[str]:
        """Убираем внешние шрифты (rsms.me/inter), чтобы не было ERR_CONNECTION_RESET."""
        links = super()._additional_css_links(request, action)
        if not links:
            return []
        return [url for url in links if "rsms.me" not in (str(url) or "")]

    def _additional_js_links(self, request: Request, action: str) -> list[str]:
        links = super()._additional_js_links(request, action) or []
        action_s = str(action).upper()
        if action_s == "LIST" or action_s.endswith(".LIST"):
            return [*links, "/admin_api/screeners/global-debug.js"]
        return links

    def can_create(self, request: Request) -> bool:
        return not is_demo_session(request)

    def can_edit(self, request: Request) -> bool:
        return not is_demo_session(request)

    def can_delete(self, request: Request) -> bool:
        return not is_demo_session(request)

    def get_list_query(self, request: Request):  # type: ignore[override]
        stmt = super().get_list_query(request)
        if is_demo_session(request):
            stmt = stmt.where(SettingsORM.name == DEMO_SCREENER_NAME)
        return stmt

    def get_count_query(self, request: Request):  # type: ignore[override]
        stmt = super().get_count_query(request)
        if is_demo_session(request):
            stmt = stmt.where(SettingsORM.name == DEMO_SCREENER_NAME)
        return stmt

    def get_details_query(self, request: Request):  # type: ignore[override]
        stmt = super().get_details_query(request)
        if is_demo_session(request):
            stmt = stmt.where(SettingsORM.name == DEMO_SCREENER_NAME)
        return stmt

    async def serialize_field_value(  # type: ignore[override]
        self,
        value: Any,
        field: Any,
        action: RequestAction,
        request: Request,
    ) -> Any:
        if field.name in ("chat_id", "bot_token") and action in _MASK_TELEGRAM_ACTIONS:
            if value is None:
                return await field.serialize_none_value(request, action)
            masked = mask_credential_display(value)
            if masked is None:
                return await field.serialize_none_value(request, action)
            return masked
        return await super().serialize_field_value(value, field, action, request)

    fields = [
        # Общие настройки
        StringField(
            "name",
            label="Название скринера",
            required=True,
            help_text="Краткое имя для отображения в списке (например: Bybit Futures).",
        ),
        BooleanField(
            "enabled",
            label="Включить скринер",
            # help_text="Снимите галочку, если нужно полностью остановить проверки и отправку сигналов."
        ),
        BooleanField(
            "debug",
            label="Отладка",
            help_text="Если включено, в текст сообщения будет добавлен отладочный блок.",
            required=False,
        ),
        EnumField(
            "exchange",
            label="Биржа для анализа",
            choices=[
                (Exchange.BINANCE.value, Exchange.BINANCE.capitalize()),
                (Exchange.BYBIT.value, Exchange.BYBIT.capitalize()),
                (Exchange.BITGET.value, Exchange.BITGET.capitalize()),
                (Exchange.ASTER.value, Exchange.ASTER.capitalize()),
                (Exchange.MEXC.value, Exchange.MEXC.capitalize()),
                (Exchange.OKX.value, Exchange.OKX.capitalize()),
                (Exchange.GATE.value, Exchange.GATE.capitalize()),
            ],
            required=True,
            # help_text="Выберите торговую площадку, с которой бот будет собирать и формировать сигналы."
        ),
        EnumField(
            "market_type",
            label="Тип рынка внутри выбранной биржи",
            choices=[
                (MarketType.SPOT.value, MarketType.SPOT.capitalize()),
                (MarketType.FUTURES.value, MarketType.FUTURES.capitalize()),
            ],
            required=True,
            help_text="Укажите, для какого сегмента биржи (Spot или Futures) нужно запускать проверки. ! Тип рынка нельзя изменить после создания скринера",
        ),
        StringField(
            "blacklist",
            label="Черный список тикеров",
            help_text="Перечислите тикеры через запятую без постфикса USDT: BTC,ETH,XRP. Эти монеты будут игнорироваться.",
        ),
        StringField(
            "whitelist",
            label="Белый список тикеров",
            help_text=(
                "Если заполнено - сканируем только эти тикеры.",
                "Перечислите тикеры через запятую без постфикса USDT: BTC,ETH,XRP..."
                "Оставьте поле пустым, чтобы анализировать весь рынок.",
            ),
        ),
        # Фильтр пампов и дампов
        IntegerField(
            "pd_interval_sec",
            label="Интервал для измерения роста монеты, сек",
            help_text="Временной интервал для измерения роста монеты в секундах.",
        ),
        FloatField(
            "pd_min_change_pct",
            label="Минимальный рост цены монеты, %",
            help_text="Процент роста, при котором сработает фильтр пампа/дампа.",
        ),
        # Фильтр открытого интереса
        IntegerField(
            "oi_interval_sec",
            label="Интервал для измерения роста открытого интереса, сек",
            help_text="Интервал для измерения роста открытого интереса в секундах.",
        ),
        FloatField(
            "oi_min_change_pct",
            label="Изменение открытого интереса, %",
            help_text="Положительное значение (например 2) — фильтр срабатывает только при росте OI на ≥ 2%. Отрицательное (например −2) — только при падении OI на ≥ 2%.",
        ),
        FloatField(
            "oi_min_change_usd",
            label="Изменение открытого интереса, $",
            help_text="Положительное значение — рост OI в $. Отрицательное — падение OI в $.",
        ),
        # Фильтр ставки финансирования
        FloatField(
            "fr_min_value_pct",
            label="Минимальная ставка финансирования, %",
            help_text="Нижний порог допустимой ставки финансирования.",
        ),
        FloatField(
            "fr_max_value_pct",
            label="Максимальная ставка финансирования, %",
            help_text="Верхний порог допустимой ставки финансирования.",
        ),
        # Фильтр множителя объема
        IntegerField(
            "vl_interval_sec",
            label="Интервал расчета множителя объема, сек",
            help_text="Сколько секунд учитывается при сравнении объема.",
        ),
        FloatField(
            "vl_min_multiplier",
            label="Минимальный множитель объема, Х",
            help_text="Во сколько раз объем должен вырасти относительно среднего объема за сутки. Например, 50 = рост в 50 раз.",
        ),
        # Фильтр ликвидаций
        IntegerField(
            "lq_interval_sec",
            label="Интервал расчета ликвидаций, сек",
            help_text="Промежуток времени, за который суммируем ликвидации.",
        ),
        FloatField(
            "lq_min_amount_usd",
            label="Минимальная сумма ликвидаций, $",
            help_text="Минимальная сумма ликвидаций в долларах, при которой фильтр будет пройден.",
        ),
        FloatField(
            "lq_min_amount_pct",
            label="Минимальная сумма ликвидаций, % от суточного объема",
            help_text=(
                "Минимальный процент суммы ликвидаций от суточного объема торгов.",
                "Если заданы и $, и %, оба условия должны выполняться.",
            ),
        ),
        # Фильтр объема монеты за сутки
        FloatField(
            "dv_min_usd",
            label="Минимальный суточный объем, $",
            help_text="Минимальный объем монеты в долларах, при котором фильтр будет пройден.",
        ),
        FloatField(
            "dv_max_usd",
            label="Максимальный суточный объем, $",
            help_text="Монета не пройдет фильтр, если объем монеты за сутки в долларах превышает это значение.",
        ),
        # Фильтр изменения цены монеты за сутки
        FloatField(
            "dp_min_pct",
            label="Минимальное изменение цены за сутки, %",
            help_text="Минимальное допустимое значение изменения цены за сутки в процентах.",
        ),
        FloatField(
            "dp_max_pct",
            label="Максимальное изменение цены за сутки, %",
            help_text="Ограничьте слишком волатильные монеты, указав верхнюю границу изменения цены в процентах.",
        ),
        # Настройка уведомлений
        IntegerField(
            "max_day_alerts",
            label="Максимум сигналов на тикер в сутки",
            required=True,
            help_text="Позволяет ограничить спам по одной монете. 0 означает без ограничений.",
        ),
        IntegerField(
            "timeout_sec",
            label="Таймаут между сигналами по тикеру, сек",
            required=False,
            help_text="Минимальное время между повторными уведомлениями по одной монете. Помогает избегать дублей.",
        ),
        IntegerField(
            "chat_id",
            label="ID Telegram чата для уведомлений",
            required=False,
            help_text=(
                "ID чата для уведомлений. Необязательно: без пары токен+чат скринер работает, "
                "сигналы пишутся в БД и лог без отправки в Telegram.",
                "Пустое поле + TELEGRAM_CHAT_ID в .env — подставится из .env.",
            ),
        ),
        StringField(
            "bot_token",
            label="Токен Telegram-бота, который будет отправлять уведомления",
            required=False,
            help_text=(
                "Токен бота (@BotFather). Необязательно: см. подсказку у поля «ID чата».",
                "Пустое поле + TELEGRAM_BOT_TOKEN в .env — подставится из .env.",
            ),
        ),
        EnumField(
            "text_template_type",
            label="Шаблон текста сигнала",
            choices=[
                (TextTemplateType.DEFAULT.value, "Обычный"),
                (TextTemplateType.TREE.value, "Древовидный"),
            ],
            required=True,
            help_text="Формат отображения данных в сообщении.",
        ),
    ]

    async def validate(self, request: Request, data: dict[str, Any]) -> None:
        errors = {}

        # Работа с логичаскими ошибками
        def ensure_min_before_max(min_key: str, max_key: str, message: str) -> None:
            min_value = data.get(min_key)
            max_value = data.get(max_key)
            if min_value is None or max_value is None:
                return
            if min_value > max_value:
                errors[min_key] = message
        
        ensure_min_before_max(
            "dv_min_usd",
            "dv_max_usd",
            "Минимальный суточный объем не может превышать максимальный.",
        )
        ensure_min_before_max(
            "dp_min_pct",
            "dp_max_pct",
            "Минимальное изменение цены за сутки не может быть больше максимального."
        )
        ensure_min_before_max(
            "fr_min_value_pct",
            "fr_max_value_pct",
            "Минимальная ставка финансирования должна быть ниже максимальной.",
        )

        timeout = data.get("timeout_sec")
        if timeout is not None and timeout < 0:
            errors["timeout_sec"] = "Таймаут между сигналами не может быть отрицательным."

        if data.get("max_day_alerts") is not None and data["max_day_alerts"] < 0:
            errors["max_day_alerts"] = "Количество сигналов в сутки не должно быть отрицательным"

        def ensure_positive(field: str, message: str) -> None:
            value = data.get(field)
            if value is None:
                return
            if value <= 0:
                errors[field] = message

        ensure_positive("pd_interval_sec", "Интервал для роста цены должен быть больше нуля.")
        ensure_positive(
            "oi_interval_sec", "Интервал анализа открытого интереса должен быть больше нуля."
        )
        ensure_positive(
            "vl_interval_sec","Интервал расчета множителя объема должен превышать ноль."
        )
        ensure_positive("vl_min_multiplier", "Множитель объема должен быть положительным.")
        ensure_positive("lq_interval_sec", "Интервал расчета ликвидаций должен быть больше нуля.")

        # Работа с дефолтными значениями
        if data.get("timeout_sec") is None:
            data["timeout_sec"] = 60
        if not (data.get("name") or "").strip():
            data["name"] = "Скринер"
        if not data.get("text_template_type"):
            data["text_template_type"] = TextTemplateType.DEFAULT.value

        # Нормализация и подстановка дефолтов Telegram из .env (отправка необязательна)
        raw_token = data.get("bot_token")
        if isinstance(raw_token, str):
            raw_token = raw_token.strip() or None
        data["bot_token"] = raw_token
        if data.get("chat_id") == "":
            data["chat_id"] = None

        env_tok = (config.telegram_bot_token or "").strip() or None
        if (not data.get("bot_token")) and env_tok:
            data["bot_token"] = env_tok
        if (data.get("chat_id") is None) and config.telegram_chat_id is not None:
            data["chat_id"] = config.telegram_chat_id

        def has_any_filters_selected() -> bool:
            """Проверяет, активирован ли хотя бы один фильтр."""
            # Пампы и дампы
            pumps_enabled = (
                data.get("pd_interval_sec") is not None
                and data.get("pd_min_change_pct") is not None
            )
        
            # Открытый интерес
            open_interest_enabled = data.get("oi_interval_sec") is not None and (
                data.get("oi_min_change_pct") is not None
                or data.get("oi_min_change_usd") is not None
            )

            # Ставка финансирования
            funding_rate_enabled = (
                data.get("fr_min_value_pct") is not None or data.get("fr_max_value_pct") is not None
            )

            # Множитель объема
            volume_multiplier_enabled = (
                data.get("vl_interval_sec") is not None
                and data.get("vl_min_multiplier") is not None
            )

            # Ликвидации
            liquidations_enabled = (
                data.get("lq_interval_sec") is not None
                and (
                    data.get("lq_min_amount_usd") is not None
                    or data.get("lq_min_amount_pct") is not None
                )
            )

            # Суточный объем и изменение цены
            daily_volume_enabled = (
                data.get("dv_min_usd") is not None or data.get("dv_max_usd") is not None
            )
            daily_price_change_enabled = (
                data.get("dp_min_pct") is not None or data.get("dp_max_pct") is not None
            )

            return any(
                [
                    pumps_enabled,
                    open_interest_enabled,
                    funding_rate_enabled,
                    volume_multiplier_enabled,
                    liquidations_enabled,
                    daily_volume_enabled,
                    daily_price_change_enabled,
                ]
            )

        # Не блокируем сохранение: скринер можно создать и потом добавить фильтры при редактировании.
        # if not has_any_filters_selected():
        #     errors["enabled"] = (
        #         "Нужно настроить хотя бы один фильтр, иначе скринер ничего не проверяет."
        #     )

        if errors:
            raise FormValidationError(errors)


class DashboardCustomView(CustomView):
    """Главная страница админки: сводка скринеров, сигналов, аналитики и метрик процесса."""

    def __init__(self) -> None:
        super().__init__(
            label="Обзор",
            icon="fa fa-home",
            path="/",
            name="dashboard_index",
            template_path="dashboard.html",
            add_to_menu=True,
        )

    async def render(self, request: Request, templates: Jinja2Templates) -> Response:
        summary = await build_dashboard_summary()
        return templates.TemplateResponse(
            request,
            "dashboard.html",
            {"request": request, "dashboard_initial": summary},
        )


class MetrCustomView(CustomView):
    """Показывает ключевые метрики сервера в админ-панели."""

    async def render(self, request: Request, templates: Jinja2Templates) -> Response:  # noqa: D401
        """Возвращает шаблон с загрузкой CPU, RAM, диска и времени аптайма."""
        await asyncio.to_thread(record_snapshot)
        context: dict[str, Any] = {
            "request": request,
            **get_template_context(),
        }
        return templates.TemplateResponse(request, "metr.html", context)


class LogsViewerView(CustomView):
    """Просмотр логов приложения в админке."""

    def is_accessible(self, request: Request) -> bool:
        if is_demo_session(request):
            return False
        return super().is_accessible(request)

    async def render(self, request: Request, templates: Jinja2Templates) -> Response:  # noqa: D401
        """Возвращает шаблон со списком логов."""
        logs_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs")
        log_file = os.path.join(logs_dir, "app.log")

        content, log_truncated = "", False
        if os.path.isfile(log_file):
            content, log_truncated = await asyncio.to_thread(_read_app_log_tail, log_file)

        context: dict[str, Any] = {
            "request": request,
            "log_content": content,
            "log_truncated": log_truncated,
        }

        return templates.TemplateResponse(request, "logs.html", context)


class SignalsView(CustomView):
    """Страница просмотра истории сигналов в реальном времени."""

    async def render(self, request: Request, templates: Jinja2Templates) -> Response:
        context: dict[str, Any] = {
            "request": request,
            "per_page_default": 100,
            "is_demo": is_demo_session(request),
        }
        return templates.TemplateResponse(request, "signals.html", context)


class AnalyticsCatalogView(CustomView):
    """Каталог сессий Аналитика."""

    identity = "analytics"
    name = "Аналитика"

    async def render(self, request: Request, templates: Jinja2Templates) -> Response:
        return templates.TemplateResponse(
            request,
            "analytics.html",
            {"request": request},
        )


class UiSettingsView(CustomView):
    """Настройки отображения времени в админке (IANA, только клиент)."""

    async def render(self, request: Request, templates: Jinja2Templates) -> Response:
        return templates.TemplateResponse(
            request,
            "ui_settings.html",
            {"request": request},
        )