"""Auth middleware protecting panel and API routes."""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse, Response
from starlette.status import HTTP_401_UNAUTHORIZED

from volta.auth.session import is_authenticated_session

PUBLIC_PATHS = frozenset({"/health", "/login"})
PUBLIC_PREFIXES = ("/static/",)


class AuthMiddleware(BaseHTTPMiddleware):
    """Require session auth for /chart and /api/* except /health."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        path = request.url.path

        if path in PUBLIC_PATHS:
            return await call_next(request)

        for prefix in PUBLIC_PREFIXES:
            if path.startswith(prefix):
                return await call_next(request)

        if path == "/" or path.startswith("/chart") or path.startswith("/api/"):
            if not is_authenticated_session(request.session):
                if path.startswith("/api/"):
                    return JSONResponse(
                        {"detail": "Unauthorized"},
                        status_code=HTTP_401_UNAUTHORIZED,
                    )
                return RedirectResponse(url="/login", status_code=303)

        return await call_next(request)
