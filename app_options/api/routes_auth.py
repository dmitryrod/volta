"""Auth routes: login/logout."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from app_options.auth.session import (
    SESSION_AUTH_KEY,
    SESSION_USERNAME_KEY,
    is_authenticated_session,
    verify_credentials,
)

router = APIRouter(tags=["auth"])


def get_templates() -> Jinja2Templates:
    from app_options.__main__ import templates
    return templates


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request) -> HTMLResponse:
    if is_authenticated_session(request.session):
        return RedirectResponse(url="/chart", status_code=303)
    return get_templates().TemplateResponse(
        request,
        "login.html",
        {"error": None},
    )


@router.post("/login", response_model=None)
async def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
) -> Response:
    if not verify_credentials(username, password):
        await asyncio.sleep(0.75)
        return get_templates().TemplateResponse(
            request,
            "login.html",
            {"error": "Invalid login or password"},
            status_code=401,
        )
    request.session.clear()
    request.session[SESSION_AUTH_KEY] = True
    request.session[SESSION_USERNAME_KEY] = username.strip()
    return RedirectResponse(url="/chart", status_code=303)


@router.post("/logout")
async def logout(request: Request) -> RedirectResponse:
    request.session.clear()
    return RedirectResponse(url="/login", status_code=303)
