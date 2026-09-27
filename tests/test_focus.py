"""Focus is a briefing: can I trade, the checklist, lean/stay, after the last trade."""
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from edge_analysis.ui import focus as fo  # noqa: E402


def _g(rs, start="2026-09-01 20:00"):
    return pd.DataFrame({"__dt": pd.date_range(start, periods=len(rs), freq="D"), "__rr": rs})


def test_state_follows_the_breaker_lines():
    now = pd.Timestamp("2026-09-20")
    assert fo.right_now(_g([1.0, -1.0, 0.5]), 5.0, -6.0, now)["state"] == "clear"
    assert fo.right_now(_g([-1.0] * 5), 5.0, -6.0, now)["state"] == "careful"      # 1R above the stop
    assert fo.right_now(_g([-1.0] * 6), 5.0, -6.0, now)["state"] == "stop"
    assert fo.right_now(_g([2.0, 2.0, 1.5]), 5.0, -6.0, now)["state"] == "target"


def test_right_now_counts_this_month_and_week_only():
    g = pd.concat([_g([3.0, 3.0], "2026-08-20 20:00"), _g([1.0, -1.0, 2.0], "2026-09-17 20:00")])
    s = fo.right_now(g, 5.0, -6.0, pd.Timestamp("2026-09-20"))
    assert s["mtd"] == 2.0 and s["n_month"] == 3
    assert s["n_week"] == 3 and s["week_r"] == 2.0          # Thu 17 - Sat 19 Sep, week to Sun 20
    assert s["path"] == [1.0, 0.0, 2.0]


def test_after_last_reads_the_streak_and_what_followed_it():
    # losses followed by: +1, -1, +2, -1, +1 ... then the journal ends on two losses
    rs = [-1, 1, -1, -1, 2, -1, -1, -1, 1, 1, -1, 2, -1, -1]
    a = fo.after_last(_g([float(r) for r in rs]), min_n=2)
    assert a["kind"] == "loss" and a["streak"] == 2 and a["run"] == 2
    # after two losses in a row (excluding the final pair): next = 2, -1, 1  → avg 0.67 over 3
    assert a["same_n"] == 3 and round(a["same_avg"], 2) == 0.67
    txt = fo._after_text(a)
    assert "2 losses in a row" in txt and "over 3 trades" in txt


def test_after_last_says_too_few_rather_than_guessing():
    a = fo.after_last(_g([1.0, -1.0, -1.0]), min_n=5)
    assert a["same_avg"] is None and "too few" in fo._after_text(a)


def test_breakevens_are_not_losses_when_the_journal_says_so():
    # his last four: Loss, BE (-0.26R), Loss, BE (-0.22R) — not "4 losses in a row"
    g = _g([-1.01, -0.26, -1.03, -0.22])
    g["Outcome"] = ["Loss", "BE", "Loss", "BE"]
    a = fo.after_last(g, min_n=1)
    assert a["kind"] == "be" and a["streak"] == 1
    assert "losses in a row" not in fo._after_text(a)
    g2 = g.drop(columns="Outcome")                        # no tags: fall back to the R bands
    assert fo.after_last(g2, min_n=1)["kind"] == "loss"


def test_checklist_merges_numbers_notes_and_rules():
    proven = [("Your proven timeframes — 5M", 0.81, True, False)]
    recs = [("keep:A+ setups", "Only take A+ setups", "worth +0.51R a trade over 11 trades", True),
            ("keep:Asia session", "Trade the Asia session", "worth +0.37R a trade over 11 trades", True),
            ("avoid:New York session", "Skip the New York session", "costing −0.53R a trade over 6 trades", False)]
    groups = [{"theme": "Taking profit", "n": 4, "rows": [{"text": "Dont be more ambitious than TP2"},
                                                          {"text": "A much longer note about the target that ran on"}]},
              {"theme": "Other", "n": 2, "rows": [{"text": "x"}]}]
    items = fo.checklist_items(proven, recs, groups, ["No trades after two losses", "Only take A+ setups"],
                               beats=set(), gate_beats=set())
    texts = [i["text"] for i in items]
    assert texts == ["Timeframes — 5M", "Only take A+ setups", "Skip the New York session",
                     "Is my target somewhere price actually gets to?", "No trades after two losses"]
    assert items[0]["chip"] == "+0.81R" and "early read" in items[0]["sub"]
    assert items[2]["chip"] == "−0.53R"
    assert "“Dont be more ambitious than TP2”" in items[3]["sub"] and items[3]["chip"] == "4×"


def test_a_notion_result_column_counts_too():
    g = _g([-1.0, -0.22])
    g["Result"] = ["Loss", "BE"]
    assert fo.after_last(g, min_n=1)["kind"] == "be"
