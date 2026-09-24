"""Render errors: the member sees a short message with a reference, the
owner can see the traceback, and Sentry gets the error without local
variables (roadmap 1.4).

    python -m pytest tests/test_errors.py -q
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


@pytest.fixture
def broken_views(monkeypatch):
    import sentry_sdk
    from edge_analysis.ui import tabs

    sent = {"messages": [], "exceptions": []}

    def boom(*a, **k):
        secret_in_a_local = "tok-SHOULD-NOT-LEAVE"  # noqa: F841
        raise ValueError("column 'R Result' missing")

    monkeypatch.setattr(tabs, "render_all_tabs", boom)
    monkeypatch.setattr(sentry_sdk, "capture_message",
                        lambda msg, level=None, **k: sent["messages"].append(msg))
    monkeypatch.setattr(sentry_sdk, "capture_exception",
                        lambda *a, **k: sent["exceptions"].append(a))
    monkeypatch.setenv("_EA_SENTRY_ON", "1")
    return sent


def _app(uid, owner):
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=180)
    at.query_params["demo"] = "1"
    at.secrets["EA_OWNER"] = owner
    return at


def _texts(at, kind):
    return [str(e.value) for e in getattr(at, kind)]


def test_member_sees_a_reference_not_a_traceback(broken_views):
    at = _app("member", "someone-else@example.com")
    at.run()
    at.run()
    errs = _texts(at, "error")
    assert any("couldn't be drawn" in e and "reference" in e for e in errs), errs
    assert not any("Traceback" in e for e in errs)
    assert not [x for x in at.expander if "Error details" in str(x.label)]
    assert broken_views["messages"], "nothing reached Sentry"
    assert "ValueError" in broken_views["messages"][0]
    assert broken_views["exceptions"] == []  # never the frames' locals


def test_report_error_returns_a_reference_without_sentry(monkeypatch):
    monkeypatch.delenv("_EA_SENTRY_ON", raising=False)
    script = f"""
import sys
sys.path.insert(0, {str(ROOT)!r}); sys.path.insert(0, {str(ROOT / 'src')!r})
sys.modules.pop("app", None)
import app, streamlit as st
st.session_state["ref"] = app._report_error(RuntimeError("x"), where="t")
"""
    at = AppTest.from_string(script, default_timeout=120)
    at.run()
    assert not at.exception, at.exception
    assert len(at.session_state["ref"]) == 6
