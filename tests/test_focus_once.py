"""Focus says what the rest of the site says (29 Sep, from the 28 Sep blind
check): the best setup is Entry's best, a tie among lessons is named as a
tie, copies of one note are one note, and the Right now line doesn't repeat
the bar under it.

    python -m pytest tests/test_focus_once.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "src"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from edge_analysis.ui import focus as fo  # noqa: E402
from edge_analysis.ui import lessons as ls  # noqa: E402
from edge_analysis.ui import reshape as rx  # noqa: E402


def _g(rows):
    d = pd.date_range("2026-09-01 20:00", periods=len(rows), freq="D")
    g = pd.DataFrame(rows, columns=["__rr", "Entry Model 1", "Entry Model 2"])
    g["__dt"] = d
    g["Date"] = d
    g["Outcome"] = ["Win" if r > 0.15 else ("Loss" if r < -0.15 else "BE") for r in g["__rr"]]
    return g


def test_best_setup_is_entrys_best_by_r_a_trade():
    # A->B: 7 trades, +4.2R in total but +0.60R a trade; C->B: 3 trades at +1.0R a trade
    rows = [(1.8, "A", "B"), (-1.0, "A", "B"), (1.6, "A", "B"), (-1.0, "A", "B"),
            (2.8, "A", "B"), (-1.0, "A", "B"), (1.0, "A", "B"),
            (1.0, "C", "B"), (1.0, "C", "B"), (1.0, "C", "B")]
    items = {i["area"]: i["html"] for i in fo.rundown(_g(rows), verdicts=True)}
    assert "<b>C</b> then <b>B</b>" in items["Best setup"] and "+1.00R a trade over 3" in items["Best setup"]


def test_a_tie_among_lessons_is_named_as_a_tie():
    groups = [{"theme": "Where you get in", "n": 4}, {"theme": "Sweeps and liquidity", "n": 4},
              {"theme": "Taking profit", "n": 4}, {"theme": "News", "n": 2}]
    html, tied = ls.top_line(groups)
    assert tied and "(4× each)" in html and "sweeps and liquidity" in html and "news" not in html
    assert ls.top_line(groups[2:]) == ("<b>taking profit</b> (4×)", False)


def test_a_note_copied_onto_same_day_trades_is_written_once():
    df = pd.DataFrame({"Date": pd.to_datetime(["2026-09-14 20:00", "2026-09-14 21:00", "2026-09-20 20:00"]),
                       "Closed RR": [-1.0, -1.0, 1.0],
                       "Teachings/Learning Curve": ["Hold to TP2", "Hold to TP2", "Hold to TP2"]})
    g = ls.summary(df)["groups"]
    assert g and g[0]["n"] == 2                       # 14 Sep's copy is one note, not two


def test_right_now_line_leaves_the_bar_its_numbers():
    t = rx._tokens()
    s = {"state": "clear", "tgt": 5.0, "stop": -6.0, "mtd": -1.8, "room": 4.2, "month_name": "September",
         "last": None, "week_r": -1.0, "n_week": 1}
    html = fo._right_now_html(s, None, t)
    assert html.count("−1.8R") == 1              # the month's R once: on the bar


def test_the_rundown_follows_the_filters_and_says_so():
    from streamlit.testing.v1 import AppTest

    def script():
        import pandas as pd
        import streamlit as st
        from edge_analysis.ui.focus import render_focus
        d = pd.date_range("2026-09-01 20:00", periods=12, freq="D")
        df = pd.DataFrame({"Date": d, "Closed RR": [1.0, -1.0] * 6, "Outcome": ["Win", "Loss"] * 6,
                           "Session": ["London"] * 4 + ["Asia"] * 8})
        df["PnL_from_RR"] = df["Closed RR"]
        st.session_state["filters_sess_select"] = "London"
        render_focus(df[df["Session"] == "London"], df, lambda c: c)

    at = AppTest.from_function(script, default_timeout=60)
    at.run()
    assert not at.exception, at.exception
    text = " ".join(str(m.value) for m in at.markdown)
    assert "for the 4 trades your filters leave" in text
    assert "over 4 trades" in text                         # the record line reads the filtered trades


def test_plan_can_still_format_the_focus_template():
    # Plan's "Before you take a trade" formats Focus's template with these keys
    # only; a new placeholder broke it on 29 Sep before it shipped
    fo._CSS.format(bg="", bc="", c="", **rx._tokens())
