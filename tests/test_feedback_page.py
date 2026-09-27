"""His note, 27 Sep: "It won't let me type in the Tell us ... I like to copy
images and paste them ... Also needs to work on iPhone too."

    python -m pytest tests/test_feedback_page.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "src"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from streamlit.testing.v1 import AppTest  # noqa: E402

from edge_analysis.ui import feedback_page as fp  # noqa: E402

_APP = """
import sys, os
sys.path.insert(0, {root!r}); sys.path.insert(0, {src!r})
os.environ["EA_FEEDBACK_DIR"] = {box!r}
import streamlit as st
from edge_analysis.ui.feedback_page import render_feedback_page
render_feedback_page(is_owner=False, mobile={mobile!r})
"""


def _run(tmp_path, mobile=False):
    at = AppTest.from_string(_APP.format(root=str(ROOT), src=str(ROOT / "src"),
                                         box=str(tmp_path), mobile=mobile), default_timeout=60)
    at.run()
    assert not at.exception, at.exception
    return at


def test_the_text_box_keeps_one_identity_whatever_the_kind():
    # the hint used to change with the kind, which gave the box a new identity
    # and Streamlit drew a fresh, empty one: picking "Broken" wiped his note
    assert isinstance(fp._PLACEHOLDER, str)


def test_everything_is_inside_the_form_so_nothing_reruns_while_typing(tmp_path):
    at = _run(tmp_path)
    ta = at.text_area(key="ea_fb_text")
    assert ta.label == "Tell us" and ta.placeholder == fp._PLACEHOLDER
    form = at.get("form")[0]
    keys = {getattr(w, "key", None) for w in form.children.values()}
    assert {"ea_fb_text", "ea_fb_area"} <= keys
    md = " ".join(m.value for m in at.markdown)
    assert 'class="ea-fb-pastebtn"' in md and "Ctrl+V" in md


def test_phone_gets_the_iphone_steps(tmp_path):
    md = " ".join(m.value for m in _run(tmp_path, mobile=True).markdown)
    assert "Share → Copy" in md and "Ctrl+V" not in md


def test_the_paste_script_uses_the_forms_own_file_box():
    js = fp._PASTE_PAGE_JS
    assert "clipboard.read()" in js and "'paste'" in js
    assert 'stFileUploader"] input[type="file"]' in js      # same path as Browse files
    assert "image/jpeg" in js and "4.5 * 1024 * 1024" in js   # big retina shots fit the 5 MB cap
    assert "</script>" not in js
