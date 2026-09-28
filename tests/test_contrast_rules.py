"""Thin-sample rows read quieter by colour, never by fading their text (28 Sep
contrast sweep: rows at 0.45-0.78 opacity put numbers under 3:1), and dark
mode captions are not left at Streamlit's 0.6 opacity.

    python -m pytest tests/test_contrast_rules.py -q
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "src", ROOT / "tests"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from edge_analysis.ui import reshape as rx, tabs, theme  # noqa: E402


def test_dim_table_rows_are_not_faded():
    src = inspect.getsource(theme)
    assert "tr.dim td {{ opacity" not in src and "tr.dim td { opacity" not in src


def test_mistake_bar_dim_rows_keep_their_text():
    assert ".ea-pb-row.ea-dim{opacity" not in tabs._EA_VIZ_CSS


def test_ranked_rows_few_keeps_text_opaque():
    src = inspect.getsource(rx.ranked_rows)
    assert ".ea-pl-v b{{opacity" not in src and "ea-pl-n span,.ea-pl-row.few" not in src


def test_dark_captions_are_full_opacity():
    src = inspect.getsource(theme.inject_dark_overlay)
    assert '[data-testid="stCaptionContainer"] { opacity: 1 !important; }' in src


def test_break_even_dots_are_readable_on_white():
    assert rx.contrast(rx.BE_GREY, "#ffffff") >= 3.0
