"""TZ-04: "this week / this month" follow the trader's clock, not the server's UTC."""
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from edge_analysis.core import clock  # noqa: E402


def test_local_now_is_melbourne_by_default(monkeypatch):
    monkeypatch.delenv("EDGE_LOCAL_TZ", raising=False)
    utc = pd.Timestamp.now(tz="UTC").tz_localize(None)
    gap_h = (clock.local_now() - utc).total_seconds() / 3600
    assert 9.9 < gap_h < 11.1          # AEST +10 / AEDT +11
    assert clock.local_now().tzinfo is None


def test_zone_can_be_set(monkeypatch):
    monkeypatch.setenv("EDGE_LOCAL_TZ", "UTC")
    utc = pd.Timestamp.now(tz="UTC").tz_localize(None)
    assert abs((clock.local_now() - utc).total_seconds()) < 5
