"""SEC-01: the device keeps a sealed blob, never the Notion token.

    python -m pytest tests/test_seal.py -q
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "src"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from streamlit.testing.v1 import AppTest  # noqa: E402

from edge_analysis.core import seal as sl  # noqa: E402

TOKEN = "ntn_" + "x" * 40


def test_round_trip_and_nothing_readable():
    box = sl.sealer(["client-secret"])
    blob = sl.seal(TOKEN, box)
    assert blob.startswith(sl.PREFIX) and TOKEN not in blob and "ntn_" not in blob
    assert sl.unseal(blob, box) == TOKEN


def test_foreign_edited_and_expired_blobs_do_not_open():
    box = sl.sealer(["client-secret"])
    blob = sl.seal(TOKEN, box)
    assert sl.unseal(blob, sl.sealer(["another-app"])) is None          # stolen to another server
    flipped = blob[:-6] + ("A" if blob[-6] != "A" else "B") + blob[-5:]
    assert sl.unseal(flipped, box) is None                               # edited
    old = sl.PREFIX + box.encrypt_at_time(TOKEN.encode(), int(time.time()) - 61 * 86400).decode()
    assert sl.unseal(old, box) is None                                   # past MAX_AGE_DAYS
    assert sl.unseal(TOKEN, box) is None                                 # a plain token isn't a blob
    assert sl.unseal("v1.garbage", box) is None


def test_adding_a_seal_key_later_signs_nobody_out():
    before = sl.seal(TOKEN, sl.sealer([None, "client-secret"]))
    after = sl.sealer(["new-seal-key", "client-secret"])
    assert sl.unseal(before, after) == TOKEN
    assert sl.unseal(sl.seal(TOKEN, after), sl.sealer(["client-secret"])) is None  # new blobs use the new key


def test_no_secret_means_no_token_on_the_device():
    assert sl.sealer([None, ""]) is None
    assert sl.seal(TOKEN, None) is None and sl.unseal("v1.x", None) is None


_APP = """
import sys, json
sys.path.insert(0, {root!r}); sys.path.insert(0, {src!r})
sys.modules.pop("app", None)
import app, streamlit as st
calls = []
app._js_eval = lambda expr, key: calls.append(expr) or True
st.session_state[app.SessionKeys.USER_TOKEN] = {tok!r}
st.session_state[app.SessionKeys.DB_ID] = "db1"
app._sync_device_auth()
st.session_state["js"] = calls[-1] if calls else ""
box = app._seal_box()
from edge_analysis.core.seal import seal
st.session_state["legacy"] = app._device_token({{"t": {tok!r}, "d": "db1"}})
st.session_state["sealed"] = app._device_token({{"s": seal({tok!r}, box), "d": "db1"}})
st.session_state["junk"] = app._device_token({{"s": "v1.junk"}})
"""


def _run(secret: str | None):
    at = AppTest.from_string(_APP.format(root=str(ROOT), src=str(ROOT / "src"), tok=TOKEN),
                             default_timeout=120)
    if secret:
        at.secrets["NOTION_OAUTH_CLIENT_SECRET"] = secret
    at.run()
    assert not at.exception, at.exception
    return at


def test_device_save_writes_only_a_sealed_blob_and_replaces_the_old_token():
    at = _run("oauth-client-secret")
    js = at.session_state["js"]
    assert TOKEN not in js                        # the token itself never reaches the browser
    assert 's:"v1.' in js and "t:" not in js      # a fresh object: any old plain token is dropped
    assert at.session_state["legacy"] == TOKEN    # old devices still sign in once (no lockout)
    assert at.session_state["sealed"] == TOKEN
    assert at.session_state["junk"] is None


def test_without_a_server_secret_the_device_keeps_only_the_journal():
    at = _run(None)
    js = at.session_state["js"]
    assert TOKEN not in js and "s:" not in js and "d:" in js


_RESTORE = """
import sys, json
sys.path.insert(0, {root!r}); sys.path.insert(0, {src!r})
sys.modules.pop("app", None)
import app, streamlit as st
from edge_analysis.core.seal import seal
got = []
app._complete_login_with_token = lambda t: got.append(t)
box = app._seal_box()
out = {{}}
for name, rec in (("sealed", {{"s": seal({tok!r}, box), "d": ""}}),
                  ("legacy", {{"t": {tok!r}, "d": ""}}),
                  ("foreign", {{"s": seal({tok!r}, __import__("edge_analysis.core.seal", fromlist=["x"]).sealer(["other"])), "d": ""}}),
                  ("empty", {{}})):
    app._js_eval = lambda expr, key, rec=rec: json.dumps(rec)
    got.clear()
    out[name] = [app._restore_device_auth(), list(got)]
st.session_state["out"] = out
"""


def test_restore_signs_in_from_sealed_and_old_devices_and_refuses_foreign_blobs():
    at = AppTest.from_string(_RESTORE.format(root=str(ROOT), src=str(ROOT / "src"), tok=TOKEN),
                             default_timeout=120)
    at.secrets["NOTION_OAUTH_CLIENT_SECRET"] = "oauth-client-secret"
    at.run()
    assert not at.exception, at.exception
    out = at.session_state["out"]
    assert out["sealed"] == [True, [TOKEN]]
    assert out["legacy"] == [True, [TOKEN]]        # no lockout for devices saved before SEC-01
    assert out["foreign"] == [False, []]           # a blob sealed by another server is just a sign-in page
    assert out["empty"] == [False, []]
