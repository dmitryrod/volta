"""Фильтр списка скринеров для demo и маскирование Telegram-полей в админке."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from sqlalchemy.dialects import sqlite
from starlette_admin._types import RequestAction
from starlette_admin.fields import IntegerField, StringField

from app.admin.privacy_mask import mask_credential_display
from app.admin.roles import DEMO_SCREENER_NAME, ROLE_ADMIN, ROLE_DEMO, SESSION_ROLE_KEY
from app.admin.view import SettingsModelView
from app.database import SettingsORM


def _demo_request() -> MagicMock:
    req = MagicMock()
    req.session = {SESSION_ROLE_KEY: ROLE_DEMO, "username": "demo"}
    return req


def _admin_request() -> MagicMock:
    req = MagicMock()
    req.session = {SESSION_ROLE_KEY: ROLE_ADMIN, "username": "root"}
    return req


def _sql_str(stmt: object) -> str:
    return str(
        stmt.compile(
            dialect=sqlite.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )


@pytest.mark.parametrize(
    ("raw", "expected_substr"),
    [
        (None, None),
        ("", ""),
        ("ab", "****"),
        ("abc", "a****c"),
        ("1234567890123456789", "1234****6789"),
        (-9876543210123456, "-987****3456"),
    ],
)
def test_mask_credential_display(raw: object, expected_substr: str | None) -> None:
    out = mask_credential_display(raw)  # type: ignore[arg-type]
    if expected_substr is None:
        assert out is None
    else:
        assert out == expected_substr


def test_demo_list_query_filters_by_name() -> None:
    view = SettingsModelView(model=SettingsORM)
    stmt = view.get_list_query(_demo_request())
    sql = _sql_str(stmt)
    assert DEMO_SCREENER_NAME in sql
    assert "name" in sql.lower()


def test_demo_count_query_filters_by_name() -> None:
    view = SettingsModelView(model=SettingsORM)
    stmt = view.get_count_query(_demo_request())
    sql = _sql_str(stmt)
    assert DEMO_SCREENER_NAME in sql


def test_demo_details_query_filters_by_name() -> None:
    view = SettingsModelView(model=SettingsORM)
    stmt = view.get_details_query(_demo_request())
    sql = _sql_str(stmt)
    assert DEMO_SCREENER_NAME in sql


def test_admin_list_query_no_demo_filter() -> None:
    view = SettingsModelView(model=SettingsORM)
    stmt = view.get_list_query(_admin_request())
    sql = _sql_str(stmt)
    # Нет жёсткой привязки к имени demo для полного админа
    assert sql.count(DEMO_SCREENER_NAME) == 0


@pytest.mark.asyncio
async def test_serialize_masks_chat_id_for_api() -> None:
    view = SettingsModelView(model=SettingsORM)
    field = IntegerField("chat_id", label="id")
    req = _admin_request()
    out = await view.serialize_field_value(-1001234567890, field, RequestAction.API, req)
    assert isinstance(out, str)
    assert "****" in out
    assert out.startswith("-100")


@pytest.mark.asyncio
async def test_serialize_masks_bot_token_for_list() -> None:
    view = SettingsModelView(model=SettingsORM)
    field = StringField("bot_token", label="t")
    req = _admin_request()
    tok = "1234567890:AAHxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
    out = await view.serialize_field_value(tok, field, RequestAction.LIST, req)
    assert out.startswith("1234")
    assert "****" in out
    assert out.endswith("xxxx")


@pytest.mark.asyncio
async def test_serialize_edit_leaves_bot_token_to_super() -> None:
    view = SettingsModelView(model=SettingsORM)
    field = StringField("bot_token", label="t")
    req = _admin_request()
    tok = "full_secret_token_value"
    out = await view.serialize_field_value(tok, field, RequestAction.EDIT, req)
    assert out == tok
