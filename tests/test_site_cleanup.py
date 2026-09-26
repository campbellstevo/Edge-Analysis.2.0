"""Site clean-up (his notes, 26 Sep): conditions verdict, spacing, quiet empty states."""
import re
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from edge_analysis.ui import reshape as rx  # noqa: E402
from edge_analysis.ui import tabs  # noqa: E402


def _capture(monkeypatch):
    out = []
    for mod in (tabs.st, rx.st):
        monkeypatch.setattr(mod, "markdown", lambda body, **k: out.append(str(body)))
        monkeypatch.setattr(mod, "caption", lambda body, **k: out.append(str(body)))
    return out


def _conditions(trend_r, range_r):
    rows = ([{"Conditions MTF": "Trending", "Closed RR": r} for r in trend_r]
            + [{"Conditions MTF": "Ranging", "Closed RR": r} for r in range_r])
    g = pd.DataFrame(rows)
    g["Outcome"] = g["Closed RR"].map(lambda r: "Win" if r > 0.05 else ("Loss" if r < -0.05 else "BE"))
    return g


def test_conditions_never_names_one_cell_best_and_lowest(monkeypatch):
    out = _capture(monkeypatch)
    # 5 trending trades, 12 ranging: the old 8-trade floor left one cell and
    # printed it as both "Best" and "Lowest"
    tabs._conditions_tab(_conditions([-1.0, -1.0, -1.0, -1.0, 0.6],
                                     [1.0, -1.0, 0.5, 0.2, -0.4, 1.5, 0.0, -1.0, 0.9, 0.3, -0.2, 1.56]),
                         show_table=False)
    text = " ".join(out)
    assert "Lowest" not in text and "Best condition" not in text
    assert "Ranging pays best" in text and "5 trending" in text
    # the takeaway sits under the grid, not above it
    assert text.index("Timeframe") < text.index("Ranging pays best")


def test_conditions_says_so_when_states_match(monkeypatch):
    out = _capture(monkeypatch)
    tabs._conditions_tab(_conditions([0.5, -0.5, 0.5, -0.5, 0.2], [0.5, -0.5, 0.5, -0.5, 0.2]),
                         show_table=False)
    assert "No real difference" in " ".join(out)


def test_spacers_are_marked_so_the_theme_can_collapse_doubles(monkeypatch):
    out = _capture(monkeypatch)
    tabs._gap(18)
    assert "class='ea-gap'" in out[0]


def test_no_empty_wrapper_blocks_left():
    # a bare </div> or a lone <div class="section"> drew nothing but took a
    # 12px gap each; they were the other half of the "random spaces"
    pat = re.compile(r'st\.markdown\((?:"</div>"|\'</div>\'|\'<div class="section">\')\s*,')
    for f in ("tabs.py", "mt5_tabs.py", "pro_tabs.py"):
        src = (ROOT / "src" / "edge_analysis" / "ui" / f).read_text()
        assert not pat.search(src), f


def test_not_enough_data_is_a_quiet_note_not_a_warning():
    src = (ROOT / "src" / "edge_analysis" / "ui" / "pro_tabs.py").read_text()
    assert not re.search(r'_insight_box\("Need ~', src)
    assert "you have {len(wins)} so far" in src
