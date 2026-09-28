"""D4: Refinements and Projections are tested against chance before members see them.

    python -m pytest tests/test_refinement_tests.py -q
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

from edge_analysis.ui import tabs as T  # noqa: E402


def _journal(rs, sessions):
    rs = np.round(np.asarray(rs, dtype=float), 2)
    out = np.where(rs > 0.15, "Win", np.where(rs < -0.15, "Loss", "BE"))
    return pd.DataFrame({"Date": pd.date_range("2026-01-01", periods=len(rs), freq="D"),
                         "Outcome": out, "Closed RR": rs, "Session": sessions})


def _claims(res):
    return [it for col in ("working", "holding_back", "refinements") for it in res.get(col, [])]


def test_a_real_session_gap_beats_chance():
    rng = np.random.default_rng(3)
    ny = rng.normal(-0.7, 0.8, 60)
    ldn = rng.normal(0.8, 0.8, 60)
    df = _journal(np.concatenate([ny, ldn]), ["New York"] * 60 + ["London"] * 60)
    res = T.refinements_result(df, df)
    proven = [it["title"] for it in _claims(res) if it.get("proven")]
    assert any("London" in t for t in proven) and any("New York" in t for t in proven)
    assert res["n_proven"] >= 2


def test_pure_noise_rarely_gets_past_the_test():
    fired = 0
    for seed in range(40):
        rng = np.random.default_rng(100 + seed)
        n = 60
        df = _journal(rng.choice([-1.0, 1.0], n) * rng.uniform(0.5, 1.5, n),
                      rng.choice(["New York", "London", "Asia"], n))
        res = T.refinements_result(df, df)
        fired += bool(res["n_proven"])
    assert fired <= 4, fired                      # about the 5% the test allows, not most journals


def test_every_claim_is_labelled_and_counts_are_not():
    rng = np.random.default_rng(5)
    df = _journal(rng.normal(0.1, 1, 30), rng.choice(["New York", "London"], 30))
    res = T.refinements_result(df, df)
    for it in _claims(res):
        if it.get("test"):
            assert it["proven"] in (True, False)
        else:
            assert it["proven"] is None           # fillers and plain counts aren't claims


def test_signflip():
    assert T._signflip_p([1.0] * 12, lower=False) < 0.01
    assert T._signflip_p([1.0, -1.0] * 6, lower=False) > 0.3


def test_members_see_only_what_beats_chance(monkeypatch):
    out = []
    monkeypatch.setattr(T.st, "markdown", lambda body, **k: out.append(body))
    monkeypatch.setattr(T.st, "caption", lambda body, **k: out.append(body))

    class _Col:
        def __enter__(self): return self
        def __exit__(self, *a): return False
    monkeypatch.setattr(T.st, "columns", lambda n: [_Col() for _ in range(n if isinstance(n, int) else len(n))])
    res = {"working": [{"title": "A <b>win</b>", "detail": "d", "test": ("x", "good"), "proven": True}],
           "holding_back": [{"title": "Leak", "detail": "d", "test": ("y", "bad"), "proven": False}],
           "refinements": [{"title": "Keep logging", "action": "a", "proven": None}],
           "n_proven": 1, "n_early": 1}
    T._refinements_tab(pd.DataFrame({"a": [1]}), None, None, result=res, members=True)
    html = " ".join(out)
    assert "A &lt;b&gt;win&lt;/b&gt;" in html and "beats chance" in html   # escaped, labelled
    assert "Leak" not in html and "Keep logging" not in html
    assert "1 more suggestion from your journal" in html


def test_projection_paths_carry_the_sample_uncertainty():
    f = getattr(T._mc_paths, "__wrapped__", T._mc_paths)
    _, fixed = f(500, 456, 0.26, 0.32, 2.8, 1.08, 1.0, 10000.0, 0)
    _, n19 = f(500, 456, 0.26, 0.32, 2.8, 1.08, 1.0, 10000.0, 19)
    _, n2000 = f(500, 456, 0.26, 0.32, 2.8, 1.08, 1.0, 10000.0, 2000)
    p = lambda eq: float(np.mean(eq[:, -1] > 10000))
    assert p(fixed) > 0.99 and p(n19) < 0.9          # 19 trades can't make profit near-certain
    assert p(n2000) > p(n19)                          # more trades, more certainty


def test_projections_lead_with_one_sentence_and_fold_nothing(monkeypatch):
    # round 17: the card leads with one sentence in R. 28 Sep, his note on the
    # folded simulator ("I don't like the hiding stuff away"): it is on the page
    import inspect
    src = inspect.getsource(T._projections_tab)
    assert "st.expander(" not in src and "_projections_body(df_raw, styler)" in src
    body = inspect.getsource(T._projections_body)
    assert "st.expander(" not in body                       # month by month is on a phone too
    assert "Prob. of Profit</div>" not in body               # the sentence already says it
    assert "$" not in src.split('head.markdown(')[1]          # the sentence carries no dollars


def test_projections_count_break_evens_at_what_they_really_pay():
    # 28 Sep check: break-evens were simulated at 0R while his average about
    # -0.2R, so the model ran a third above his edge
    import numpy as np
    zero, _ = T._mc_paths(400, 300, 0.25, 0.30, 2.8, 1.1, 1.0, 10000.0, 0)
    real, _ = T._mc_paths(400, 300, 0.25, 0.30, 2.8, 1.1, 1.0, 10000.0, 0, be_r=-0.23)
    assert float(np.mean(real)) < float(np.mean(zero))
    assert abs(float(np.mean(real)) - (0.25 * 2.8 - 0.30 * 0.23 - 0.45 * 1.1)) < 0.03
