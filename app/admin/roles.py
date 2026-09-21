"""Роли сессии админки (полный доступ vs demo) и проверки ACL для API."""

from __future__ import annotations

from typing import Any, Final, Literal

from starlette.exceptions import HTTPException
from starlette.requests import Request

SESSION_ROLE_KEY: Final[str] = "mp_admin_role"
ROLE_ADMIN: Final[Literal["admin"]] = "admin"
ROLE_DEMO: Final[Literal["demo"]] = "demo"

# Единственная запись скринеров, видимая в админке при сессии demo (список / детали).
DEMO_SCREENER_NAME: Final[str] = "demo"

# Отображаемые и отдаваемые GET /admin_api/scanner/runtime-settings в demo (без записи в БД).
DEMO_SCANNER_RUNTIME_RESPONSE: Final[dict[str, Any]] = {
    "max_cards": 10,
    "posttracking_minutes": 10,
    "cooldown_hours": 24,
    "statistics_enabled": True,
}


def get_session_role(request: Request) -> str | None:
    """Возвращает ``admin`` / ``demo`` или None, если сессия без роли."""
    return request.session.get(SESSION_ROLE_KEY)


def is_demo_session(request: Request) -> bool:
    """True, если пользователь вошёл как demo."""
    return get_session_role(request) == ROLE_DEMO


def ensure_full_admin(request: Request) -> None:
    """Разрешает только полную роль admin: без сессии / не admin — 401, demo — 403."""
    role = get_session_role(request)
    if role == ROLE_DEMO:
        raise HTTPException(status_code=403, detail="Недоступно в демо-режиме")
    if role != ROLE_ADMIN:
        raise HTTPException(
            status_code=401, detail="Требуется полный доступ администратора"
        )
