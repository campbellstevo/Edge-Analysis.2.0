"""Reshaped views (launch review mockups): the helpers under the new grids."""
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from edge_analysis.ui import reshape as rx  # noqa: E402


def test_parse_hour_reads_every_clock_format():
    assert rx._parse_hour("9:15 PM") == 21
    assert rx._parse_hour("12:05 AM") == 0
    assert rx._parse_hour("2026-09-21 19:07") == 19
    assert rx._parse_hour("after NY") is None
    assert rx._parse_hour(float("nan")) is None


def test_trade_hours_prefers_the_journal_clock():
    salty = pd.DataFrame({"Time of Trade": ["8:30 PM", "soon", "07:10"]})
    assert list(rx.trade_hours(salty)[[0, 2]]) == [20, 7]
    mt5 = pd.DataFrame({"Hour (Melb)": [16, 23]})
    assert list(rx.trade_hours(mt5)) == [16, 23]
    # date-only journals carry no hour at all: no bars, no grid
    date_only = pd.DataFrame({"Date": pd.to_datetime(["2026-09-01", "2026-09-02"])})
    assert rx.trade_hours(date_only) is None


def test_stats_use_house_definitions():
    g = pd.DataFrame({"Outcome": ["Win", "BE", "Loss", "Loss"], "Closed RR": [2.0, 0.0, -1.0, -1.0]})
    s = rx._stats(rx._counted(g))
    assert s["n"] == 4
    assert s["win"] == 25.0          # wins over every counted trade
    assert s["exp"] == 0.0 and s["net"] == 0.0


def test_metric_text():
    assert rx._metric_txt(0.456, "Expectancy") == "+0.46R"
    assert rx._metric_txt(-3.21, "Net R") == "−3.2R"
    assert rx._metric_txt(42.4, "Win rate") == "42%"
    assert rx._metric_txt(None, "Expectancy") == "—"
    assert rx._metric_txt(-0.001, "Expectancy") == "0.00R"


def _capture(monkeypatch):
    out = []
    monkeypatch.setattr(rx.st, "markdown", lambda body, **k: out.append(body))
    return out


def test_pair_grid_reads_double_confirmation_journals(monkeypatch):
    out = _capture(monkeypatch)
    g = pd.DataFrame({
        "Outcome": ["Win"] * 3 + ["Loss"] * 3 + ["BE"],
        "Closed RR": [2.0, 3.0, 1.5, -1.0, -1.0, -1.1, 0.0],
    })
    m1 = pd.Series(["Internal NC+S"] * 6 + ["External NC+S"])
    m2 = pd.Series(["Internal NC+S"] * 7)
    assert rx.pair_grid(g, m1, m2, "Expectancy", min_n=5)
    html = "".join(out)
    assert "Internal NC+S" in html and "External NC+S" in html
    assert 'class="few' in html          # the 1-trade pair is hatched, not coloured
    assert "+0.57R" in html              # 6 trades: (2+3+1.5-3.1)/6


def test_grids_drop_blocks_nobody_trades(monkeypatch):
    out = _capture(monkeypatch)
    g = pd.DataFrame({
        "Outcome": ["Win", "Loss"] * 5, "Closed RR": [1.0, -1.0] * 5,
        "Hour (Melb)": [19, 20] * 5, "DayName": ["Monday", "Tuesday"] * 5,
    })
    assert rx.day_time_grid(g, "Expectancy")
    html = "".join(out)
    assert "16–20" in html and "04–08" not in html


def test_discipline_hero_never_claims_a_gap_that_is_not_there(monkeypatch):
    out = _capture(monkeypatch)
    rx.discipline_hero(71, 166, 233, [(26, "went past your monthly cap")], "x",
                       clean_r=0.16, flag_r=0.40, days=[("d", True)], facts=[])
    html = "".join(out)
    assert "That gap is what discipline is worth" not in html
    assert "no worse on average" in html
    out.clear()
    rx.discipline_hero(76, 178, 233, [], "x", clean_r=0.44, flag_r=-0.43)
    assert "That gap is what discipline is worth" in "".join(out)


def test_exit_whatif_uses_the_simulator_model():
    g = pd.DataFrame({"mfe": [2.5, 0.4, 1.2, 3.0], "r": [2.4, -1.0, 0.0, 1.0], "mae": [-0.2, -1.0, -0.5, -0.3]})
    wf, actual = rx.exit_whatif(g)
    assert actual == 2.4
    at2 = wf.set_index("T").loc[2.0]
    # 2.5 and 3.0 reached 2R -> +2 each; 0.4 hit its stop -> -1; 1.2 keeps its 0.0
    assert at2["net"] == 3.0 and at2["hit"] == 50.0


def test_week_report_says_the_conclusion_first(monkeypatch):
    out = _capture(monkeypatch)
    rx.week_report("", "A green week, made by one trade.", "Wednesday's <b>+3.80R</b> carried it.", "C",
                   [("Net", "+4.6R", "last 4 weeks: −0.5R a week", "#16a34a")],
                   [("Mon", 1.8, 1), ("Tue", None, 0)], [], [("Mistakes logged", "Overtraded ×1")])
    html = "".join(out)
    assert html.index("A green week") < html.index("+4.6R")      # sentence before numbers
    assert "PROCESS" in html and "Overtraded" in html
    assert "Nothing stood out either way." in html               # empty keep list says so


def test_record_stats_drawdown_and_streaks():
    r = pd.Series([1.0, 2.0, -1.0, -1.0, 0.0, -1.0, 3.0, 1.0, -1.0])
    d = pd.Series(pd.date_range("2026-09-01", periods=len(r)))
    s = rx.record_stats(r, d)
    assert s["net"] == 3.0 and s["n"] == 9
    assert s["maxdd"] == -3.0                           # peak +3 after trade 2, trough 0 after trade 6
    assert s["dd_from"] == d[1] and s["dd_to"] == d[5] and s["dd_back"] == d[6]
    assert s["best_w"] == 2 and s["best_l"] == 3        # the scratch breaks no streak
    assert s["cur"] == -1
    assert round(s["win"]) == 44 and round(s["be"]) == 11


def test_explorer_frame_reads_both_journal_shapes():
    g = pd.DataFrame({
        "__Date": pd.to_datetime(["2026-09-21 16:33", "2026-09-22 09:10", "2026-09-23 20:00"]),
        "Closed RR": [-1.06, 2.1, 0.0],
        "Entry Model 1": ["Internal NC+S", "External NC+S", None],
        "Entry Model 2": ["Internal NC+S", None, None],
        "Rules Followed?": ["Yes", "No", None],
        "Mistake": ["No A+ setup", "", "NA"],
        "Comment": ["<b>chased</b>", None, ""],
    })
    x = rx.explorer_frame(g)
    assert list(x["r"]) == [0.0, 2.1, -1.06]                       # newest first
    first = x.iloc[-1]
    assert first["setup"] == "Internal NC+S → Internal NC+S"   # the pair is the setup
    assert bool(first["flag"]) and bool(x.iloc[1]["flag"])          # mistake / rule broken
    assert not bool(x.iloc[0]["flag"])                               # "NA" is no mistake
    assert first["notes"] == "<b>chased</b>"                        # escaped at render, kept raw here


def test_share_card_is_a_png_with_r_only():
    png = rx.share_card_png("Week of 21 Sep", "+4.6R", "this week",
                            ["50% won · 7 trades", "rules followed 6 of 7", "best +3.8R · Internal FBoS"],
                            [0.0, 1.0, 0.5, 2.0, 4.6])
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    from PIL import Image
    import io
    assert Image.open(io.BytesIO(png)).size == (1200, 630)
