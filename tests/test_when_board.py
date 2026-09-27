"""Round 14: "When you trade" reads as sessions and days in words on a young
journal; the thin charts wait in an expander.

    python -m pytest tests/test_when_board.py -q
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


def _journal():
    # his shape: Asia 11 (+4.0R), New York 6 (-3.2R), London 2 (+2.9R)
    r = [0.9, 0.9, -0.1, 0.1, 1.2, -1.0, 0.1, 0.5, 0.3, 1.1, 0.1] + [-1.0, -1.0, 0.1, -1.0, -0.4, 0.1] + [1.5, 1.4]
    sess = ["Asia"] * 11 + ["New York"] * 6 + ["London"] * 2
    day = (["Mon", "Tue", "Wed", "Fri"] * 5)[:19]
    r = np.round(np.asarray(r), 2)
    return pd.DataFrame({"Session Norm": sess, "Day": day, "Closed RR": r,
                         "Outcome": np.where(r > 0.15, "Win", np.where(r < -0.15, "Loss", "BE"))})


def _html(monkeypatch, **k):
    out = []
    monkeypatch.setattr(rx.st, "markdown", lambda body, **kw: out.append(body))
    return rx.when_board(_journal(), **k), " ".join(out)


def test_sessions_and_days_as_rows_with_one_sentence(monkeypatch):
    drew, html = _html(monkeypatch)
    assert drew and "By session: <b>Asia</b> leads at" in html and "<b>New York</b> costs" in html
    assert "By day:" in html and html.count('class="ea-pl-row') == 3 + 4
    assert html.count("Best first.") == 1                      # one caption under the last list
    assert "early read" in html


def test_members_see_counts_not_untested_claims(monkeypatch):
    drew, html = _html(monkeypatch, verdicts=False)
    assert drew and "leads at" not in html and "costs" not in html


def test_setups_grid_owns_sessions_and_rich_grid_owns_days(monkeypatch):
    drew, html = _html(monkeypatch, sessions=False, days=False)
    assert not drew and html == ""
    drew, html = _html(monkeypatch, sessions=False)
    assert drew and "Asia" not in html and "Tue" in html
