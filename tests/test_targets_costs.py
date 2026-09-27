"""Round 2: targets planned / reached / banked, and costs as one line in R.

    python -m pytest tests/test_targets_costs.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "src", ROOT / "tests"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from edge_analysis.ui import reshape as rx  # noqa: E402
from edge_analysis.ui import pro_tabs  # noqa: E402


def _trades(plan, mfe, r):
    n = len(r)
    return pd.DataFrame({"Date": pd.date_range("2026-09-01", periods=n, freq="D"),
                         "Planned R:R": plan, "MFE (R)": mfe, "Closed RR": r})


def test_targets_summary_counts_reached_and_half():
    df = _trades([2, 4, 3, 2, 5, 1], [2.5, 1.0, 1.6, 0.4, 5.0, None], [2, -1, 1.5, -1, 5, 1])
    g = rx.targets_frame(df)
    assert len(g) == 5                                   # the row with no MFE is left out
    s = rx.targets_summary(g)
    assert s["reached"] == 2 and s["half"] == 3
    assert s["plan"] == pytest.approx(3.2) and s["bank"] == pytest.approx(1.3)
    assert g["when"].iloc[0] == pd.Timestamp("2026-09-05")   # newest first


def test_targets_need_five_trades():
    assert rx.targets_frame(_trades([2] * 4, [1] * 4, [1] * 4)) is None
    assert rx.targets_frame(pd.DataFrame({"Closed RR": [1.0] * 9})) is None


def test_ladder_html(monkeypatch):
    out = []
    monkeypatch.setattr(rx.st, "markdown", lambda body, **k: out.append(body))
    df = _trades([3] * 15, [1.2] * 15, [-1.0] * 15)
    assert rx.targets_ladder(df)
    html = out[0]
    assert html.count('class="ea-tl-r"') == rx.TARGET_ROWS              # last 12 drawn
    assert "the sentence above counts all 15" in html
    assert "translateX(-50%)" in html                                  # CSS minus left alone
    assert "−1R" in html and "reached your target on <b>0 of 15</b>" in html


def test_costs_in_r_spread_and_fees():
    df = pd.DataFrame({"Spread at Entry": [5, 6, 4, 5, 5, 6],
                       "Risk (pips)": [500, 600, 400, 500, 500, 600],
                       "PnL": [100, -100, 200, -50, 150, -100],
                       "Closed RR": [1.0, -1.0, 2.0, -0.5, 1.5, -1.0],
                       "Commission": [-1.0] * 6, "Swap": [0.0] * 6})
    c = pro_tabs.cost_in_r(df)
    assert c["spread"] == pytest.approx(0.01)
    assert c["fees"] == pytest.approx(0.01)            # $1 a trade at $100 per R
    assert c["total"] == pytest.approx(0.02)
    line = pro_tabs.cost_line(c)
    assert "about <b>0.02R</b> a trade" in line and "Nothing to fix" in line
    assert "$" not in line


def test_costs_skip_spread_when_units_disagree():
    df = pd.DataFrame({"Spread at Entry": [50] * 6, "Risk (pips)": [40] * 6, "Closed RR": [1.0] * 6})
    assert pro_tabs.cost_in_r(df) is None               # points vs pips: 125% of the stop isn't real


def test_big_costs_say_so():
    c = {"spread": 0.04, "fees": 0.08, "total": 0.12}
    assert "Worth checking" in pro_tabs.cost_line(c)


def test_execution_section_steps_aside_for_the_ladder(monkeypatch):
    from edge_analysis.ui import mt5_tabs
    drawn = []
    monkeypatch.setattr(mt5_tabs.st, "markdown", lambda *a, **k: drawn.append(a[0]))
    monkeypatch.setattr(mt5_tabs.st, "caption", lambda *a, **k: drawn.append(a[0]))
    df = _trades([2] * 6, [1] * 6, [1] * 6)
    mt5_tabs._execution_section(df, lambda c: c, planned_kpis=False)
    assert drawn == []                                   # only planned R:R to show, and the ladder has it
