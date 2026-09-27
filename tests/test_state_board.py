"""Round 13: mental state, in the journal's own words.

    python -m pytest tests/test_state_board.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "src"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from edge_analysis.ui import reshape as rx  # noqa: E402


def _journal(states, rs):
    rs = np.round(np.asarray(rs, dtype=float), 2)
    return pd.DataFrame({"Mental State": states, "Closed RR": rs,
                         "Outcome": np.where(rs > 0.15, "Win", np.where(rs < -0.15, "Loss", "BE"))})


def _html(monkeypatch, df, **k):
    out = []
    monkeypatch.setattr(rx.st, "markdown", lambda body, **kw: out.append(body))
    drew = rx.state_board(df, **k)
    return drew, " ".join(out)


def test_his_shape_is_one_honest_line(monkeypatch):
    # 12 Clear & Calm, 1 Fatigued, 6 blank: nothing to compare, and it says so
    df = _journal(["Clear & Calm"] * 12 + ["Fatigued & Hesitant"] + [None] * 6,
                  [0.5] * 12 + [-1.0] + [0.1] * 6)
    drew, html = _html(monkeypatch, df)
    assert drew and "<b>12 of 13</b> tagged trades were <b>Clear &amp; Calm</b>" in html
    assert "Fatigued &amp; Hesitant</b>, 1 trade at" in html and "nothing to compare" in html
    assert "6 trades have no state logged" in html and "ea-pl-row" not in html


def test_real_variety_gets_ranked_rows(monkeypatch):
    rng = np.random.default_rng(4)
    df = _journal(["Clear & Calm"] * 20 + ["Stressed & Impulsive"] * 8,
                  np.concatenate([rng.normal(0.4, 0.8, 20), rng.normal(-0.6, 0.8, 8)]))
    drew, html = _html(monkeypatch, df)
    assert drew and html.count('class="ea-pl-row') == 2
    assert html.index("Clear &amp; Calm") < html.index("Stressed &amp; Impulsive")    # best first
    assert "early read" in html or "beats chance" in html


def test_members_get_no_untested_claim(monkeypatch):
    df = _journal(["Good"] * 4 + ["Bad"] * 4, [1, 1, 1, -1, -1, -1, 1, -1])
    drew, html = _html(monkeypatch, df, verdicts=False)
    assert drew and "average" not in html.split("ea-pl-head")[1].split("</div>")[0]


def test_too_few_states_draws_nothing(monkeypatch):
    drew, html = _html(monkeypatch, _journal(["Clear & Calm", None, None], [1, 1, 1]))
    assert not drew and html == ""


def test_a_plus_reads_as_words_not_yes_no(monkeypatch):
    # his live shape: 11 A+ (+5.6R), 2 not (-2.5R), 6 untagged
    from edge_analysis.ui import tabs as T
    df = _journal(["Yes"] * 11 + ["No"] * 2 + [None] * 6,
                  [0.5] * 11 + [-1.25, -1.25] + [0.0] * 6).rename(columns={"Mental State": "A+ Setup?"})
    out = []
    monkeypatch.setattr(rx.st, "markdown", lambda body, **kw: out.append(body))
    assert rx.state_board(df, "A+ Setup?", title="A+ setups", relabel=T._AP_WORDS, noun="answer")
    html = " ".join(out)
    assert "### A+ setups" in html and "<b>11 of 13</b> tagged trades were <b>A+ setup</b>" in html
    assert "<b>Not A+</b>, 2 trades at" in html and "No other answer has 3" in html
    assert "6 trades have no answer logged" in html and ">Yes<" not in html
