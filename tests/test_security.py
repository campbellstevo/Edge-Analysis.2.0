"""Journal text can't become markup (SEC-10); the OAuth verifier store
expires (SEC-08).

    python -m pytest tests/test_security.py -q
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

EVIL = '<img src=x onerror="alert(1)">'
EVIL_STYLE = "<style>body{display:none}</style>"


def test_neutralise_markup_breaks_tags_but_keeps_ordinary_text():
    import data_loading as dl
    df = pd.DataFrame({"Entry Model": [EVIL, "FBoS", "<30m", ">2hs"],
                       "Entry Models List": [[EVIL], ["FBoS"], [], []],
                       "<b>col": [1, 2, 3, 4]})
    out = dl._neutralise_markup(df)
    assert "<img" not in out["Entry Model"][0]
    assert out["Entry Model"].tolist()[1:] == ["FBoS", "<30m", ">2hs"]
    assert "<img" not in out["Entry Models List"][0][0]
    assert not any(str(c).startswith("<b") for c in out.columns)


@pytest.fixture
def poisoned_member(monkeypatch):
    from edge_analysis.data import notion_adapter as na
    pages = salty_fixture.salty_pages()
    for p in pages[:12]:  # enough rows that every grouped view shows the value
        p["properties"]["Entry Model"] = {"type": "select", "select": {"name": EVIL}}
        p["properties"]["Emotional State Before Entry"] = {
            "type": "select", "select": {"name": EVIL_STYLE}}
    salty_fixture.FakeNotionClient.pages = pages
    monkeypatch.setattr(na, "Client", salty_fixture.FakeNotionClient)
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=180)
    at.session_state["user_notion_token"] = "test-" + uuid.uuid4().hex
    at.session_state["override_DATABASE_ID"] = uuid.uuid4().hex
    at.session_state["user_id"] = "member-" + uuid.uuid4().hex[:8]
    at.secrets["EA_ACCESS"] = "open"
    return at


def test_journal_text_never_renders_as_markup(poisoned_member):
    at = poisoned_member
    at.run()
    at.run()
    seen = []
    for view in ["Performance", "Entry", "Externals", "Psychology", "Plan", "Review"]:
        at.session_state["ea_tab"] = view
        at.session_state["ea_nav_external"] = True
        at.run()
        assert not at.exception, at.exception
        seen += [str(m.value) for m in at.markdown]
    blob = " ".join(seen)
    assert "<img src=x" not in blob
    assert "<style>body{display:none}" not in blob


# ── SEC-08: PKCE verifiers expire and the store is capped ────────────────────
_STORE = """
import sys, time
sys.path.insert(0, {root!r}); sys.path.insert(0, {src!r})
sys.modules.pop("app", None)
import app, streamlit as st
store = app._oauth_store(); store.clear()
app._oauth_put("fresh", "v1")
store["stale"] = {{"code_verifier": "v0", "ts": time.time() - 3600}}
st.session_state["stale"] = app._oauth_pop("stale")
st.session_state["fresh"] = app._oauth_pop("fresh")
for i in range(app._OAUTH_STORE_MAX + 50):
    app._oauth_put(f"s{{i}}", "v")
st.session_state["size"] = len(store)
"""


def test_oauth_verifier_store_expires_and_is_capped():
    at = AppTest.from_string(_STORE.format(root=str(ROOT), src=str(ROOT / "src")),
                             default_timeout=120)
    at.run()
    assert not at.exception, at.exception
    assert at.session_state["stale"] is None
    assert at.session_state["fresh"]["code_verifier"] == "v1"
    assert at.session_state["size"] <= 1000
