"""A synthetic journal shaped like Salty's TradingPool template, as Notion's
API returns it — so tests drive the real loader, not a hand-built frame.

R values only: no prices, balances or dollar figures. Deterministic (seeded).
Includes the rows real journals have: a few with no R yet, a few with only a
date, and two blank pages.
"""
from __future__ import annotations

import random
from datetime import date, timedelta


def _title(v):
    return {"type": "title", "title": [{"plain_text": str(v)}] if v not in (None, "") else []}


def _text(v):
    return {"type": "rich_text", "rich_text": [{"plain_text": str(v)}] if v not in (None, "") else []}


def _select(v):
    return {"type": "select", "select": {"name": v} if v else None}


def _multi(vs):
    return {"type": "multi_select", "multi_select": [{"name": v} for v in (vs or [])]}


def _date(v):
    return {"type": "date", "date": {"start": v} if v else None}


def _formula():
    # Notion formulas flatten to None in the adapter; the column still exists.
    return {"type": "formula", "formula": {"type": "number", "number": None}}


_SESSIONS = ["London", "NY", "Asia"]
_SESSION_P = [0.5, 0.35, 0.15]
_MODELS = ["FBoS", "Protected Structure Continuation", "NC Model"]
_HOURS = {"London": ["17:30", "18:15", "19:00"], "NY": ["22:30", "23:15", "23:45"],
          "Asia": ["09:30", "10:15", "11:00"]}


def _row(i, d, sess, rr, result, rules):
    return {
        "Trade No. ": _title(i),
        "Date": _date(d),
        "Time of Trade": _text(random.choice(_HOURS[sess]) if sess else ""),
        "Pair": _select("XAUUSD"),
        "R Result": _select(rr),
        "Result": _select(result),
        "Running R ": _formula(),
        "Expectancy ": _formula(),
        "Deviation Score": _formula(),
        "3SL Window": _select(sess),
        "Entry Model": _select(random.choice(_MODELS) if sess else None),
        "Entry Model Timeframe": _select(random.choice(["1M", "3M", "5M"]) if sess else None),
        "Long or Short": _select(random.choice(["Long", "Short"]) if sess else None),
        "Rules Followed? Y/N": _select(rules),
        "HTF/MTF Bias Strength": _select(random.choice(["Strong", "Medium", "Weak"]) if sess else None),
        "Confirmation/Risk": _select(random.choice(["Confirmation", "Risk"]) if sess else None),
        "Double Confirmation": _select(random.choice(["Y", "N"]) if sess else None),
        "+S (Execution)": _select(random.choice(["+S", "No +S"]) if sess else None),
        "Did price hit full TP without you?": _select(random.choice(["Y", "N"]) if sess else None),
        "Entry Confluences": _multi(random.sample(["Sweep", "Divergence", "GAP"], k=random.randint(0, 2)) if sess else []),
        "Emotional State Before Entry": _select(random.choice(["Calm", "Anxious", "Confident"]) if sess else None),
        "News Proximity": _select(random.choice(["No News", "Post News"]) if sess else None),
        "Trade Duration": _select(random.choice(["<30m", "30m-2h", ">2h"]) if sess else None),
    }


def salty_pages(n_trades: int = 120, seed: int = 7) -> list:
    """Notion `results` pages for a Salty-template journal."""
    random.seed(seed)
    pages = []
    start = date(2026, 2, 2)
    days = [start + timedelta(days=k) for k in range(0, 232) if (start + timedelta(days=k)).weekday() < 5]
    for i in range(1, n_trades + 1):
        d = random.choice(days).isoformat()
        sess = random.choices(_SESSIONS, _SESSION_P)[0]
        u = random.random()
        if u < 0.42:
            rr, res = random.choice(["+2RR", "+3RR", "+4RR", "5-6RR"]), "Win"
        elif u < 0.52:
            rr, res = "0RR", "BE"
        else:
            rr, res = "-1RR", "Loss"
        pages.append({"properties": _row(i, d, sess, rr, res, random.choice(["Y", "Y", "Y", "N"]))})
    for i in range(3):  # entered, not closed yet
        pages.append({"properties": _row(900 + i, days[-1 - i].isoformat(), "London", None, None, None)})
    for i in range(4):  # only a date
        pages.append({"properties": _row(950 + i, days[-5 - i].isoformat(), None, None, None, None)})
    for _ in range(2):  # blank pages
        pages.append({"properties": _row("", None, None, None, None, None)})
    return pages


class FakeNotionClient:
    """Stands in for notion_client.Client: serves pages 100 at a time."""

    pages: list = []

    def __init__(self, auth=None, **_kw):
        self.databases = self

    def query(self, database_id=None, page_size=100, start_cursor=None, **_kw):
        start = int(start_cursor or 0)
        chunk = self.pages[start:start + page_size]
        more = start + page_size < len(self.pages)
        return {"results": chunk, "has_more": more,
                "next_cursor": str(start + page_size) if more else None}
