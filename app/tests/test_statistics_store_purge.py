"""Очистка каталога statistics-data."""

from __future__ import annotations

import app.screener.statistics_store as ss


def test_purge_statistics_data_files_removes_jsonl(monkeypatch, tmp_path) -> None:
    root = tmp_path / "statistics-data"
    monkeypatch.setattr(ss, "_STAT_ROOT", root)
    day = root / "2026-04-13"
    day.mkdir(parents=True)
    (day / "bybit-futures-X.jsonl").write_text("{}\n", encoding="utf-8")
    n = ss.purge_statistics_data_files()
    assert n == 1
    assert root.is_dir()
    assert list(root.iterdir()) == []
