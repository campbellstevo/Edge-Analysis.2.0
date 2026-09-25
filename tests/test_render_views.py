"""Every view renders, headless, on the build about to be pushed.

Runs the real app.py through streamlit.testing.AppTest on the pinned
Streamlit, twice:
  * the demo (?demo=1) — what a visitor sees before connecting;
  * a member on Salty's TradingPool template — Notion is faked with
    tests/salty_fixture.py, so the real loader and adapter run.

A view "renders" when the script raised nothing and the page shows no
"Something broke" error box. This is the check that would have caught the
st.popover(key=...) crash before it shipped.

    python -m pytest tests/test_render_views.py -q
"""
from __future__ import annotations

import sys
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "src", ROOT / "tests"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from streamlit.testing.v1 import AppTest  # noqa: E402

VIEWS = ["Performance", "Entry", "Externals", "Psychology", "Plan", "Review"]
TIMEOUT = 180


def _problems(at) -> list:
    out = [f"exception: {e.value}" for e in at.exception]
    for el in at.error:
        body = str(getattr(el, "value", "") or "")
        if "Something broke" in body or "Traceback" in body:
            out.append(f"error box: {body[:160]}")
    return out


def _walk_views(at) -> dict:
    """Render each view in turn; return {view: [problems]} for the failures."""
    bad = {}
    for view in VIEWS:
        at.session_state["ea_tab"] = view
        at.session_state["ea_nav_external"] = True
        at.run(timeout=TIMEOUT)
        probs = _problems(at)
        if probs:
            bad[view] = probs
    return bad


def _boot(at):
    at.run(timeout=TIMEOUT)
    at.run(timeout=TIMEOUT)  # second pass: the app reruns once after boot
    return at


def test_demo_renders_all_six_views():
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=TIMEOUT)
    at.query_params["demo"] = "1"
    _boot(at)
    assert not _problems(at), _problems(at)
    assert _walk_views(at) == {}


def test_focus_mode_renders_where_verdicts_are_on():
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=TIMEOUT)
    at.query_params["demo"] = "1"
    at.secrets["EA_VERDICTS"] = "all"
    at.session_state["ea_density_pref"] = "Focus"
    _boot(at)
    assert not _problems(at), _problems(at)
    assert at.session_state["ea_density_pref"] == "Focus"
    assert [r for r in at.radio if r.label == "Density"]


def test_focus_is_not_offered_without_verdicts():
    # Focus without the verdict layer is one card: members and the demo get
    # Everything, and a stored Focus pref falls back instead of trapping them.
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=TIMEOUT)
    at.query_params["demo"] = "1"
    at.session_state["ea_density_pref"] = "Focus"
    _boot(at)
    assert not _problems(at), _problems(at)
    assert at.session_state["ea_density_pref"] == "All"
    assert not [r for r in at.radio if r.label == "Density"]


@pytest.fixture
def salty_member(monkeypatch):
    import salty_fixture
    from edge_analysis.data import notion_adapter

    salty_fixture.FakeNotionClient.pages = salty_fixture.salty_pages()
    monkeypatch.setattr(notion_adapter, "Client", salty_fixture.FakeNotionClient)
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=TIMEOUT)
    # a unique fake token per run: the journal cache is keyed on it
    at.session_state["user_notion_token"] = "test-" + uuid.uuid4().hex
    at.session_state["override_DATABASE_ID"] = uuid.uuid4().hex
    at.session_state["user_id"] = "member-" + uuid.uuid4().hex[:8]
    at.secrets["EA_ACCESS"] = "open"  # a member, not the owner
    return at


def test_salty_member_renders_all_six_views(salty_member):
    at = _boot(salty_member)
    assert at.session_state["detected_schema"] == "salty"
    assert not _problems(at), _problems(at)
    assert _walk_views(at) == {}
