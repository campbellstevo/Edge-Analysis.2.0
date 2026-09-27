"""Members see descriptive stats; the verdicts that fire on noise are the
owner's until each passes its null test (roadmap 1.12, D4).

    python -m pytest tests/test_verdicts.py -q
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

# Prob. of Profit left this list on 27 Sep (D4): its paths now sample the
# uncertainty of the trades they come from, so it is shown to everyone.
GATED = ["What needs work", "Recommended from your data"]


def _all_text(secrets=None) -> str:
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=180)
    at.query_params["demo"] = "1"
    for k, v in (secrets or {}).items():
        at.secrets[k] = v
    at.run()
    text = []
    for view in ["Performance", "Plan", "Review"]:
        at.session_state["ea_tab"] = view
        at.session_state["ea_nav_external"] = True
        at.run()
        assert not at.exception, at.exception
        text += [str(m.value) for m in at.markdown]
    return " ".join(text)


def test_demo_visitor_sees_no_noisy_verdicts():
    text = _all_text()
    for phrase in GATED:
        assert phrase not in text, phrase


def test_ea_verdicts_all_shows_them_to_everyone():
    text = _all_text({"EA_VERDICTS": "all"})
    for phrase in ("What needs work", "Prob. of Profit"):
        assert phrase in text, phrase


def test_prob_of_profit_is_shown_and_never_certain():
    import re
    text = _all_text()
    m = re.search(r'Prob\. of Profit</div><div class="proj-stat-value">([^<]+)<', text)
    assert m, "Prob. of Profit missing for visitors"
    assert m.group(1) not in ("over 99%", "100%")
