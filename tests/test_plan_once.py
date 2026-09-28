"""The Plan view says each rule and each number once (his note, 28 Sep: "you
double down on the A+ setup rule, on suggested and in my process").

    python -m pytest tests/test_plan_once.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "src", ROOT / "tests"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from edge_analysis.ui import plan_tabs as pt  # noqa: E402
from edge_analysis.ui import tabs  # noqa: E402

GOOD = [("A+ setups", 0.39, 16), ("Asia session", 0.37, 11)]
BAD = [("Non-A+ setups", -0.83, 3), ("New York session", -0.53, 6)]


def _owner(monkeypatch, state=None):
    monkeypatch.setattr(tabs, "_verdicts_on", lambda: True)
    st_ = state or {"custom": [], "accepted": [], "declined": []}
    monkeypatch.setattr(pt, "_rules_state", lambda: st_)


def test_a_checklist_box_is_never_suggested_again(monkeypatch):
    _owner(monkeypatch)
    rules = [r[1] for r in pt.pending_recs(GOOD, BAD, covered={"aplus"})]
    assert "Only take A+ setups" not in rules
    assert "Skip the New York session" in rules and "Trade the Asia session" in rules


def test_without_the_box_the_suggestion_stays(monkeypatch):
    _owner(monkeypatch)
    assert "Only take A+ setups" in [r[1] for r in pt.pending_recs(GOOD, BAD)]


def test_his_own_rule_word_for_word_is_not_suggested(monkeypatch):
    _owner(monkeypatch, {"custom": ["trade the asia session"], "accepted": [], "declined": []})
    assert "Trade the Asia session" not in [r[1] for r in pt.pending_recs(GOOD, BAD)]


def test_members_get_no_suggestions(monkeypatch):
    monkeypatch.setattr(tabs, "_verdicts_on", lambda: False)
    assert pt.pending_recs(GOOD, BAD) == []


def test_every_refinement_that_restates_a_leak_names_it():
    stats = {"overall_win_rate": 30, "overall_net_rr": -2.0, "overall_trades": 20,
             "by_session": [{"session": "Asia", "trades": 9, "win_rate": 40, "net_rr": 3.0},
                            {"session": "New York", "trades": 8, "win_rate": 10, "net_rr": -4.0}],
             "bad_beat_count": 3, "bad_beat_pct": 15, "early_close_net": -1.5}
    res = tabs._compute_refinements(stats)
    leaks = {it["title"] for it in res["holding_back"]}
    paired = [it for it in res["refinements"] if it.get("of")]
    assert paired, res["refinements"]
    assert all(it["of"] in leaks for it in paired)
