"""Salty's TradingPool template reads correctly (roadmap 1.9, 1.10).

    python -m pytest tests/test_salty_fit.py -q
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
from edge_analysis.core.parsing import normalize_session  # noqa: E402
from edge_analysis.data import notion_adapter as na  # noqa: E402


def _salty_frame():
    raw = pd.DataFrame([na._flatten_props(p["properties"]) for p in salty_fixture.salty_pages()])
    assert na.detect_schema(raw) == "salty"
    return raw, na.normalise_salty_df(raw)


def test_rules_followed_lands_where_the_app_reads_it_as_yes_no():
    raw, df = _salty_frame()
    assert "Rules Followed?" in df.columns          # DATA-10: was "Rules Followed"
    vals = set(df["Rules Followed?"].dropna())
    assert vals and vals <= {"Yes", "No"}             # was Y/N: 0 of 120 recognised


def test_every_yn_column_becomes_yes_no():
    _, df = _salty_frame()
    for col in ("Multi-Entry Model Setup", "Hit Full TP"):
        vals = set(df[col].dropna())
        assert vals and vals <= {"Yes", "No"}, (col, vals)


def test_time_of_trade_becomes_the_hour():
    raw, df = _salty_frame()
    assert "Hour (Melb)" in df.columns
    timed = raw["Time of Trade"].astype(str).str.len() > 0
    assert df.loc[timed, "Hour (Melb)"].notna().all()
    assert df.loc[~timed, "Hour (Melb)"].isna().all()   # blank stays blank
    assert df["Hour (Melb)"].dropna().nunique() >= 3    # not a synthetic 10:00/11:00


@pytest.mark.parametrize("text,hour", [("21:30", 21), ("9:30 PM", 21), ("9pm", 21),
                                       ("0930", 9), ("12:15 am", 0), ("7.30", 7),
                                       ("", None), (None, None), ("soon", None)])
def test_clock_hour(text, hour):
    assert na._clock_hour(text) == hour


def test_no_phantom_none_session():
    assert normalize_session(None) is None
    assert normalize_session("None") is None
    assert normalize_session("London") == "London"


@pytest.fixture
def salty_member(monkeypatch):
    salty_fixture.FakeNotionClient.pages = salty_fixture.salty_pages()
    monkeypatch.setattr(na, "Client", salty_fixture.FakeNotionClient)
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=180)
    at.session_state["user_notion_token"] = "test-" + uuid.uuid4().hex
    at.session_state["override_DATABASE_ID"] = uuid.uuid4().hex
    at.session_state["user_id"] = "member-" + uuid.uuid4().hex[:8]
    at.secrets["EA_ACCESS"] = "open"
    return at


def test_salty_member_sees_rules_followed_and_no_auto_log(salty_member):
    at = salty_member
    at.run()
    at.run()
    labels = [str(b.label) for b in at.button]
    assert "Auto-log my trades" not in labels          # 1.10: MT5 journals only
    at.session_state["ea_tab"] = "Psychology"
    at.session_state["ea_nav_external"] = True
    at.run()
    assert not at.exception, at.exception
    text = " ".join(str(m.value) for m in at.markdown)
    assert "Rules Followed" in text                    # the surface exists again


def test_demo_still_offers_auto_log():
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=180)
    at.query_params["demo"] = "1"
    at.run()
    assert "Auto-log my trades" in [str(b.label) for b in at.button]
