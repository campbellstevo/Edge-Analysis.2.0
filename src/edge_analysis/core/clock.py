"""The trader's clock. The server runs on UTC, so "this week" and "this
month" turned over ten hours late for a Melbourne trader: a Monday-morning
look still showed last week (TZ-04). Everything that asks "what is today"
asks here.

EDGE_LOCAL_TZ sets the zone (a per-member zone is roadmap 5.2); the default
is Melbourne, his city."""
from __future__ import annotations

import os
from datetime import date

import pandas as pd

DEFAULT_TZ = "Australia/Melbourne"


def local_tz() -> str:
    return os.environ.get("EDGE_LOCAL_TZ") or DEFAULT_TZ


def local_now() -> pd.Timestamp:
    """Now on the trader's wall clock, as a naive Timestamp (journal dates are
    naive local times too)."""
    try:
        return pd.Timestamp.now(tz=local_tz()).tz_localize(None)
    except Exception:
        return pd.Timestamp.now()


def local_today() -> date:
    return local_now().date()
