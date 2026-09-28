"""M7 (his yes, 27 Sep): the book in view is always on screen, and a tap
switches it without opening Filters.

    python -m pytest tests/test_book_chip.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "src"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from streamlit.testing.v1 import AppTest  # noqa: E402

_APP = """
import sys, datetime as dt
sys.path.insert(0, {root!r}); sys.path.insert(0, {src!r})
import streamlit as st
import filters
st.session_state.setdefault("ea_tot_default", "Live money")
sync = ("", "<div class='ea-sync' title='Live · synced just now'><span class='ea-sync-dot' "
            "style='background:#16a34a;'></span><span class='ea-sync-t'>Synced just now</span></div>")
out = filters.render_filters({mobile!r}, ["All"], ["All"], ["All"], ["All"], dt.date(2026, 8, 1),
                             dt.date(2026, 9, 27), acct_opts=None, tot_opts={tot!r}, brand=sync)
st.session_state["out_tot"] = st.session_state.get("filters_tot_select")
"""


def _run(tot, mobile=False):
    at = AppTest.from_string(_APP.format(root=str(ROOT), src=str(ROOT / "src"), tot=tot, mobile=mobile),
                             default_timeout=60)
    at.run()
    assert not at.exception, at.exception
    return at


def test_live_and_challenge_journal_gets_the_chip_and_it_switches():
    at = _run(["Live money", "All", "Live", "Challenge"])
    md = " ".join(m.value for m in at.markdown)
    assert 'class="ea-mk ea-bs ea-bk' in md and "<span class='ea-sync-t'>" not in md   # chip replaces the sync line
    book = at.radio(key="ea_book_pick")
    assert list(book.options) == ["Live money", "Challenge", "Everything"]   # "Live" folds into Live money
    assert book.value == "Live money"
    book.set_value("Challenge").run()
    assert at.session_state["filters_tot_select"] == "Challenge"
    assert not [w for w in at.warning if "Session State" in w.value]


def test_one_book_keeps_the_sync_line():
    md = " ".join(m.value for m in _run(["All", "Live"]).markdown)
    assert 'ea-bs ea-bk' not in md and "<span class='ea-sync-t'>" in md


def test_phone_gets_the_chip_too():
    md = " ".join(m.value for m in _run(["Live money", "All", "Live", "Challenge"], mobile=True).markdown)
    assert "ea-ps ea-bk" in md


def test_the_book_decides_the_full_history_too():
    # 28 Sep (rule 8): with Challenge picked, the month cards and Projections
    # read the whole journal and fell back to the live account's months
    import pandas as pd
    from filters import book_mask
    df = pd.DataFrame({"Type of Trade": ["['Live']", "['Live']", "['Challenge']", "['Back Test']"]})
    assert list(book_mask(df, "Challenge")) == [False, False, True, False]
    assert list(book_mask(df, "Live money")) == [True, True, False, False]
    assert list(book_mask(df, "Executed")) == [True, True, True, False]
    assert book_mask(df, "All") is None and book_mask(df.drop(columns="Type of Trade"), "Challenge") is None
    src = (ROOT / "app.py").read_text(encoding="utf-8")
    assert "_df_hist = df[_paper_mask].copy() if _paper_mask is not None else df" in src
    assert "_paper_mask = book_mask(df, sel_tot)" in src
