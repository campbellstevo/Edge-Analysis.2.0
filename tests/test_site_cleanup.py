"""Site clean-up (his notes, 26 Sep): conditions verdict, spacing, quiet empty states."""
import re
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from edge_analysis.ui import reshape as rx  # noqa: E402
from edge_analysis.ui import tabs  # noqa: E402


def _capture(monkeypatch):
    out = []
    for mod in (tabs.st, rx.st):
        monkeypatch.setattr(mod, "markdown", lambda body, **k: out.append(str(body)))
        monkeypatch.setattr(mod, "caption", lambda body, **k: out.append(str(body)))
    return out


def _conditions(trend_r, range_r):
    rows = ([{"Conditions MTF": "Trending", "Closed RR": r} for r in trend_r]
            + [{"Conditions MTF": "Ranging", "Closed RR": r} for r in range_r])
    g = pd.DataFrame(rows)
    g["Outcome"] = g["Closed RR"].map(lambda r: "Win" if r > 0.05 else ("Loss" if r < -0.05 else "BE"))
    return g


def test_conditions_never_names_one_cell_best_and_lowest(monkeypatch):
    out = _capture(monkeypatch)
    # 5 trending trades, 12 ranging: the old 8-trade floor left one cell and
    # printed it as both "Best" and "Lowest"
    tabs._conditions_tab(_conditions([-1.0, -1.0, -1.0, -1.0, 0.6],
                                     [1.0, -1.0, 0.5, 0.2, -0.4, 1.5, 0.0, -1.0, 0.9, 0.3, -0.2, 1.56]),
                         show_table=False)
    text = " ".join(out)
    assert "Lowest" not in text and "Best condition" not in text
    assert "Ranging pays best" in text and "5 trending" in text
    # the takeaway sits under the grid, not above it
    assert text.index("Timeframe") < text.index("Ranging pays best")


def test_conditions_says_so_when_states_match(monkeypatch):
    out = _capture(monkeypatch)
    tabs._conditions_tab(_conditions([0.5, -0.5, 0.5, -0.5, 0.2], [0.5, -0.5, 0.5, -0.5, 0.2]),
                         show_table=False)
    assert "No real difference" in " ".join(out)


def test_spacers_are_marked_so_the_theme_can_collapse_doubles(monkeypatch):
    out = _capture(monkeypatch)
    tabs._gap(18)
    assert "class='ea-gap'" in out[0]


def test_no_empty_wrapper_blocks_left():
    # a bare </div> or a lone <div class="section"> drew nothing but took a
    # 12px gap each; they were the other half of the "random spaces"
    pat = re.compile(r'st\.markdown\((?:"</div>"|\'</div>\'|\'<div class="section">\')\s*,')
    for f in ("tabs.py", "mt5_tabs.py", "pro_tabs.py"):
        src = (ROOT / "src" / "edge_analysis" / "ui" / f).read_text()
        assert not pat.search(src), f


def test_not_enough_data_is_a_quiet_note_not_a_warning():
    src = (ROOT / "src" / "edge_analysis" / "ui" / "pro_tabs.py").read_text()
    assert not re.search(r'_insight_box\("Need ~', src)
    assert "you have {len(wins)} so far" in src


def test_suggested_rules_are_choices_with_real_evidence():
    from edge_analysis.ui.plan_tabs import rule_recommendations
    good = [("London session", 0.55, 3), ("A+ setups", 0.30, 13), ("Asia session", 0.17, 13),
            ("Single entry", 0.11, 6)]
    bad = [("Non-A+ setups", -1.22, 4), ("New York session", -0.60, 7),
           ("Good headspace", -0.16, 16), ("Multi-entry", -0.06, 17)]
    recs = rule_recommendations(good, bad)
    rules = [r[1] for r in recs]
    assert rules == ["Skip the New York session", "Only take A+ setups", "Trade the Asia session"]
    assert not any("headspace" in r.lower() for r in rules)     # not a choice to avoid
    assert not any("London" in r for r in rules)                # 3 trades is a reading, not a rule
    assert "−0.60R a trade over 7 trades" in recs[0][2] or "-0.60R a trade over 7 trades" in recs[0][2]


def test_a_pair_is_one_rule_and_the_stronger_side_speaks():
    from edge_analysis.ui.plan_tabs import rule_recommendations
    recs = rule_recommendations([("A+ setups", 0.30, 13)], [("Non-A+ setups", -0.42, 10)])
    assert [(r[0], r[1]) for r in recs] == [("avoid:Non-A+ setups", "Only take A+ setups")]


def test_weekly_tagging_ignores_fields_never_filled():
    g = pd.DataFrame({"A+ Setup?": ["Yes", "No", "Yes"], "Mistake": ["NA", "Overtraded", "NA"],
                      "Conviction (1-5)": [None, None, None]})
    assert rx.used_tags(g, ["A+ Setup?", "Conviction (1-5)", "Mistake"]) == ["A+ Setup?", "Mistake"]


def test_explorer_starts_with_ten_rows_under_week_headers(monkeypatch):
    import contextlib
    out = []
    monkeypatch.setattr(rx.st, "markdown", lambda body, **k: out.append(str(body)))
    monkeypatch.setattr(rx.st, "caption", lambda body, **k: out.append(str(body)))
    monkeypatch.setattr(rx.st, "radio", lambda *a, **k: "All")
    monkeypatch.setattr(rx.st, "selectbox", lambda label, opts, **k: list(opts)[0])
    monkeypatch.setattr(rx.st, "text_input", lambda *a, **k: "")
    monkeypatch.setattr(rx.st, "button", lambda *a, **k: False)
    monkeypatch.setattr(rx.st, "columns", lambda spec, **k: [contextlib.nullcontext()] * (spec if isinstance(spec, int) else len(spec)))
    n = 30
    g = pd.DataFrame({"__Date": pd.date_range("2026-08-01 20:00", periods=n, freq="D"),
                      "Closed RR": [1.0, -1.0, 0.0] * 10})
    try:
        rx.trade_explorer(g, key="t_tx")
    except Exception:
        pass   # the trade card below the list needs the full widget set
    table = next(b for b in out if 'class="ea-tx"' in b)
    assert table.count('class="wk"') >= 2                 # 10 days span two or three weeks
    assert table.count("<tr><td") == 10                   # ten trades, not 25
    assert any("Showing 10 of 30" in b for b in out)


def test_live_money_leads_when_the_journal_has_a_live_track_record(monkeypatch):
    import filters
    state = {}
    monkeypatch.setattr(filters.st, "session_state", state)
    opts = ["Live money", "All", "Challenge", "Live"]
    assert filters._tot_default_for(opts) == "All"            # app.py hasn't decided
    state["ea_tot_default"] = "Live money"
    assert filters._tot_default_for(opts) == "Live money"
    assert filters._tot_default_for(["Executed", "All", "Forward test", "Live"]) == "Executed"
