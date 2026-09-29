"""His note on the Model 1 x Model 2 grid (27 Sep): "this is hard to
understand". The pairs are now one ranked list read in words.

    python -m pytest tests/test_pair_list.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "src"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from edge_analysis.ui import reshape as rx  # noqa: E402
from edge_analysis.ui import tabs as T  # noqa: E402

# his shape: the trigger is nearly always Internal NC+S, the structure varies
_M1 = (["External NC+S"] * 4 + ["Internal Protected Structure"] * 5 + ["Internal NC+S"] * 2
       + ["External Protected Structure"] + ["External NC+S"])
_M2 = ["Internal NC+S"] * 12 + ["External NC+S"]
_R = [2.0, 2.0, -0.1, 2.0, 1.0, 1.0, 0.1, -0.1, -1.0, 1.4, -1.1, -1.06, -1.06]


def _journal():
    return pd.DataFrame({"Entry Model 1": _M1, "Entry Model 2": _M2, "Closed RR": _R,
                         "Outcome": ["Win" if r > 0.15 else ("Loss" if r < -0.15 else "BE") for r in _R]})


def _html(monkeypatch, fn):
    out = []
    monkeypatch.setattr(rx.st, "markdown", lambda body, **k: out.append(body))
    fn()
    return " ".join(out)


def test_rows_are_ranked_best_first_with_counts():
    df = _journal()
    rows = rx.pair_rows(df, df["Entry Model 1"], df["Entry Model 2"])
    assert [r["n"] for r in rows] == [4, 5, 2, 1, 1] and rows[0]["m1"] == "External NC+S"
    assert rows[0]["won"] == 3 and round(rows[0]["exp"], 3) == 1.475
    assert rows[0]["exp"] >= rows[1]["exp"] >= rows[-1]["exp"]


def test_one_plain_sentence_and_no_grid_words(monkeypatch):
    df = _journal()
    html = _html(monkeypatch, lambda: rx.pair_list(df, df["Entry Model 1"], df["Entry Model 2"]))
    assert "You trigger on <b>Internal NC+S</b> in 12 of 13 paired trades, so the structure is what changes" in html
    assert "Best so far: <b>External NC+S</b> then <b>Internal NC+S</b>" in html and "early read" in html
    assert "Any model" not in html and "hatched" not in html.lower()
    assert html.count('class="ea-pl-row') == 5 and html.count('class="ea-pl-row few"') == 4


def test_members_see_no_untested_best_pair(monkeypatch):
    df = _journal()
    html = _html(monkeypatch, lambda: rx.pair_list(df, df["Entry Model 1"], df["Entry Model 2"], verdicts=False))
    assert "Best so far" not in html and "12 of 13" in html          # the count is a fact, not a claim


def test_names_are_escaped(monkeypatch):
    df = _journal().assign(**{"Entry Model 1": ["<b>x</b>"] * 13})
    html = _html(monkeypatch, lambda: rx.pair_list(df, df["Entry Model 1"], df["Entry Model 2"]))
    assert "&lt;b&gt;x&lt;/b&gt;" in html and "<b>x</b>" not in html


def test_setups_card_draws_the_list_not_the_grid(monkeypatch):
    out = []
    monkeypatch.setattr(T.st, "markdown", lambda body, **k: out.append(body))
    monkeypatch.setattr(rx.st, "markdown", lambda body, **k: out.append(body))
    monkeypatch.setattr(T.st, "caption", lambda body, **k: out.append(body))
    monkeypatch.setattr(rx, "metric_picker", lambda key: (_ for _ in ()).throw(AssertionError("no metric switch")))

    class _X:
        def __enter__(self): return self
        def __exit__(self, *a): return False
    monkeypatch.setattr(T.st, "expander", lambda *a, **k: _X())
    monkeypatch.setattr(T, "render_entry_model_table", lambda *a, **k: None)
    assert T._two_model_sections(_journal())
    html = " ".join(out)
    assert "Your setups — structure, then trigger" in html and "ea-pl-row" in html


def test_the_full_setup_is_named_once(monkeypatch):
    df = _journal().assign(**{"Timeframe 1": ["5M"] * 9 + ["15M"] * 4, "Timeframe 2": ["1M"] * 9 + ["5M"] * 4})
    tp = df["Timeframe 1"] + " → " + df["Timeframe 2"]
    html = _html(monkeypatch, lambda: rx.pair_list(df, df["Entry Model 1"], df["Entry Model 2"], tfpair=tp))
    # (29 Sep) each pair's row names the timeframes it was taken on; the one
    # "Most taken in full" sentence that stood in for the cross is gone
    assert "Most taken in full" not in html
    row = html[html.index("<span>Internal Protected Structure</span><em>then</em><span>Internal NC+S</span>"):]
    row = row[:row.index("</small>")]
    assert 'class="ea-pl-tf"' in row and "5M → 1M: 5 at " in row
