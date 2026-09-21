"""Заголовки кэша статики админки (production)."""

from __future__ import annotations

from starlette.responses import PlainTextResponse

from app.middleware.production_asset_cache import apply_production_asset_cache_headers
from app.schemas import EnvironmentType


def test_prod_cache_sets_long_statics() -> None:
    resp = PlainTextResponse("ok")
    apply_production_asset_cache_headers(
        environment=EnvironmentType.PRODUCTION,
        path="/admin/statics/css/tabler.min-1.1.0.css",
        headers=resp.headers,
    )
    assert resp.headers["cache-control"].startswith("public")
    assert "max-age=31536000" in resp.headers["cache-control"]


def test_prod_cache_sets_timezone_js() -> None:
    resp = PlainTextResponse("ok")
    apply_production_asset_cache_headers(
        environment=EnvironmentType.PRODUCTION,
        path="/admin_api/ui/timezone.js",
        headers=resp.headers,
    )
    cc = resp.headers["cache-control"]
    assert "max-age=86400" in cc


def test_dev_skips_headers() -> None:
    resp = PlainTextResponse("ok")
    apply_production_asset_cache_headers(
        environment=EnvironmentType.DEVELOPMENT,
        path="/admin/statics/js/vendor/jquery.min.js",
        headers=resp.headers,
    )
    assert "cache-control" not in resp.headers
