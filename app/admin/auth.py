from __future__ import annotations

import asyncio
import hashlib
import secrets
from typing import Literal

from starlette.requests import Request
from starlette.responses import RedirectResponse, Response
from starlette.status import HTTP_303_SEE_OTHER
from starlette_admin.auth import AdminConfig, AdminUser, AuthProvider
from starlette_admin.exceptions import LoginFailed

from app.admin.roles import ROLE_ADMIN, ROLE_DEMO, SESSION_ROLE_KEY
from app.config import config


def _digest_eq(a: str, b: str) -> bool:
    """Сравнение строк без утечки длины через SHA-256 + compare_digest."""
    da = hashlib.sha256(a.encode("utf-8")).digest()
    db = hashlib.sha256(b.encode("utf-8")).digest()
    return secrets.compare_digest(da, db)


def match_admin_or_demo(
    username: str | None,
    password: str | None,
    *,
    admin_login: str,
    admin_password: str,
    demo_enabled: bool,
    demo_login: str,
    demo_password: str,
) -> Literal["admin", "demo"] | None:
    """Возвращает роль при успешной паре логин/пароль, иначе None."""
    u = (username or "").strip()
    p = password or ""
    if not u:
        return None
    if _digest_eq(u, admin_login) and _digest_eq(p, admin_password):
        return ROLE_ADMIN
    if (
        demo_enabled
        and demo_login
        and demo_password
        and _digest_eq(u, demo_login)
        and _digest_eq(p, demo_password)
    ):
        return ROLE_DEMO
    return None


class AdminAuthProvider(AuthProvider):
    """Логин/пароль из env: полный admin и опционально demo.

    Роль и имя пишутся в ``request.session`` (см. ``SessionMiddleware``): сессия —
    подписанная cookie у клиента, без общего серверного состояния по ``username``.
    """

    async def login(  # type: ignore[override]
        self,
        username: str | None,
        password: str | None,
        remember_me: bool,
        request: Request,
        response: Response,
    ) -> Response:
        role = match_admin_or_demo(
            username,
            password,
            admin_login=config.admin.login,
            admin_password=config.admin.password,
            demo_enabled=config.demo.enabled,
            demo_login=config.demo.login,
            demo_password=config.demo.password,
        )
        if role is None:
            await asyncio.sleep(0.75)
            raise LoginFailed("Неверный логин или пароль")
        request.session.clear()
        uname = (username or "").strip()
        if not uname:
            uname = config.demo.login if role == ROLE_DEMO else config.admin.login
        request.session["username"] = uname
        request.session[SESSION_ROLE_KEY] = role
        return response

    async def is_authenticated(self, request: Request) -> bool:  # type: ignore[override]
        role = request.session.get(SESSION_ROLE_KEY)
        user = request.session.get("username")
        if not role or not user:
            return False
        request.state.user = user
        request.state.admin_role = role
        return True

    def get_admin_config(self, request: Request) -> AdminConfig:  # type: ignore[override]
        return AdminConfig(app_title=config.admin.title, logo_url=config.admin.logo_url)

    def get_admin_user(self, request: Request) -> AdminUser:  # type: ignore[override]
        username = getattr(request.state, "user", None) or request.session.get(
            "username", ""
        )
        return AdminUser(username=str(username))

    async def logout(self, request: Request, response: Response) -> Response:  # type: ignore[override]
        request.session.clear()
        return RedirectResponse(url="/admin/login", status_code=HTTP_303_SEE_OTHER)
