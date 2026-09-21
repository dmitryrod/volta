from __future__ import annotations

from dataclasses import dataclass
import logging
import os
import uuid
from os import getenv

from app.schemas import EnvironmentType

_log = logging.getLogger(__name__)


def parse_optional_telegram_chat_id(raw: str | None) -> int | None:
    """Разбор ``TELEGRAM_CHAT_ID`` из env: пусто / мусор / ``#…`` → ``None`` без падения процесса.

    Некорректное значение логируется как WARNING; приложение стартует, доставка в Telegram
    отключается до появления валидной пары токен + chat (см. ``consumer._telegram_delivery_configured``).

    Args:
        raw: Сырое значение из окружения или ``None``.

    Returns:
        Целый chat id или ``None``, если задать нельзя.
    """
    if raw is None:
        return None
    s = raw.strip()
    if not s:
        return None
    if s.startswith("#"):
        _log.warning(
            "TELEGRAM_CHAT_ID starts with '#'; treating as unset. "
            "Use a plain integer (no shell-style comment prefix in the value)."
        )
        return None
    try:
        return int(s)
    except ValueError:
        _log.warning(
            "TELEGRAM_CHAT_ID is not a valid integer (%r); treating as unset.",
            raw,
        )
        return None


def parse_optional_telegram_bot_token(raw: str | None) -> str | None:
    """Разбор ``TELEGRAM_BOT_TOKEN`` из env: пусто / только пробелы / префикс ``#`` → ``None``.

    Некорректный префикс логируется как WARNING (см. комментарии в ``parse_optional_telegram_chat_id``).

    Args:
        raw: Сырое значение из окружения или ``None``.

    Returns:
        Токен без лишних пробелов или ``None``.
    """
    if raw is None:
        return None
    s = raw.strip()
    if not s:
        return None
    if s.startswith("#"):
        _log.warning(
            "TELEGRAM_BOT_TOKEN starts with '#'; treating as unset. "
            "Do not prefix the token with '#' in .env."
        )
        return None
    return s


@dataclass(frozen=True)
class _DatabaseConfig:
    """Настройки подключения к базе данных."""

    user: str = getenv("POSTGRES_USER", "postgres")
    password: str = getenv("POSTGRES_PASSWORD", "postgres")
    host: str = getenv("POSTGRES_HOST", "postgres")
    port: int = int(getenv("POSTGRES_PORT", "5432"))
    name: str = getenv("POSTGRES_DB", "screener_db")

    def build_connection_str(self) -> str:
        return (
            f"postgresql+asyncpg://{self.user}:{self.password}"
            f"@{self.host}:{self.port}/{self.name}"
        )


@dataclass(frozen=True)
class _AdminConfig:
    """Настройки админ-панели."""

    title: str = "Money Pulso"
    logo_url: str = (
        "https://images.icon-icons.com/3256/PNG/512/admin_lock_padlock_icon_205893.png"
    )
    login: str = getenv("ADMIN_LOGIN", "admin")
    password: str = getenv("ADMIN_PASSWORD", "admin")


def _env_truthy(name: str, default: str = "0") -> bool:
    return getenv(name, default).strip().lower() in ("1", "true", "yes")


@dataclass(frozen=True)
class _DemoConfig:
    """Публичный демо-вход (отдельная роль ``demo``). Включается только из env."""

    enabled: bool = _env_truthy("ADMIN_DEMO_ENABLED", "0")
    login: str = getenv("DEMO_LOGIN", "")
    password: str = getenv("DEMO_PASSWORD", "")


@dataclass(frozen=True)
class Configuration:
    """Единая точка доступа к настройкам приложения."""

    db: _DatabaseConfig = _DatabaseConfig()
    admin: _AdminConfig = _AdminConfig()
    demo: _DemoConfig = _DemoConfig()

    try:
        environment: EnvironmentType = EnvironmentType(
            os.getenv("ENVIRONMENT", "development")
        )
    except ValueError as err:
        raise ValueError(f"Invalid environment: {os.getenv('ENVIRONMENT')}") from err

    cypher_key: str = getenv(
        "CYPHER_KEY", uuid.UUID(int=uuid.getnode()).hex[-12:]
    )

    # Дефолты для Telegram, если не заданы в настройках скринера (опционально; битый env не валит импорт)
    telegram_bot_token: str | None = parse_optional_telegram_bot_token(
        getenv("TELEGRAM_BOT_TOKEN")
    )
    telegram_chat_id: int | None = parse_optional_telegram_chat_id(
        getenv("TELEGRAM_CHAT_ID")
    )


config: Configuration = Configuration()
