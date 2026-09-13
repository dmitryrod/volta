"""API routes package."""

from app_options.api.routes_auth import router as auth_router
from app_options.api.routes_candles import router as candles_router
from app_options.api.routes_meta import router as meta_router
from app_options.api.routes_options import router as options_router
from app_options.api.routes_polymarket import router as polymarket_router

__all__ = [
    "auth_router",
    "candles_router",
    "meta_router",
    "options_router",
    "polymarket_router",
]
