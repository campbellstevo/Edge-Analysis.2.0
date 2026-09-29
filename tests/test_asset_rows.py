"""Assets read like every other comparison (29 Sep, from the 28 Sep blind
check): ranked by R a trade, tested, and the sentence agrees with the rows.

    python -m pytest tests/test_asset_rows.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "src"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from edge_analysis.ui import reshape as rx  # noqa: E402


def _html(monkeypatch, fn):
    out = []
    monkeypatch.setattr(rx.st, "markdown", lambda body, **k: out.append(body))
    assert fn()
    return " ".join(out)


def test_two_losing_assets_are_not_called_best(monkeypatch):
    # the Challenge book: every trade lost, GC worse than MGC
    df = pd.DataFrame({"Closed RR": [-1.2, -1.1, -1.1, -0.7, -0.7, -0.76],
                       "Outcome": ["Loss"] * 6, "Instrument": ["GC"] * 3 + ["MGC"] * 3})
    html = _html(monkeypatch, lambda: rx.label_board(df, df["Instrument"], "Asset", verdicts=True))
    assert "best-performing" not in html and "leads" not in html     # nothing earned, so nothing leads
    assert "<b>GC</b> costs −1.13R a trade over 3" in html
    assert html.index("<span>MGC</span>") < html.index("<span>GC</span>")   # best R a trade first


def test_members_see_no_untested_claim(monkeypatch):
    df = pd.DataFrame({"Closed RR": [1.0, -1.0, 2.0, -1.0, 1.5, -1.0], "Outcome": ["Win", "Loss"] * 3,
                       "Instrument": ["XAUUSD"] * 3 + ["NAS100"] * 3})
    html = _html(monkeypatch, lambda: rx.label_board(df, df["Instrument"], "Asset", verdicts=False,
                                                     empty="Each row is what trades on that asset paid."))
    assert "early read" not in html and "Each row is what trades on that asset paid." in html
