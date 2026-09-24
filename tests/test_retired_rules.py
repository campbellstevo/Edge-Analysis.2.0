"""The app enforces no retired rule (roadmap 1.5–1.7; the pre-push pack's
"retired-string grep = 0"). Window rules are gone on purpose — the trader
runs without windows while the data decides where they belong — and the app
ships no rules of its own for members.

    python -m pytest tests/test_retired_rules.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "src", ROOT / "tests"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from streamlit.testing.v1 import AppTest  # noqa: E402

RETIRED = [
    "never Asia",                      # COMP-03 Plan fallback
    "Window Compliance",               # COMP-01
    "Window compliance by week",       # COMP-01
    "inside the 2h session window",    # COMP-01 caption
    "Dead \\u00b7 Asia",               # COMP-10 tier label (source form)
    "Dead · Asia",
    "dead (Asia)",                     # the coach's copy of the tier
    "your session rule in one number", # TZ-13
    "Asia is overweight",              # COMP-02
    "lower-quality session",           # COMP-02
    "Stop for the week at",            # COMP-17 constant rule
    "is over after a loss",            # STAT-09
    "[17, 18, 19, 20, 21, 22, 23, 0, 1, 2]",  # the retired 17:00–02:00 window
    "5M entries only",                 # Plan fallback
    "next 3SL window",
]
SOURCES = [ROOT / "app.py", ROOT / "filters.py", ROOT / "data_loading.py",
           *sorted((ROOT / "src" / "edge_analysis").rglob("*.py"))]


@pytest.mark.parametrize("phrase", RETIRED)
def test_retired_phrase_is_gone_from_the_code(phrase):
    hits = [f"{p.relative_to(ROOT)}" for p in SOURCES
            if phrase in p.read_text(encoding="utf-8")]
    assert hits == [], f"{phrase!r} still in {hits}"


def test_demo_psychology_scores_no_window():
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=180)
    at.query_params["demo"] = "1"
    at.run()
    at.session_state["ea_tab"] = "Psychology"
    at.session_state["ea_nav_external"] = True
    at.run()
    assert not at.exception
    text = " ".join(str(m.value) for m in at.markdown).lower()
    assert "window compliance" not in text
    assert "one trade per session" in text
