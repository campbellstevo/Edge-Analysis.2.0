"""Reshaped views (launch review mockups): the helpers under the new grids."""
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from edge_analysis.ui import reshape as rx  # noqa: E402


def test_parse_hour_reads_every_clock_format():
    assert rx._parse_hour("9:15 PM") == 21
    assert rx._parse_hour("12:05 AM") == 0
    assert rx._parse_hour("2026-09-21 19:07") == 19
    assert rx._parse_hour("after NY") is None
    assert rx._parse_hour(float("nan")) is None


def test_trade_hours_prefers_the_journal_clock():
    salty = pd.DataFrame({"Time of Trade": ["8:30 PM", "soon", "07:10"]})
    assert list(rx.trade_hours(salty)[[0, 2]]) == [20, 7]
    mt5 = pd.DataFrame({"Hour (Melb)": [16, 23]})
    assert list(rx.trade_hours(mt5)) == [16, 23]
    # date-only journals carry no hour at all: no bars, no grid
    date_only = pd.DataFrame({"Date": pd.to_datetime(["2026-09-01", "2026-09-02"])})
    assert rx.trade_hours(date_only) is None


def test_stats_use_house_definitions():
    g = pd.DataFrame({"Outcome": ["Win", "BE", "Loss", "Loss"], "Closed RR": [2.0, 0.0, -1.0, -1.0]})
    s = rx._stats(rx._counted(g))
    assert s["n"] == 4
    assert s["win"] == 25.0          # wins over every counted trade
    assert s["exp"] == 0.0 and s["net"] == 0.0


def test_metric_text():
    assert rx._metric_txt(0.456, "Expectancy") == "+0.46R"
    assert rx._metric_txt(-3.21, "Net R") == "−3.2R"
    assert rx._metric_txt(42.4, "Win rate") == "42%"
    assert rx._metric_txt(None, "Expectancy") == "—"
    assert rx._metric_txt(-0.001, "Expectancy") == "0.00R"
