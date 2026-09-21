"""FastAPI application entry point."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from app_options.api import (
    auth_router,
    candles_router,
    meta_router,
    options_router,
    polymarket_router,
)
from app_options.auth import AuthMiddleware
from app_options.config import config, setup_logging
from app_options.ingestor import IngestorOperator

BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "frontend" / "static"
TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

_operator: IngestorOperator | None = None
_operator_task: asyncio.Task | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _operator, _operator_task
    setup_logging(config.log_level)
    _operator = IngestorOperator()
    _operator_task = asyncio.create_task(_operator.start())
    yield
    if _operator:
        await _operator.stop()
    if _operator_task:
        _operator_task.cancel()
        try:
            await _operator_task
        except asyncio.CancelledError:
            pass


app = FastAPI(title="Volta", version="0.1.0", lifespan=lifespan)

# AuthMiddleware must be inner; SessionMiddleware outer (added last).
app.add_middleware(AuthMiddleware)
app.add_middleware(
    SessionMiddleware,
    secret_key=config.panel.cypher_key,
    session_cookie="app_options_session",
    max_age=86400 * 7,
    same_site="lax",
    https_only=False,
)

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

app.include_router(auth_router)
app.include_router(candles_router)
app.include_router(meta_router)
app.include_router(options_router)
app.include_router(polymarket_router)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "environment": config.environment}


@app.get("/")
async def root() -> RedirectResponse:
    return RedirectResponse(url="/chart", status_code=303)
