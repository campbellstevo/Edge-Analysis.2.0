"""The trade card's path (29 Sep, from the 28 Sep blind check): its labels
never overlap, never run off the drawing, and a phone gets its own drawing.

    python -m pytest tests/test_trade_path.py -q
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "src"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from edge_analysis.ui import reshape as rx  # noqa: E402


def _labels(svg, y):
    return [(float(x), t) for x, t in re.findall(rf'<text x="([\d.]+)" y="{y}"[^>]*>([^<]+)</text>', svg)]


def _clear(labels, per_char, w):
    spans = sorted((x - len(t) * per_char / 2, x + len(t) * per_char / 2) for x, t in labels)
    assert all(a >= 0 and b <= w for a, b in spans), spans
    assert all(spans[i][1] <= spans[i + 1][0] for i in range(len(spans) - 1)), spans


def test_labels_never_overlap_or_run_off():
    for w in (400, 300):
        # a 9R target squeezes stop and entry together; a scratch puts worst and best side by side
        for row in ({"plan": 9.0, "mae": -0.2, "mfe": 0.1, "r": 0.0},
                    {"plan": 3.7, "mae": -1.68, "mfe": 2.44, "r": 0.0},
                    {"plan": None, "mae": -0.05, "mfe": 0.05, "r": 0.0}):
            svg = rx._big_path(pd.Series(row), w)
            _clear(_labels(svg, 78), 6.9, w)
            _clear(_labels(svg, 16), 6.2, w)


def test_spread_leaves_room_alone():
    assert rx._spread([(50, 20), (200, 20)], 0, 400) == [50.0, 200.0]
