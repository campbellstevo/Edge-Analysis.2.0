"""The launch access switch (src/edge_analysis/access.py) and its wiring.

    python -m pytest tests/test_access.py -q
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

from edge_analysis import access  # noqa: E402

OWNER = "owner@example.com"
STRANGER = "stranger@example.com"


# ── the decision table ────────────────────────────────────────────────────────
@pytest.mark.parametrize("mode,allow,email,expect", [
    ("owner", set(), OWNER, (True, "owner")),
    ("owner", set(), STRANGER, (False, "not_open")),
    ("allowlist", {STRANGER}, STRANGER, (True, "allowed")),
    ("allowlist", set(), STRANGER, (False, "not_open")),
    ("open", set(), STRANGER, (True, "open")),
    ("paused", {STRANGER}, STRANGER, (False, "paused")),
    ("paused", set(), OWNER, (True, "owner")),
])
def test_decide(mode, allow, email, expect):
    assert access.decide(mode, {OWNER}, allow, set(), email) == expect


def test_no_owner_configured_admits_nobody_except_open():
    assert access.decide("owner", set(), set(), {"u1"}, STRANGER) == (False, "no_owner")
    assert access.decide("open", set(), set(), {"u1"}, STRANGER) == (True, "open")


def test_owner_may_be_named_by_notion_user_id():
    assert access.decide("owner", {"abc-123"}, set(), {"abc-123"}, "") == (True, "owner")


def test_email_match_is_case_insensitive():
    assert access.decide("allowlist", {OWNER}, {"Stranger@Example.com".lower()}, set(),
                         "STRANGER@example.com")[0]


def test_unset_or_unknown_mode_is_owner_only(monkeypatch):
    monkeypatch.delenv("EA_ACCESS", raising=False)
    assert access.mode() == "owner"
    monkeypatch.setenv("EA_ACCESS", "wide-open-please")
    assert access.mode() == "owner"
    monkeypatch.setenv("EA_ACCESS", "Allow-List")
    assert access.mode() == "allowlist"


def test_owner_falls_back_to_whoop_owner(monkeypatch):
    monkeypatch.delenv("EA_OWNER", raising=False)
    monkeypatch.setenv("WHOOP_OWNER", "Owner@Example.com")
    assert access.owners() == {OWNER}


def test_identity_of_an_oauth_bot_is_its_owner():
    me = {"object": "user", "id": "bot-1", "type": "bot", "name": "Edge Analysis",
          "bot": {"owner": {"type": "user", "user": {
              "id": "person-9", "type": "person", "person": {"email": "Owner@Example.com"}}}}}
    ids, email = access.notion_identity(me)
    assert ids == {"bot-1", "person-9"}
    assert email == OWNER


def test_identity_of_a_person():
    ids, email = access.notion_identity({"id": "p1", "person": {"email": OWNER}})
    assert (ids, email) == ({"p1"}, OWNER)
    assert access.notion_identity(None) == (set(), "")


# ── sign-in: a refused visitor leaves nothing behind ─────────────────────────
_LOGIN_SCRIPT = """
import sys
sys.path.insert(0, {root!r}); sys.path.insert(0, {src!r})
sys.modules.pop("app", None)
import app
app._complete_login_with_token("tok-under-test", workspace_name="ws")
"""


def _login_as(monkeypatch, email, secrets):
    import requests
    from edge_analysis import user_store

    calls = []
    monkeypatch.setattr(user_store, "upsert_user", lambda uid, **kw: calls.append((uid, kw)) or {})
    monkeypatch.setattr(user_store, "get_user", lambda uid: None)

    class _Resp:
        status_code = 200

        def json(self):
            return {"object": "user", "id": "bot-" + email, "type": "bot",
                    "bot": {"owner": {"type": "user", "user": {
                        "id": "person-" + email, "person": {"email": email}}}}}

    monkeypatch.setattr(requests, "get", lambda *a, **k: _Resp())
    at = AppTest.from_string(_LOGIN_SCRIPT.format(root=str(ROOT), src=str(ROOT / "src")),
                             default_timeout=120)
    for k, v in secrets.items():
        at.secrets[k] = v
    at.run()
    assert not at.exception, at.exception
    return at, calls


def test_stranger_is_refused_and_nothing_is_stored(monkeypatch):
    at, calls = _login_as(monkeypatch, STRANGER, {"EA_OWNER": OWNER})
    assert at.session_state["ea_denied"]["why"] == "not_open"
    assert "user_notion_token" not in at.session_state
    assert "override_NOTION_TOKEN" not in at.session_state
    assert calls == []


def test_paused_refuses_even_an_allowlisted_member(monkeypatch):
    at, calls = _login_as(monkeypatch, STRANGER, {
        "EA_OWNER": OWNER, "EA_ACCESS": "paused", "EA_ALLOW": STRANGER})
    assert at.session_state["ea_denied"]["why"] == "paused"
    assert calls == []


def test_allowlisted_member_is_admitted_without_name_or_email_stored(monkeypatch):
    at, calls = _login_as(monkeypatch, STRANGER, {
        "EA_OWNER": OWNER, "EA_ACCESS": "allowlist", "EA_ALLOW": STRANGER})
    assert at.session_state["user_notion_token"] == "tok-under-test"
    assert calls and "name" not in calls[0][1] and "email" not in calls[0][1]


def test_owner_is_admitted_by_the_bot_owners_email(monkeypatch):
    at, _ = _login_as(monkeypatch, OWNER, {"EA_OWNER": OWNER})
    assert at.session_state["user_notion_token"] == "tok-under-test"
    assert at.session_state["ea_user_email"] == OWNER


# ── every run: a signed-in session is re-checked against the live switch ─────
def _signed_in_app(uid):
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=180)
    at.session_state["user_notion_token"] = "test-" + uuid.uuid4().hex
    at.session_state["user_id"] = uid
    at.session_state["ea_user_email"] = ""
    return at


def _page_text(at) -> str:
    return " ".join(str(m.value) for m in at.markdown)


def test_pausing_locks_out_a_signed_in_member():
    at = _signed_in_app("member-1")
    at.secrets["EA_OWNER"] = OWNER
    at.secrets["EA_ACCESS"] = "open"
    at.run()
    assert "paused for a moment" not in _page_text(at)
    at.secrets["EA_ACCESS"] = "paused"
    at.run()
    assert "paused for a moment" in _page_text(at)
    assert not [r for r in at.radio if r.key == "ea_tab"]


def test_owner_passes_while_paused():
    at = _signed_in_app("owner-uid")
    at.secrets["EA_OWNER"] = "owner-uid"
    at.secrets["EA_ACCESS"] = "paused"
    at.run()
    assert "paused for a moment" not in _page_text(at)
    assert not at.exception


# ── SEC-06: a token in the URL is never a login ──────────────────────────────
def test_url_token_does_not_sign_in_and_is_stripped():
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=180)
    at.query_params["notion_token"] = "abc"
    at.query_params["database_id"] = "0" * 32
    at.run()
    assert not at.exception, at.exception
    assert "user_notion_token" not in at.session_state
    assert "override_NOTION_TOKEN" not in at.session_state
    assert "notion_token" not in at.query_params
    assert "database_id" not in at.query_params


def test_url_params_are_not_runtime_secrets():
    src = (ROOT / "app.py").read_text(encoding="utf-8")
    assert '_get_query_param("notion_token")' not in src
    assert '_get_query_param("database_id")' not in src


def test_phone_sign_in_never_puts_a_token_in_a_link():
    src = (ROOT / "filters.py").read_text(encoding="utf-8")
    assert '"notion_token"' not in src
    assert "st.code(url" not in src
