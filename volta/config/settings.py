"""Application configuration from environment."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache

from loguru import logger


def _env(key: str, default: str = "") -> str:
    return (os.getenv(key) or default).strip()


@dataclass(frozen=True)
class DatabaseConfig:
    url: str
    host: str
    port: int
    user: str
    password: str
    name: str


@dataclass(frozen=True)
class PanelAuthConfig:
    login: str
    password: str
    cypher_key: str


@dataclass(frozen=True)
class IngestorConfig:
    interval_sec: int
    tracked_bases: tuple[str, ...]
    exchange: str


@dataclass(frozen=True)
class PolymarketConfig:
    retention_hours_after_expiry: int
    max_events_per_base: int


@dataclass(frozen=True)
class AppConfig:
    environment: str
    log_level: str
    db: DatabaseConfig
    panel: PanelAuthConfig
    ingestor: IngestorConfig
    polymarket: PolymarketConfig
    static_dir: str = "frontend/static"
    templates_dir: str = "volta/templates"


@lru_cache(maxsize=1)
def get_config() -> AppConfig:
    """Load config from environment (cached)."""
    db_url = _env("DATABASE_URL")
    if not db_url:
        user = _env("POSTGRES_USER", "user")
        password = _env("POSTGRES_PASSWORD", "password")
        host = _env("POSTGRES_HOST", "localhost")
        port = int(_env("POSTGRES_PORT", "5432"))
        name = _env("POSTGRES_DB", "options_data")
        db_url = f"postgresql+asyncpg://{user}:{password}@{host}:{port}/{name}"
    else:
        user = _env("POSTGRES_USER", "user")
        password = _env("POSTGRES_PASSWORD", "password")
        host = _env("POSTGRES_HOST", "localhost")
        port = int(_env("POSTGRES_PORT", "5432"))
        name = _env("POSTGRES_DB", "options_data")

    bases_raw = _env("TRACKED_BASES", "BTC,ETH,SOL")
    bases = tuple(b.strip().upper() for b in bases_raw.split(",") if b.strip())

    return AppConfig(
        environment=_env("ENVIRONMENT", "development"),
        log_level=_env("LOG_LEVEL", "INFO"),
        db=DatabaseConfig(
            url=db_url,
            host=host,
            port=port,
            user=user,
            password=password,
            name=name,
        ),
        panel=PanelAuthConfig(
            login=_env("PANEL_LOGIN", "admin"),
            password=_env("PANEL_PASSWORD", "changeme"),
            cypher_key=_env("CYPHER_KEY", "dev-insecure-cypher-key-change-me"),
        ),
        ingestor=IngestorConfig(
            interval_sec=max(30, int(_env("SNAPSHOT_INTERVAL_SEC", "300"))),
            tracked_bases=bases,
            exchange=_env("TRACKED_EXCHANGE", "bybit").lower(),
        ),
        polymarket=PolymarketConfig(
            retention_hours_after_expiry=max(
                0, int(_env("PM_RETENTION_HOURS_AFTER_EXPIRY", "24"))
            ),
            max_events_per_base=max(1, int(_env("PM_MAX_EVENTS_PER_BASE", "10"))),
        ),
    )


def setup_logging(level: str = "INFO") -> None:
    """Configure loguru."""
    logger.remove()
    logger.add(
        sink=lambda msg: print(msg, end=""),
        level=level.upper(),
        format="{time:YYYY-MM-DD HH:mm:ss} | {level:<8} | {name}:{function}:{line} - {message}",
    )


config = get_config()
