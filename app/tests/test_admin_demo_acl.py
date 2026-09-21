"""Демо-роль админки: сопоставление логина и ограничения API."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from starlette.exceptions import HTTPException

from app.admin.auth import match_admin_or_demo
from app.admin.roles import (
    DEMO_SCANNER_RUNTIME_RESPONSE,
    ROLE_ADMIN,
    ROLE_DEMO,
    SESSION_ROLE_KEY,
    ensure_full_admin,
    is_demo_session,
)


def test_match_admin_credentials() -> None:
    r = match_admin_or_demo(
        "root",
        "secret",
        admin_login="root",
        admin_password="secret",
        demo_enabled=True,
        demo_login="demo",
        demo_password="demo",
    )
    assert r == ROLE_ADMIN


def test_match_demo_when_enabled() -> None:
    r = match_admin_or_demo(
        "demo",
        "demo",
        admin_login="root",
        admin_password="secret",
        demo_enabled=True,
        demo_login="demo",
        demo_password="demo",
    )
    assert r == ROLE_DEMO


def test_demo_ignored_when_flag_off() -> None:
    assert (
        match_admin_or_demo(
            "demo",
            "demo",
            admin_login="root",
            admin_password="secret",
            demo_enabled=False,
            demo_login="demo",
            demo_password="demo",
        )
        is None
    )


def test_wrong_password_none() -> None:
    assert (
        match_admin_or_demo(
            "root",
            "wrong",
            admin_login="root",
            admin_password="secret",
            demo_enabled=True,
            demo_login="demo",
            demo_password="demo",
        )
        is None
    )


def _request_with_session(session_dict: dict) -> MagicMock:
    req = MagicMock()
    req.session = session_dict
    return req


def test_is_demo_session_true() -> None:
    req = _request_with_session({SESSION_ROLE_KEY: ROLE_DEMO, "username": "x"})
    assert is_demo_session(req) is True


def test_is_demo_session_false_for_admin() -> None:
    req = _request_with_session({SESSION_ROLE_KEY: ROLE_ADMIN, "username": "x"})
    assert is_demo_session(req) is False


def test_ensure_full_admin_raises_for_demo() -> None:
    req = _request_with_session({SESSION_ROLE_KEY: ROLE_DEMO})
    with pytest.raises(HTTPException) as ei:
        ensure_full_admin(req)
    assert ei.value.status_code == 403


def test_ensure_full_admin_raises_401_without_role() -> None:
    req = _request_with_session({})
    with pytest.raises(HTTPException) as ei:
        ensure_full_admin(req)
    assert ei.value.status_code == 401


def test_ensure_full_admin_raises_401_username_without_role() -> None:
    req = _request_with_session({"username": "guest"})
    with pytest.raises(HTTPException) as ei:
        ensure_full_admin(req)
    assert ei.value.status_code == 401


def test_ensure_full_admin_allows_admin() -> None:
    req = _request_with_session({SESSION_ROLE_KEY: ROLE_ADMIN, "username": "root"})
    ensure_full_admin(req)


def test_demo_runtime_contract() -> None:
    assert DEMO_SCANNER_RUNTIME_RESPONSE["max_cards"] == 10
    assert DEMO_SCANNER_RUNTIME_RESPONSE["posttracking_minutes"] == 10
    assert DEMO_SCANNER_RUNTIME_RESPONSE["cooldown_hours"] == 24
    assert DEMO_SCANNER_RUNTIME_RESPONSE["statistics_enabled"] is True


def test_concurrent_demo_logical_separate_session_dicts() -> None:
    """Два «клиента» с одним и тем же именем demo — независимые объекты сессии."""
    a: dict = {SESSION_ROLE_KEY: ROLE_DEMO, "username": "DEMO"}
    b: dict = {SESSION_ROLE_KEY: ROLE_DEMO, "username": "DEMO"}
    a["username"] = "x"
    assert b["username"] == "DEMO"
    assert a[SESSION_ROLE_KEY] == ROLE_DEMO
