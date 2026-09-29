"""Plan's "Minimum 3R of room" rule counts only trades that carry a planned
RR (29 Sep, from the 28 Sep blind check: its two sides added up to every
trade), and the targeted-RR table keeps Expectancy on a phone.

    python -m pytest tests/test_plan_room.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "src"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from edge_analysis.ui import plan_tabs as P  # noqa: E402


def test_room_rule_sides_count_only_planned_trades():
    n = 20
    rr = [2.0, -1.0, -1.0, 0.0] * 5
    df = pd.DataFrame({"Date": pd.date_range("2026-08-01 20:00", periods=n, freq="D"),
                       "Closed RR": rr, "Outcome": ["Win", "Loss", "Loss", "BE"] * 5,
                       "Planned R:R": [4.0, 2.0, 5.0, 1.5] * 3 + [None] * 8})
    m = P.plan_model(df)
    room = next(e for e in m["entries"] if e[0].startswith("Minimum "))
    na, nb = room[6], room[7]
    assert na + nb == 12, (na, nb)            # the 8 trades with no target sit on neither side


def test_targeted_rr_table_keeps_its_columns_on_a_phone():
    src = (ROOT / "src/edge_analysis/ui/plan_tabs.py").read_text(encoding="utf-8")
    i = src.index("For reference — targeted RR")
    assert "table-wrap ea-keepcols" in src[i:i + 2500]
