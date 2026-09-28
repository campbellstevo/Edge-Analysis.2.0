"""Externals: one card per market factor (28 Sep, his notes: "why don't we
have anything on the website for gaps" and "only have Market conditions in
externals and nothing else?").

    python -m pytest tests/test_externals.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "src", ROOT / "tests"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from edge_analysis.ui import externals as ex  # noqa: E402

SPEC = {s[0]: s for s in ex.FACTORS}


def _journal(n=19, gap_ticks=1):
    r = [1.3] + [0.1] * (n - 1)
    return pd.DataFrame({
        "Closed RR": r, "Outcome": ["Win" if x > 0.5 else "BE" for x in r],
        "GAP Alignment?": [i < gap_ticks for i in range(n)],
        "Opposing Weak Structure?": [i % 3 == 0 for i in range(n)],
        "Conditions MTF": ["Ranging" if i % 4 else "Trending" for i in range(n)],
        "Conditions HTF": [None] * n,
        "Volatility": [None] * n,
        "Oversold or Overbought?": [False] * n,
    })


def _md(monkeypatch):
    out = []
    monkeypatch.setattr(ex.st, "markdown", lambda body, **_k: out.append(str(body)))
    return out


def test_a_gap_ticked_once_gets_its_own_card_and_one_honest_line(monkeypatch):
    out = _md(monkeypatch)
    df = _journal()
    assert ex.logged(df, SPEC["gap"])
    assert ex.factor_board(df, SPEC["gap"])
    text = " ".join(out)
    assert "You ticked it on <b>1 of 19</b> trades" in text
    assert "too few to compare yet" in text and "GAP Alignment" in text
    assert "ea-pl-row" not in text          # one line, no rows repeating its numbers


def test_a_never_ticked_checkbox_is_not_logged():
    df = _journal(gap_ticks=0)
    assert not ex.logged(df, SPEC["gap"])
    assert not ex.logged(df, SPEC["obos"])
    assert "GAP Alignment" in ex.never_filled(df)


def test_never_filled_names_the_journal_fields(monkeypatch):
    nf = ex.never_filled(_journal())
    assert "Volatility" in nf and "Oversold or Overbought" in nf and "Conditions HTF" in nf
    assert "Conditions MTF" not in nf and "GAP Alignment" not in nf


def test_a_real_split_gets_ranked_rows(monkeypatch):
    out = _md(monkeypatch)
    assert ex.factor_board(_journal(), SPEC["ows"])
    text = " ".join(out)
    assert "ea-pl-row" in text and "Into weak structure" in text and "Clear" in text


def test_members_see_no_early_reads(monkeypatch):
    out = _md(monkeypatch)
    ex.factor_board(_journal(), SPEC["ows"], verdicts=False)
    assert "early read" not in " ".join(out)
