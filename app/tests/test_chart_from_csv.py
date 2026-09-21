"""Tests for CSV → PNG chart helper (Marp presentations)."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("matplotlib")

from presentations.chart_from_csv import build_chart, read_xy_series


def test_read_xy_series(tmp_path: Path) -> None:
    p = tmp_path / "d.csv"
    p.write_text("year,growth\n2022,-1.2\n2023,3.6\n", encoding="utf-8")
    xs, ys, rx, ry = read_xy_series(p, None, None)
    assert rx == "year" and ry == "growth"
    assert xs == [2022.0, 2023.0]
    assert ys == [-1.2, 3.6]


def test_build_chart_matplotlib(tmp_path: Path) -> None:
    csv = tmp_path / "d.csv"
    csv.write_text("a,b\n1,10\n2,20\n", encoding="utf-8")
    png = tmp_path / "out.png"
    build_chart(csv, png, backend="matplotlib", title="T", dark=True)
    assert png.is_file()
    assert png.stat().st_size > 500
