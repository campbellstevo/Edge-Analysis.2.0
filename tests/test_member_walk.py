"""What a member on another template meets — found on the Salty member walk
(25 Sep 2026): the app read as the owner's playbook in places.

    python -m pytest tests/test_member_walk.py -q
"""
from __future__ import annotations

import sys
import uuid
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "src", ROOT / "tests"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from streamlit.testing.v1 import AppTest  # noqa: E402

import salty_fixture  # noqa: E402
from edge_analysis.core.parsing import normalize_entry_model, smart_title  # noqa: E402
from edge_analysis.data import notion_adapter as na  # noqa: E402


@pytest.mark.parametrize("raw,shown", [("FBoS", "FBoS"), ("NC Model", "NC Model"),
                                        ("protected structure continuation",
                                         "Protected Structure Continuation"),
                                        ("no close", "No Close"), ("NC+S", "NC+S")])
def test_model_names_keep_the_traders_capitals(raw, shown):
    assert normalize_entry_model(raw) == shown       # was "Fbos", "Nc Model"
    assert smart_title(raw) == shown


def test_formulas_are_read_for_salty_only():
    props = {"Deviation Score": {"type": "formula",
                                 "formula": {"type": "string", "string": "1 = Small deviation"}},
             "Running R ": {"type": "formula", "formula": {"type": "number", "number": 4.0}}}
    assert na._flatten_props(props) == {"Deviation Score": None, "Running R ": None}
    assert na._flatten_props(props, formulas=True) == {"Deviation Score": "1 = Small deviation",
                                                        "Running R ": 4.0}


def test_deviation_scores_parse_only_the_1_to_3_scale():
    from edge_analysis.ui.tabs import _deviation_scored
    f = pd.DataFrame({"Deviation Score": ["1 = Small deviation", "3", "2.0", "0.35", None, "12"],
                      "Outcome": ["Win"] * 6})
    assert _deviation_scored(f)["__dev_num"].tolist() == [1.0, 3.0, 2.0]


def test_every_confluence_tag_gets_its_own_row():
    from edge_analysis.ui.tabs import _confluence_tags
    assert _confluence_tags("Sweep, GAP") == ["Sweep", "GAP"]
    assert _confluence_tags(["Divergence"]) == ["Divergence"]
    assert _confluence_tags(None) == [] and _confluence_tags("") == []


@pytest.fixture
def member(monkeypatch):
    salty_fixture.FakeNotionClient.pages = salty_fixture.salty_pages()
    monkeypatch.setattr(na, "Client", salty_fixture.FakeNotionClient)
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=180)
    at.session_state["user_notion_token"] = "test-" + uuid.uuid4().hex
    at.session_state["override_DATABASE_ID"] = uuid.uuid4().hex
    at.session_state["user_id"] = "member-" + uuid.uuid4().hex[:8]
    at.secrets["EA_ACCESS"] = "open"
    at.run()
    at.run()
    return at


def _view(at, name):
    at.session_state["ea_tab"] = name
    at.session_state["ea_nav_external"] = True
    at.run()
    assert not at.exception, at.exception
    return " ".join(str(m.value) for m in at.markdown) + " " + " ".join(
        str(c.value) for c in at.caption)


def test_plan_shows_the_members_boxes_not_the_owners_playbook(member):
    text = _view(member, "Plan")
    for owners in ("Headspace is Good", "genuine A+ setup", "True break confirmed",
                   "start tagging this in Notion"):
        assert owners not in text, owners
    assert "You followed your own rules" in text      # the member's own tag is a box


def test_entry_lists_every_confluence_and_no_empty_cards(member):
    text = _view(member, "Entry")
    assert "GAP" in text and "Divergence" in text     # was one "DIV & Sweep" row
    assert "No deviation score data recorded" not in text
    assert "FBoS" in text and "Fbos" not in text


def test_externals_has_no_developer_empty_state(member):
    text = _view(member, "Externals")
    assert "Conditions ETF/MTF/HTF" not in text


def test_a_date_only_journal_keeps_its_own_calendar_day(member):
    # Salty's Date is the trader's day; inferring an offset from the 17:30
    # clock slid every trade back a day (1 Sep trades counted in August).
    _view(member, "Review")
    assert member.session_state["ea_tz_offset"] == 0


def test_refinements_are_owner_only(member):
    text = _view(member, "Plan")
    assert "Data-backed tweaks worth testing next" not in text
    assert "Keep stacking this condition" not in text


def test_discipline_score_counts_every_rule(member):
    # 25 Sep: the score counted only overtrading days and revenge entries, so
    # it read 100% beside 14 of 23 rules followed and 18 trades on a cap of 12.
    import re
    text = _view(member, "Psychology")
    m = re.search(r"Discipline Score</div>\s*<div class='value'[^>]*>(\d+)%", text)
    assert m, "no discipline score on the page"
    assert int(m.group(1)) <= round(92 / 120 * 100)     # can't beat their own rules tag
    assert "broke your rules (your own tag)" in text
    assert "second entry in the same session" in text
    assert "Discipline: all clear" not in text
