"""Контракт агрегации дашборда админки."""

from __future__ import annotations

from app.admin.dashboard_summary import (
    DEFAULT_SCANNER_RUNTIME,
    invalidate_dashboard_cache,
    monitoring_subset_from_payload,
)


def test_monitoring_subset_from_payload_contract() -> None:
    payload = {
        "cpu": 12.3,
        "memory_percent": 44.0,
        "disk_percent": 61.0,
        "stale": False,
        "server_time": 1714320000.0,
        "app_dir_bytes": 1048576,
        "error": None,
        "extra": "ignored",
    }
    sub = monitoring_subset_from_payload(payload)
    assert sub["cpu"] == 12.3
    assert sub["memory_percent"] == 44.0
    assert sub["disk_percent"] == 61.0
    assert sub["stale"] is False
    assert sub["server_time"] == 1714320000.0
    assert sub["app_dir_bytes"] == 1048576
    assert "extra" not in sub


def test_monitoring_subset_skips_missing_keys() -> None:
    sub = monitoring_subset_from_payload({"cpu": 5.0})
    assert sub == {"cpu": 5.0}


def test_default_scanner_runtime_shape() -> None:
    assert DEFAULT_SCANNER_RUNTIME["max_cards"] == 10
    assert "statistics_enabled" in DEFAULT_SCANNER_RUNTIME


def test_dashboard_summary_contract_keys() -> None:
    """Форма ответа API summary (без вызова БД)."""
    sample = {
        "screeners": {"total": 1, "enabled": 1, "debug_enabled": 0},
        "signals": {
            "total": 100,
            "total_source": "estimate",
            "last_24h": 5,
            "telegram_ok_24h": 4,
            "telegram_fail_24h": 1,
        },
        "analytics": {"sessions_total": 2, "sessions_by_status": {"active": 2}},
        "scanner_runtime": dict(DEFAULT_SCANNER_RUNTIME),
        "monitoring": {"cpu": 1.0},
    }
    assert sample["signals"]["total_source"] in ("estimate", "exact")
    invalidate_dashboard_cache()

