"""Tests for presentations/scripts/polza_marp_images.py (slide split, scoring, selection)."""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "presentations" / "scripts"))

import polza_marp_images as pm  # noqa: E402


def test_split_marp_frontmatter_and_slides_with_yaml() -> None:
    doc = """---
marp: true
theme: default
---

# Slide one

Text

---

## Slide two

- a
"""
    fm, slides = pm.split_marp_frontmatter_and_slides(doc)
    assert fm is not None
    assert "marp:" in fm
    assert len(slides) == 2
    assert "Slide one" in slides[0]
    assert "Slide two" in slides[1]


def test_split_without_frontmatter() -> None:
    doc = """# A

---

# B
"""
    fm, slides = pm.split_marp_frontmatter_and_slides(doc)
    assert fm is None
    assert len(slides) == 2


def test_score_prefers_lead_penalizes_table() -> None:
    lead = "<!-- _class: lead -->\n# T\n"
    tab = "| a | b |\n|---|---|\n| 1 | 2 |\n" * 5
    assert pm.score_slide_for_ai(lead) > pm.score_slide_for_ai(tab)


def test_select_respects_max_and_consecutive() -> None:
    scores = [10.0, 10.0, 10.0, 10.0, 10.0]
    picked = pm.select_slide_indices(scores, max_count=3, max_consecutive=2)
    assert len(picked) <= 3
    # cannot pick three consecutive if max_consecutive=2
    for i in range(len(picked) - 2):
        a, b, c = picked[i], picked[i + 1], picked[i + 2]
        assert not (a + 1 == b and b + 1 == c)


def test_build_prompt_includes_palette_from_json(tmp_path: Path) -> None:
    p = tmp_path / "t.json"
    p.write_text(
        '{"semanticTokens": {"background": "#111111", "primary": "#222222"}}',
        encoding="utf-8",
    )
    pal = pm.load_palette_from_tokens(p)
    pr = pm.build_image_prompt(
        title="T",
        gist="g",
        palette=pal,
        placement="side",
    )
    assert "#111111" in pr
    assert "#222222" in pr
