"""Точка входа FastAPI-приложения."""

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import Response
from sqlalchemy import text
from starlette.middleware.gzip import GZipMiddleware
from starlette.middleware.sessions import SessionMiddleware
from starlette.responses import RedirectResponse

from app.middleware import ProductionAssetCacheMiddleware
from unicex import start_exchanges_info

from .admin import register_admin_routes
from .config import config, logger, log_signals_event
from .database import Base, Database
from .schemas import EnvironmentType
from .screener import Operator
from .utils import start_support_task
from .utils.connectivity import is_transient_network_error, wait_for_internet


def _add_lq_min_amount_pct_if_missing(sync_conn):
    """Добавляет колонку lq_min_amount_pct в settings, если её нет (миграция без Alembic)."""
    sync_conn.execute(text("ALTER TABLE settings ADD COLUMN IF NOT EXISTS lq_min_amount_pct DOUBLE PRECISION"))


def _ensure_scanner_analytics_schema(sync_conn):
    """Колонки signals и индексы для Scanner snapshot / tracking_id."""
    sync_conn.execute(
        text("ALTER TABLE signals ADD COLUMN IF NOT EXISTS tracking_id VARCHAR(64)")
    )
    sync_conn.execute(
        text("ALTER TABLE signals ADD COLUMN IF NOT EXISTS card_snapshot_json TEXT")
    )
    sync_conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_signals_tracking_id ON signals (tracking_id)"
        )
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Управление жизненным циклом приложения."""
    # Launch logs
    logger.info (f"Admin panel startup! Environment: {config.environment}")

    # Создаём таблицы, если их ещё нет (для чистого БД / Docker без миграций)
    while True:
        try:
            async with Database.engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
                await conn.run_sync(_add_lq_min_amount_pct_if_missing)
                await conn.run_sync(_ensure_scanner_analytics_schema)
            break
        except Exception as exc:
            logger.exception("Database init failed: {}", exc)
            if is_transient_network_error(exc):
                await wait_for_internet(logger=logger, log_name="database_init")
            else:
                raise
    if config.environment == EnvironmentType.DEVELOPMENT:
        logger.debug("Admin panel url: http://127.0.0.1:8000/admin")

    # Start exchanges info (унифицированные метаданные бирж; при обрыве сети — ждём)
    while True:
        try:
            await start_exchanges_info()
            break
        except Exception as exc:
            logger.exception("start_exchanges_info failed: {}", exc)
            if is_transient_network_error(exc):
                await wait_for_internet(logger=logger, log_name="unicex_exchanges_info")
            else:
                raise

    # CoinMarketCap rank cache (HTTP + фон; без ключа только warning в утилите)
    try:
        from .utils.coinmarketcap_rank import init_cmc_rank_cache

        init_cmc_rank_cache()
    except Exception as exc:
        logger.exception("CoinMarketCap rank cache init failed: {}", exc)

    # Register admin routes
    register_admin_routes(app)

    # Create and start screener operator
    operator = Operator()
    asyncio.create_task(operator.start())

    # Start supporting task (фон, можно не ждать)
    support_task = start_support_task()

    # Give control to FastAPI
    yield

    # Stop screener operator
    await operator.stop()

    # Shutdown logs
    log_signals_event({"kind": "lifecycle", "action": "application_shutdown"})
    logger.info ("Admin panel shutdown!")


# Main FastAPI object
app = FastAPI(
    lifespan=lifespan,
    **{
        "docs_url": None,
        "redoc_url": None,
        "openapi_url": None,
    }
    if config.environment == EnvironmentType.PRODUCTION
    else {}, # type: ignore
)
# Одна сессия для `/admin` и `/admin_api` (роль demo / ACL на API).
app.add_middleware(SessionMiddleware, secret_key=config.cypher_key)
app.add_middleware(GZipMiddleware, minimum_size=512)
app.add_middleware(ProductionAssetCacheMiddleware)

@app.get("/")
def root_redirect() -> RedirectResponse:
    return RedirectResponse(url="/admin/screeners/list", status_code=302)

@app.get("/.well-known/appspecific/com.chrome.devtools.json")
def _chrome_devtools_well_known() -> Response:
    """Chrome DevTools запрашивает этот URL; отдаём 204, чтобы не светить 404 в логах."""
    return Response(status_code=204)