"""The Weekly debrief (29 Sep, from the 28 Sep blind check): it opens on a
week worth reading, says each number once, and gives the real reason when
there is no grade.

    python -m pytest tests/test_weekly_debrief.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "src"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from streamlit.testing.v1 import AppTest  # noqa: E402


def _debrief(this_week: int):
    def script(this_week):
        import pandas as pd
        from edge_analysis.core.clock import local_now
        from edge_analysis.ui.plan_tabs import render_review_tab
        mon = pd.Timestamp(local_now()).tz_localize(None).normalize()
        mon = mon - pd.Timedelta(days=mon.weekday())
        rows = []
        # last week: four trades over two days, one long and three shorts
        for i, (r, oc, d) in enumerate([(2.0, "Win", "Long"), (-1.0, "Loss", "Short"),
                                         (-0.3, "BE", "Short"), (-1.0, "Loss", "Short")]):
            rows.append({"Date": mon - pd.Timedelta(days=7 - (i // 2), hours=-10), "Closed RR": r,
                         "Outcome": oc, "Direction": d, "Rules Followed?": "Yes", "MFE (R)": max(r, 0) + 0.5})
        for i in range(this_week):
            rows.append({"Date": mon + pd.Timedelta(hours=10 + i), "Closed RR": -1.0, "Outcome": "Loss",
                         "Direction": "Short", "Rules Followed?": "No", "MFE (R)": 0.2})
        render_review_tab(pd.DataFrame(rows), lambda c: c)

    for p in (str(ROOT), str(ROOT / "src")):
        if p not in sys.path:
            sys.path.insert(0, p)
    at = AppTest.from_function(script, args=(this_week,), default_timeout=60)
    at.run()
    assert not at.exception, at.exception
    return at, " ".join(str(m.value) for m in at.markdown) + " " + " ".join(str(c.value) for c in at.caption)


def test_a_thin_new_week_opens_on_last_week():
    at, text = _debrief(1)
    import pandas as pd
    from edge_analysis.core.clock import local_now
    mon = pd.Timestamp(local_now()).tz_localize(None).normalize()
    last = (mon - pd.Timedelta(days=mon.weekday() + 7)).strftime("%d %b")
    assert at.selectbox[0].value.startswith(last)
    # last week's four trades, by the tag: 1 won, 1 break-even, 2 lost
    assert "1 won · 1 BE · 2 lost" in text


def test_each_number_once():
    at, text = _debrief(3)
    assert "vs last week" not in text                  # last week rides on the tiles
    assert "last week 4 of 4" in text                  # rules followed last week
    assert "Rules broken on" not in text               # the tile says it
    assert "given back vs" not in text
    assert "The week's trades, one by one, are" in text
    assert "Direction split" not in text               # one direction: the Net tile again
    assert "All on Monday." in text                    # one day: no strip of one bar
    assert "Too few trades to grade" not in text and "too few to grade" not in text


def test_the_minus_sign_is_true():
    from edge_analysis.ui.plan_tabs import _fmt_r
    assert _fmt_r(-1.33) == "−1.33R" and _fmt_r(-0.001) == "+0.00R"
