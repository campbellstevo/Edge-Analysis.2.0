"""Round 20: the session lock, the tilt check and session balance each say
their fact once.

    python -m pytest tests/test_where_you_lose.py -q
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

from edge_analysis.ui import pro_tabs as P  # noqa: E402
from edge_analysis.ui import tabs as T  # noqa: E402


def _cap(monkeypatch, *mods):
    out = []
    for m in mods:
        monkeypatch.setattr(m.st, "markdown", lambda body, **k: out.append(body))
        monkeypatch.setattr(m.st, "caption", lambda body, **k: out.append(body))
    return out


def _journal(r, sess=None):
    r = np.round(np.asarray(r, dtype=float), 2)
    return pd.DataFrame({
        "Date": pd.date_range("2026-08-01 10:00", periods=len(r), freq="7h"),
        "Closed RR": r, "Outcome": np.where(r > 0.15, "Win", np.where(r < -0.15, "Loss", "BE")),
        "Session": sess if sess is not None else ["Asia"] * len(r)})


def test_tilt_is_one_sentence_and_never_praises_a_handful(monkeypatch):
    out = _cap(monkeypatch, P, T)
    P._tilt(_journal([1, -1, 0.8, -1, -1, 1.2, -1, 0.5, 1, -1, 0.2]), lambda c: c)
    html = " ".join(out)
    assert "After a loss, your next trade averaged" in html and "Too few trades" in html
    assert "emotional control" not in html and "QUICK RE-ENTRIES" not in html


def test_session_lock_is_one_line_pointing_at_the_score(monkeypatch):
    out = _cap(monkeypatch, T)
    df = _journal([1, -1, 0.5, -1], sess=["Asia", "Asia", "London", "London"])
    df["Date"] = pd.to_datetime(["2026-09-01 01:00", "2026-09-01 03:00", "2026-09-02 09:00", "2026-09-03 09:00"])
    T._psych_3sl_compliance(df, lambda c: c)
    html = " ".join(out)
    assert "1 second entry</b> went into a session you'd already traded, on 1 day (Asia ×1)" in html
    assert "counted in the score above" in html and "class='kpi'" not in html


def test_session_balance_is_silent_unless_overweight(monkeypatch):
    out = _cap(monkeypatch, T)
    rng = np.random.default_rng(1)
    df = _journal(rng.normal(0.2, 1, 30), sess=["Asia"] * 10 + ["London"] * 10 + ["New York"] * 10)
    T._psych_session_alert(df, lambda c: c)
    assert not any("Session balance" in x for x in out)
