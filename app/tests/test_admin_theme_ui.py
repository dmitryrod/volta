"""Регрессия: переключатель темы и сохранение в localStorage (разметка + ключ)."""

from pathlib import Path


def test_base_html_has_theme_bootstrap_and_storage_key() -> None:
    """Ранний скрипт и токены не должны исчезнуть из base.html."""
    root = Path(__file__).resolve().parents[1]
    text = (root / "admin" / "templates" / "base.html").read_text(encoding="utf-8")
    assert "mp_admin_color_scheme" in text
    assert 'setAttribute("data-bs-theme"' in text
    assert '[data-bs-theme="light"]' in text
    assert "--mp-c-surface" in text or "--mp-shell-bg" in text


def test_layout_has_theme_switch() -> None:
    root = Path(__file__).resolve().parents[1]
    text = (root / "admin" / "templates" / "layout.html").read_text(encoding="utf-8")
    assert "mp-admin-theme-switch" in text
    assert "mp-admin-topbar" in text
    assert "mp-admin-theme-change" in text
