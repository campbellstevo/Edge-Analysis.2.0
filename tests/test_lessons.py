"""Your lessons (round-1 mockup M9) and the sync-note filter on Every trade.

    python -m pytest tests/test_lessons.py -q
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

from edge_analysis.ui import lessons as ls  # noqa: E402
from edge_analysis.ui.reshape import _note_text  # noqa: E402


@pytest.mark.parametrize("text, theme", [
    ("Dont be greedy past TP2", "Taking profit"),          # lower-case "be" is not breakeven
    ("Set BE at TP1 next time", "Breakeven"),               # BE wins over TP when both appear
    ("Could have used SL2TP1 once it ran", "Taking profit"),
    ("Was too aggressive with my TP, aimed for TP3", "Taking profit"),
    ("Too tight with SL placement", "Stop placement"),
    ("Price swept lower before it went", "Sweeps and liquidity"),
    ("Flipped my bias too quickly", "Bias"),
    ("Traded the middle of a range again", "Where you get in"),
    ("Took a late entry after missing it", "Where you get in"),
    ("Against opposing weak structure", "Where you get in"),
    ("Revenge trade, walk away", "Patience and rules"),
    ("Traded straight into CPI", "News"),
    ("Felt good today", "Other"),
])
def test_theme_of(text, theme):
    assert ls.theme_of(text) == theme


def _journal(notes, rs=None, plan=None, mfe=None):
    n = len(notes)
    d = {"__Date": pd.date_range("2026-08-01", periods=n, freq="D"),
         "Closed RR": rs or [1.0] * n,
         "Teachings/Learning Curve": notes}
    if plan is not None:
        d["Planned R:R"], d["MFE (R)"] = plan, mfe
    return pd.DataFrame(d)


def test_summary_groups_repeats_and_skips_blanks():
    df = _journal(["Hold to TP2", "NA", "", "Take profit at the target", "SL too tight",
                   "Close early near the target", "Swept first"],
                  rs=[2.0, -1.0, -1.0, 1.5, -1.0, 0.5, -1.0])
    s = ls.summary(df)
    assert s["n_trades"] == 7 and s["n_lessons"] == 5          # "NA" and "" are not lessons
    top = s["groups"][0]
    assert top["theme"] == "Taking profit" and top["n"] == 3
    assert top["r"] == pytest.approx(4.0)
    assert [g["theme"] for g in s["groups"]] == ["Taking profit"]  # singles don't form a group
    assert {r["text"] for r in s["singles"]} == {"SL too tight", "Swept first"}
    assert s["all"][0]["text"] == "Swept first"                   # newest first


def test_targets_line_counts_trades_that_reached_the_plan():
    df = _journal(["x"] * 6, plan=[2.0, 3.0, 4.0, 2.0, 5.0, 1.0], mfe=[2.5, 1.0, 1.0, 0.5, 5.0, None])
    assert "<b>2 of 5</b>" in ls._targets_line(df)
    assert ls._targets_line(df.head(4)) == ""                     # too few to say anything


def test_no_lesson_column_means_no_card():
    assert ls.lessons_frame(pd.DataFrame({"Closed RR": [1.0]})).empty
    assert ls.summary(pd.DataFrame({"Closed RR": [1.0]}))["n_lessons"] == 0


def test_lesson_text_is_escaped():
    import html
    df = _journal(["<b>Hold</b> to TP2", "TP2 <script>x</script>", "TP1 & out"])
    s = ls.summary(df)
    assert s["groups"][0]["n"] == 3
    assert "<script>" not in html.escape(s["groups"][0]["rows"][0]["text"])


@pytest.mark.parametrize("raw, kept", [
    ("[sl 4587.60]", ""),
    ("[tp 4601.19]", ""),
    ("CON.F.US.GCE.Z26 (GCZ6) · 1 fill(s) in / 1 out · gross -450.00, fees 3.32", ""),
    ("Dont chase the second push", "Dont chase the second push"),
    ("sl too tight at the swing", "sl too tight at the swing"),
])
def test_sync_notes_never_reach_the_trade_list(raw, kept):
    # a broker sync's comment isn't the trader's words, and Topstep's carries dollars
    assert _note_text(raw) == kept


def test_demo_has_lessons_and_its_numbers_did_not_move():
    from edge_analysis.demo import demo_df
    d = demo_df(today=pd.Timestamp("2026-09-27"))
    assert (d["Teachings/Learning Curve"] != "").sum() >= 20
    assert round(float(d["Closed RR"].sum()), 2) == 44.68


def test_targets_line_stays_quiet_when_targets_are_mostly_reached():
    df = _journal(["x"] * 5, plan=[2.0] * 5, mfe=[2.5, 3.0, 2.0, 1.0, 0.5])
    assert ls._targets_line(df) == ""                              # 3 of 5 reached: nothing to agree with


def test_at_most_four_theme_cards(monkeypatch):
    notes = ["TP2 hold"] * 2 + ["BE early"] * 2 + ["SL tight"] * 2 + ["swept first"] * 2 + ["bias flip"] * 2
    html_out = []
    monkeypatch.setattr(ls.st, "markdown", lambda body, **k: html_out.append(body))
    monkeypatch.setattr(ls.st, "expander", lambda *a, **k: __import__("contextlib").nullcontext())
    monkeypatch.setattr(ls.st, "caption", lambda *a, **k: None)
    assert ls.render_lessons(_journal(notes))
    first = html_out[0]
    assert first.count('class="ea-ls-card"') == 4
    assert "Also written more than once:" in first
