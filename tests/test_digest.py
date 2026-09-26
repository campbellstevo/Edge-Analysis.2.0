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


def test_a_losing_setup_still_is():
    f = digest.findings(_df([-1.0, -1.0, 0.5, -1.0, 0.2], [0.5, 0.2, 0.3, 0.4, 0.25]))
    labels = [x["label"] for x in f]
    assert "Bench Internal PS" in labels and "London is below your average" in labels
