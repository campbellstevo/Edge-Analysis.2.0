"""What the server keeps, and that Disconnect deletes it (SEC-07, SEC-09,
DATA-19), and that the paid chat fails closed (1.14).

    python -m pytest tests/test_privacy.py -q
"""
from __future__ import annotations

import os
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "src", ROOT / "tests"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from streamlit.testing.v1 import AppTest  # noqa: E402


def test_store_keeps_no_name_or_email(monkeypatch, tmp_path):
    from edge_analysis import user_store
    monkeypatch.setattr(user_store, "_STORE_FILE", tmp_path / "store.json")
    monkeypatch.setattr(user_store, "_mirror_cfg", lambda: (None, None))
    user_store.upsert_user("u1", name="Old Name", email="old@example.com", db_id="d1")
    rec = user_store.get_user("u1")
    assert rec["db_id"] == "d1"
    assert "name" not in rec and "email" not in rec


def test_store_purges_legacy_name_and_email_on_next_save(monkeypatch, tmp_path):
    import json
    from edge_analysis import user_store
    f = tmp_path / "store.json"
    f.write_text(json.dumps({"version": 1, "users": {
        "old": {"name": "N", "email": "e@x.com", "db_id": "d"}}}))
    monkeypatch.setattr(user_store, "_STORE_FILE", f)
    monkeypatch.setattr(user_store, "_mirror_cfg", lambda: (None, None))
    user_store.set_user_db("someone-else", "d2")
    old = json.loads(f.read_text())["users"]["old"]
    assert old == {"db_id": "d"}


def test_forget_journal_cache_deletes_the_disk_copy(monkeypatch, tmp_path):
    import data_loading
    target = tmp_path / "copy.parquet"
    target.write_text("x")
    monkeypatch.setattr(data_loading, "_pq_path", lambda t, d: str(target))
    data_loading.forget_journal_cache("tok", "db")
    assert not target.exists()


def test_sweep_deletes_only_copies_older_than_a_day():
    import data_loading
    old = Path(f"/tmp/ea_journal_test{uuid.uuid4().hex[:8]}.parquet")
    new = Path(f"/tmp/ea_journal_test{uuid.uuid4().hex[:8]}.parquet")
    for f in (old, new):
        f.write_text("x")
    stale = time.time() - data_loading._PQ_MAX_AGE_S - 60
    os.utime(old, (stale, stale))
    try:
        data_loading._sweep_old_journal_copies()
        assert not old.exists()
        assert new.exists()
    finally:
        for f in (old, new):
            if f.exists():
                f.unlink()


_DISCONNECT = """
import sys
sys.path.insert(0, {root!r}); sys.path.insert(0, {src!r})
sys.modules.pop("app", None)
import streamlit as st
st.session_state["user_id"] = "member-7"
st.session_state["user_notion_token"] = "tok-7"
st.session_state["override_DATABASE_ID"] = "db-7"
import app
app._forget_this_user()
"""


def test_disconnect_deletes_record_cache_and_session(monkeypatch):
    from edge_analysis import user_store
    import data_loading
    deleted, forgotten = [], []
    monkeypatch.setattr(user_store, "delete_user", lambda uid: deleted.append(uid))
    monkeypatch.setattr(data_loading, "forget_journal_cache", lambda t, d: forgotten.append((t, d)))
    at = AppTest.from_string(_DISCONNECT.format(root=str(ROOT), src=str(ROOT / "src")),
                             default_timeout=120)
    at.run()
    assert not at.exception, at.exception
    assert deleted == ["member-7"]
    assert forgotten == [("tok-7", "db-7")]
    for k in ("user_id", "user_notion_token", "override_DATABASE_ID"):
        assert k not in at.session_state


def test_chat_cap_fails_closed(monkeypatch):
    import streamlit as st
    from edge_analysis import user_store
    from edge_analysis.ui import chat

    def boom(*a, **k):
        raise RuntimeError("store down")
    monkeypatch.setattr(user_store, "bump_llm_use", boom)
    monkeypatch.setattr(st, "session_state", {"user_id": "u"})
    assert chat._llm_allowed() is False


def test_paid_chat_is_offered_to_the_owner_only():
    src = (ROOT / "app.py").read_text(encoding="utf-8")
    assert "render_chat_bubble(f, llm_for_this_user=_session_is_owner())" in src


# ── 1.11: privacy on (the default) shows no dollar figure on any view ────────
def test_privacy_on_shows_no_dollar_figure_anywhere():
    import re
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=180)
    at.query_params["demo"] = "1"
    at.run()
    assert at.session_state["ea_privacy"] is True  # the default
    leaks = {}
    for view in ["Performance", "Entry", "Externals", "Psychology", "Plan", "Review"]:
        at.session_state["ea_tab"] = view
        at.session_state["ea_nav_external"] = True
        at.run()
        assert not at.exception, at.exception
        texts = [str(m.value) for m in at.markdown] + [str(c.value) for c in at.caption]
        found = [m.group(0) for t in texts for m in re.finditer(r"-?\$\s?\d[\d,.]*", t)]
        if found:
            leaks[view] = found[:5]
    assert leaks == {}, leaks
