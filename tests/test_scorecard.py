"""Round 9: the week/month scorecard that goes into Notion (R only).

    python -m pytest tests/test_scorecard.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "src"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from edge_analysis import scorecard as sc  # noqa: E402

NOW = pd.Timestamp("2026-09-27 12:00")


def _g():
    dts = pd.to_datetime(["2026-09-14 10:00", "2026-09-15 11:00", "2026-09-22 10:00", "2026-09-23 11:00",
                          "2026-09-23 16:00", "2026-08-20 10:00"])
    return pd.DataFrame({"__dt": dts, "__rr": [-1.24, 4.19, -0.26, -1.03, -0.22, 2.0],
                         "Result": ["Loss", "Win", "BE", "Loss", "BE", "Win"],
                         "Session": ["NY", "Asian", "Asian", "Asian", "Asian", "London"],
                         "Rules Followed?": [True, None, None, False, None, True],
                         "Mistake": [["Other"], [], [], ["Middle of Range"], [], ["NA"]],
                         "Breakeven Criteria": [["Loss before BE"], [], [], [], [], []],
                         "Teachings/Learning Curve": ["Too aggressive", "", "", "Mid-range again", "", "Hold to TP2"],
                         "PnL": [-400.0, 1600.0, -90.0, -350.0, -70.0, 700.0]})


def test_this_week_and_last_week():
    this = sc.build(_g(), "This week", NOW)
    assert this["title"] == "Week of 21 Sep 2026" and this["n"] == 3
    assert round(this["net"], 2) == -1.51 and (this["win"], this["be"], this["loss"]) == (0, 2, 1)
    assert this["rules"] == (0, 1, 2)
    last = sc.build(_g(), "Last week", NOW)
    assert last["n"] == 2 and round(last["net"], 2) == 2.95


def test_month_markdown_is_r_only_and_complete():
    m = sc.build(_g(), "This month", NOW)
    md = sc.to_markdown(m)
    assert md.startswith("# Scorecard · September 2026")
    assert "over 5 trades" in md and "Rules followed on **1 of 2**" in md and "(3 not tagged)" in md
    assert "Mistakes logged: Other ×1, Middle of Range ×1" in md
    assert "1 trade lost before breakeven was set (−1.2R)" in md
    assert "- Too aggressive" in md and "$" not in md and "1600" not in md


def test_empty_period_says_so():
    md = sc.to_markdown(sc.build(_g(), "Last month", pd.Timestamp("2026-08-05")))
    assert "No trades in this period." in md


def test_notion_blocks_and_send(monkeypatch):
    md = sc.to_markdown(sc.build(_g(), "This month", NOW))
    blocks = sc.notion_blocks(md)
    assert blocks[0]["type"] == "paragraph" and blocks[0]["paragraph"]["rich_text"][0]["annotations"]["bold"]
    assert any(b["type"] == "heading_2" for b in blocks) and any(b["type"] == "bulleted_list_item" for b in blocks)

    calls = []

    class R:
        def __init__(self, code, js): self.status_code, self._js = code, js
        def json(self): return self._js
    monkeypatch.setattr(sc.requests, "get", lambda url, headers, timeout: R(200, {"parent": {"type": "page_id", "page_id": "P1"}}))
    monkeypatch.setattr(sc.requests, "post", lambda url, headers, json, timeout: calls.append(json) or R(200, {"url": "https://notion.so/x"}))
    ok, url = sc.send_to_notion("tok", "db", "September 2026", md)
    assert ok and url == "https://notion.so/x"
    assert calls[0]["parent"] == {"page_id": "P1"}
    assert calls[0]["properties"]["title"]["title"][0]["text"]["content"] == "Scorecard · September 2026"

    monkeypatch.setattr(sc.requests, "post", lambda url, headers, json, timeout: R(403, {}))
    ok, msg = sc.send_to_notion("tok", "db", "September 2026", md)
    assert not ok and "insert content" in msg
    monkeypatch.setattr(sc.requests, "get", lambda url, headers, timeout: R(200, {"parent": {"type": "workspace"}}))
    ok, msg = sc.send_to_notion("tok", "db", "September 2026", md)
    assert not ok and "top of your workspace" in msg
