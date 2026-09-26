"""What needs work: a leak to cut must actually lose money."""
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from edge_analysis import digest  # noqa: E402


def _df(model_r, other_r, sess_a="London", sess_b="Asia"):
    rows = ([{"Entry Models List": ["Internal PS"], "Session": sess_a, "Closed RR": r} for r in model_r]
            + [{"Entry Models List": ["FBoS"], "Session": sess_b, "Closed RR": r} for r in other_r])
    return pd.DataFrame(rows)


def test_a_profitable_setup_is_never_benched():
    # +0.21R a trade against +0.33R elsewhere: slower, not a leak
    f = digest.findings(_df([1.0, -1.0, 0.5, 0.25, 0.3], [0.5, 0.2, 0.3, 0.4, 0.25]))
    assert not any(x["label"].startswith("Bench") for x in f)
    assert not any("below your average" in x["label"] for x in f)


def test_a_real_losing_setup_still_is():
    f = digest.findings(_df([-1.0, -1.0, 0.5, -1.0, -1.0] * 5, [2.0, -1.0, 2.0, 0.3, 1.0] * 5))
    labels = [x["label"] for x in f]
    assert "Bench Internal PS" in labels or "London is below your average" in labels


def test_noise_rarely_passes_the_null_test():
    import numpy as np
    # (seed 3's stream happens to be lumpy: a Welch t-test flags 15% of its
    # "noise" journals too; across seeds the gate fires on ~4.4%)
    rng = np.random.default_rng(21)
    fired = {"findings": 0, "strengths": 0}
    for _ in range(40):
        n = 80
        g = pd.DataFrame({
            "Closed RR": rng.choice([2.0, -1.0, 0.0], size=n, p=[0.36, 0.52, 0.12]),
            "Session": rng.choice(["London", "New York", "Asia"], size=n),
            "Entry Models List": [[m] for m in rng.choice(["A", "B", "C", "D"], size=n)],
            "Rules Followed?": rng.choice([True, False], size=n, p=[0.8, 0.2]),
        })
        fired["findings"] += bool(digest.findings(g))
        fired["strengths"] += bool(digest.strengths(g))
    # ~5% family-wise per list (2 of 40 expected); findings fired on 75-90% before
    assert fired["findings"] <= 5 and fired["strengths"] <= 5, fired
