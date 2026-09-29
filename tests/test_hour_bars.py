"""The hour bars are drawn to one honest scale (29 Sep): on a young journal
one readable hour set it, so every thin hour stood at full height.

    python -m pytest tests/test_hour_bars.py -q
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


def _bars(df, monkeypatch, **kw):
    out = []
    monkeypatch.setattr(rx.st, "markdown", lambda html, **_: out.append(html))
    assert rx.hour_bars(df, **kw)
    html = "".join(out)
    cols = re.findall(r'<div class="ea-hb-col">(.*?)<div class="ea-hb-h">(\d\d)</div>', html)
    return {int(h): float(m.group(1)) for body, h in cols
            if (m := re.search(r'height:(\d+)%', body))}


def _journal(rows):
    return pd.DataFrame([{"Hour (Melb)": h, "Closed RR": r, "Outcome": "Win" if r > 0 else "Loss"}
                         for h, r in rows])


def test_one_readable_hour_does_not_set_the_scale(monkeypatch):
    # hour 10 holds five trades at +0.5R; hour 12 one trade at -3R
    df = _journal([(10, 0.5)] * 5 + [(12, -3.0)])
    h = _bars(df, monkeypatch, min_n=5)
    assert h[12] > h[10] * 3, h        # the -3R bar is the tall one, not a tie at full height


def test_three_readable_hours_set_the_scale(monkeypatch):
    df = _journal([(9, 1.0)] * 5 + [(10, 0.5)] * 5 + [(11, -0.5)] * 5 + [(14, -6.0)])
    h = _bars(df, monkeypatch, min_n=5)
    assert h[9] > h[10]                # the readable hours keep their spread
    assert h[14] == max(h.values())    # the thin outlier is clamped, not the scale


def test_phone_keeps_the_values():
    css = rx.css()
    phone = css[css.index("@media (max-width:640px){.ea-hb{"):]
    phone = phone[:phone.index("}}") + 2]
    assert "writing-mode:vertical-rl" in phone and ".ea-hb-v{display:none" not in phone
