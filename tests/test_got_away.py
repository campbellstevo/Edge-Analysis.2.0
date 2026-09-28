"""Managing the trade says what got away once (28 Sep): one block, a row per
way a trade leaks, never summed because the rows overlap.

    python -m pytest tests/test_got_away.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "src", ROOT / "tests"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from edge_analysis.ui import got_away as ga  # noqa: E402


def _journal():
    #            went +1R then BE/worse  winners closed early      the rest
    mfe = [1.5, 2.0, 1.2, 3.0, 2.5, 0.4, 0.2, 0.3, 0.1, 0.5, 0.2, 0.6]
    r = [0.0, -1.0, 0.1, 2.0, 1.0, -1.0, -1.0, 0.0, -1.0, 0.0, -1.0, 0.2]
    return pd.DataFrame({"MFE (R)": mfe, "Closed RR": r, "Planned R:R": [3.0] * 12,
                         "Hit Full TP Without You": ["Yes", "Yes", "No"] + ["No"] * 9})


def test_each_leak_once_biggest_first():
    rows = ga.leaks(_journal())
    keys = [r["key"] for r in rows]
    assert len(keys) == len(set(keys))
    assert [r["r"] for r in rows] == sorted((r["r"] for r in rows), reverse=True)
    gave = next(r for r in rows if r["key"] == "gave")
    assert gave["n"] == 3 and round(gave["r"], 1) == 5.6           # 1.5 + 3.0 + 1.1 of peak given back
    missed = next(r for r in rows if r["key"] == "missed")
    assert missed["n"] == 2 and missed["of"] == 12


def test_one_block_that_never_adds_the_rows_up(monkeypatch):
    out = []
    monkeypatch.setattr(ga.st, "markdown", lambda body, **_k: out.append(str(body)))
    assert ga.what_got_away(_journal())
    text = " ".join(out)
    assert "What got away" in text and "The biggest leak" in text
    assert "don't add up" in text


def test_no_mfe_no_block(monkeypatch):
    monkeypatch.setattr(ga.st, "markdown", lambda *a, **k: None)
    assert not ga.what_got_away(pd.DataFrame({"Closed RR": [1.0, -1.0]}))
