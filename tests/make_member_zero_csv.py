"""Write tests/member_zero_salty.csv — the rows member zero imports into a
duplicate of Salty's TradingPool template (roadmap 0.5).

Same synthetic journal the tests use (tests/salty_fixture.py): R values only,
no prices, balances or dollars. It keeps the awkward rows real journals have —
three with no R yet, four with only a date, two blank — so the walk on Fri 2 Oct
sees what a member's journal really looks like.

Formula columns ("Running R ", "Expectancy ", "Deviation Score") are left out:
Notion computes them. Column names match the app's map exactly, including the
trailing spaces on "Trade No. " — if the import makes new columns instead of
filling existing ones, a name differs from the live template (an open question
in the roadmap).

    python tests/make_member_zero_csv.py
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "src"))

import salty_fixture  # noqa: E402
from edge_analysis.data.notion_adapter import _flatten_props  # noqa: E402

FORMULAS = {"Running R ", "Expectancy ", "Deviation Score"}


def main() -> Path:
    rows = [_flatten_props(p["properties"]) for p in salty_fixture.salty_pages()]
    cols = [c for c in rows[0].keys() if c not in FORMULAS]
    out = HERE / "member_zero_salty.csv"
    with out.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({c: ("" if r.get(c) in (None, False) else r.get(c)) for c in cols})
    return out


if __name__ == "__main__":
    print(main())
