"""Статический модуль часового пояса UI админки."""

from __future__ import annotations

from pathlib import Path


def test_timezone_ui_js_exists_and_defines_api() -> None:
    """Файл подключается как /admin_api/ui/timezone.js и задаёт window.MpAdminTime."""
    root = Path(__file__).resolve().parents[1]
    path = root / "admin" / "timezone_ui.js"
    assert path.is_file(), path
    text = path.read_text(encoding="utf-8")
    assert "MpAdminTime" in text
    assert "mp_admin_timezone" in text
    assert "formatAxisLabel" in text
