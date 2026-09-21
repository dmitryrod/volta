"""Unit-тесты in-memory метрик страницы «Система»."""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.admin import monitoring_metrics as mm


@pytest.fixture(autouse=True)
def _reset() -> None:
    mm.reset_state_for_tests()
    yield
    mm.reset_state_for_tests()


def test_format_bytes_human() -> None:
    assert mm._format_bytes(0) == "0 B"
    assert mm._format_bytes(500) == "500 B"
    assert mm._format_bytes(1024).startswith("1.00")
    assert "KB" in mm._format_bytes(2048)
    assert "MB" in mm._format_bytes(3 * 1024 * 1024)
    assert mm._format_bytes(-1) == "—"


def test_get_monitored_dir_default() -> None:
    root = mm.get_monitored_dir()
    assert root == mm._default_app_root()
    assert (root / "admin").is_dir()


def test_get_monitored_dir_env_override(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    p = tmp_path / "watched"
    p.mkdir()
    monkeypatch.setenv("MONITORING_APP_DIR", str(p))
    assert mm.get_monitored_dir() == p.resolve()


@patch("app.admin.monitoring_metrics._dir_size_bytes", return_value=1000)
@patch("app.admin.monitoring_metrics._metr_psutil_values")
def test_record_snapshot_series_length(mock_metr: MagicMock, _du: MagicMock) -> None:
    m = MagicMock()
    m.total = 8 * 1024**3
    m.used = 4 * 1024**3
    m.percent = 50.0
    d = MagicMock()
    d.total = 200 * 1024**3
    d.used = 100 * 1024**3
    d.percent = 12.0
    mock_metr.return_value = (m, d, 7.0, "2024-01-01 00:00:00")

    mm.record_snapshot()
    mm.record_snapshot()
    payload = mm.get_payload()
    assert len(payload["cpu_series"]) == 2
    assert payload["cpu"] == 7.0
    assert not payload.get("error")
    assert payload["stale"] is False
    assert payload["app_dir_bytes"] == 1000


@patch("app.admin.monitoring_metrics._dir_size_bytes", return_value=100)
@patch("app.admin.monitoring_metrics._metr_psutil_values")
def test_stale_flag_when_not_updated(mock_metr: MagicMock, _du: MagicMock) -> None:
    m = MagicMock()
    m.total = 8 * 1024**3
    m.used = 4 * 1024**3
    m.percent = 1.0
    d = MagicMock()
    d.total = 200 * 1024**3
    d.used = 1 * 1024**3
    d.percent = 2.0
    mock_metr.return_value = (m, d, 1.0, "t")

    mm.record_snapshot()
    with patch("app.admin.monitoring_metrics.time") as t:
        t.time = MagicMock(return_value=time.time() + 10.0)
        out = mm.get_payload()
    assert out["stale"] is True
