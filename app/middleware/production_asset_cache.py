"""Заголовки кэширования для статики админки в production (Lighthouse / CDN-friendly)."""

from __future__ import annotations

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.config import config
from app.schemas import EnvironmentType


# Версия в пути (tabler.min-1.1.0) — при смене файла URL меняется; immutable безопасен.
_CACHE_STATIC = "public, max-age=31536000, immutable"
# UI-скрипт без хэша в имени — короткий SLA, чтобы обновления раздавались без смены URL.
_CACHE_TIMEZONE_UI = "public, max-age=86400"


def apply_production_asset_cache_headers(
    *, environment: EnvironmentType, path: str, headers: MutableHeaders
) -> None:
    """Выставляет Cache-Control для путей статики в ``EnvironmentType.PRODUCTION``.

    Args:
        environment: Режим приложения.
        path: ``request.url.path`` без query string.
        headers: Заголовки исходящего ответа (мутируются in-place).
    """
    if environment is not EnvironmentType.PRODUCTION:
        return
    if path.startswith("/admin/statics/"):
        headers.setdefault("cache-control", _CACHE_STATIC)
    elif path == "/admin_api/ui/timezone.js":
        headers.setdefault("cache-control", _CACHE_TIMEZONE_UI)


class ProductionAssetCacheMiddleware:
    """Добавляет долгий кэш для ``/admin/statics/*`` и сутки для ``timezone.js`` в проде.

    Реализован как ASGI middleware (не ``BaseHTTPMiddleware``), чтобы не ломать
    SSE/``StreamingResponse`` (``text/event-stream``) — см. RuntimeError «No response returned».
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path") or ""

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                mh = MutableHeaders(raw=message["headers"])
                apply_production_asset_cache_headers(
                    environment=config.environment,
                    path=path,
                    headers=mh,
                )
                message["headers"] = mh.raw
            await send(message)

        await self.app(scope, receive, send_wrapper)
