"""Round 10: a field the journal never fills gets no section, and an empty
column can't empty the A-game."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "src"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from edge_analysis.ui import mt5_tabs, pro_tabs, tabs  # noqa: E402


def _capture(monkeypatch, *mods):
    out = []
    for m in mods:
        monkeypatch.setattr(m.st, "markdown", lambda body, **k: out.append(str(body)))
        monkeypatch.setattr(m.st, "caption", lambda body, **k: out.append(str(body)))
    return out


def _df(n=20):
    rng = np.random.default_rng(1)
    rr = np.round(rng.normal(0.2, 1, n), 2)
    return pd.DataFrame({"Closed RR": rr, "Outcome": ["Win" if x > 0.15 else ("Loss" if x < -0.15 else "BE") for x in rr],
                         "Conviction (1-5)": [None] * n, "A+ Setup?": ["Yes"] * 12 + ["No"] * (n - 12),
                         "Rules Followed?": [True] * 15 + [False] * (n - 15), "Mental State": ["Clear & Calm"] * n,
                         "Entry Model 1": [["Internal NC+S"]] * 14 + [[]] * (n - 14),
                         "Multi Entry Model Setup": ["Yes"] * 14 + ["No"] * (n - 14)})


def test_conviction_never_filled_draws_nothing(monkeypatch):
    out = _capture(monkeypatch, mt5_tabs)
    mt5_tabs._conviction_section(_df(), lambda c: c)
    assert out == []


def test_a_game_ignores_an_empty_conviction_column(monkeypatch):
    out = _capture(monkeypatch, pro_tabs, tabs)
    kpis = []
    monkeypatch.setattr(pro_tabs, "_kpi", lambda lab, val, sub, *a: kpis.append(lab))

    class _Col:
        def __enter__(self): return self
        def __exit__(self, *a): return False
    monkeypatch.setattr(pro_tabs.st, "columns", lambda n: [_Col() for _ in range(n)])
    pro_tabs._a_game(_df(), lambda c: c)
    assert "A-Game win rate" in kpis
    assert any("A+ + Rules followed + Clear & Calm" in o for o in out)
    assert not any("Conviction" in o for o in out if o.startswith("A-Game ="))


def test_a_criterion_every_tagged_trade_has_is_not_a_comparison(monkeypatch):
    out = _capture(monkeypatch, tabs)
    tabs._entry_criteria(_df())
    assert not any("Double confirmation" in o for o in out)


def test_context_board_rows(monkeypatch):
    from edge_analysis.ui import reshape as rx
    n = 20
    df = pd.DataFrame({"Closed RR": [1.0] * 10 + [-1.0] * 10,
                       "Conditions MTF": [["Ranging"]] * 10 + [["Trending"]] * 10,
                       "Opposing Weak Structure?": [False] * 16 + [True] * 4,
                       "Oversold or Overbought?": [False] * n,               # never ticked: no row
                       "News Aspect": [["Closed before news >2hs"]] * 5 + [["No News"]] * 15})
    rows = {r["label"]: r for r in rx.context_frame(df)}
    assert set(rows) == {"Conditions (MTF)", "Opposing weak structure", "News"}
    assert {p[0] for p in rows["News"]["parts"]} == {"Closed before news", "No news"}
    out = []
    monkeypatch.setattr(rx.st, "markdown", lambda body, **k: out.append(body))
    assert rx.context_board(df)
    assert "ranging</b> (conditions (mtf)): +10.0R over 10" in out[0]
    assert "beats chance" in out[0]          # 10 vs 10 at +1/-1 is not luck
