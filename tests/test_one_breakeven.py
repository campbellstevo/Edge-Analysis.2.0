"""One break-even on the site (29 Sep): Result in R counted wins, losses and
break-evens by an R band while every other card read his Outcome tag, so
"avg loss -0.8R" sat beside Projections' "average loss 1.1R". And the whole
record's date axis never reads "Sep 26" again.

    python -m pytest tests/test_one_breakeven.py -q
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

R = pd.Series([3.0, -1.1, -0.3, -1.0, 0.1, -0.25, 2.0, -1.2])
TAG = ["Win", "Loss", "BE", "Loss", "BE", "BE", "Win", "Loss"]
D = pd.Series(pd.date_range("2026-09-01", periods=len(R)))


def test_the_tag_decides_and_the_band_only_fills_in():
    cls = rx.outcome_class(R, TAG)
    assert list(cls) == [1, -1, 0, -1, 0, 0, 1, -1]      # -0.3R and -0.25R tagged BE are break-evens
    cls = rx.outcome_class(R, ["Win", "", None, "Loss", "BE", "nan", "Win", "Loss"])
    assert list(cls) == [1, -1, -1, -1, 0, -1, 1, -1]    # untagged rows fall back to the band
    assert list(rx.outcome_class(R)) == [1, -1, -1, -1, 0, -1, 1, -1]


def test_record_avg_loss_is_the_projections_average_loss():
    s = rx.record_stats(R, D, TAG)
    losses = [r for r, t in zip(R, TAG) if t == "Loss"]
    assert abs(s["avg_l"] - sum(losses) / len(losses)) < 1e-9     # -1.1R, what Projections uses
    assert round(s["be"]) == round(100 * 3 / 8)                   # 3 break-evens by the tag
    assert s["best_l"] == 2                                       # a break-even breaks no streak


def test_date_axis_never_reads_as_a_day():
    short = rx._date_axis(pd.date_range("2026-08-24", "2026-09-28"))
    long = rx._date_axis(pd.date_range("2025-10-01", "2026-09-28"))
    assert short.format == "%d %b" and long.format == "%b %Y"
    assert 'format="%b %y"' not in (ROOT / "src/edge_analysis/ui/reshape.py").read_text(encoding="utf-8")
