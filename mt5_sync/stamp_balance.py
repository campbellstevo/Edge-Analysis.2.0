"""Stamp your live MT5 account balance onto the newest trade in Notion.

Why: the dashboard turns dollars into percentages, and it needs a real account
balance to do that. Rather than you typing one (which goes stale the moment the
next trade closes), this reads the balance straight from MetaTrader and writes
it to your most recent journal row. The app then uses it automatically.

Setup: copy this file into C:\\Users\\campb\\OneDrive\\TradingSync\\ (it reuses
the .env already there), then add this line to run_daily_sync.bat, after the
line that runs mt5_notion_sync.py:

    python "%~dp0stamp_balance.py"

Run it by itself any time with:  python stamp_balance.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import requests

_HERE = Path(__file__).resolve().parent
_NV = {"Notion-Version": "2022-06-28"}


def _load_env() -> dict:
    """Read .env from this folder (no dependency on python-dotenv)."""
    env = {}
    for name in (".env", "../TradingSync/.env"):
        p = (_HERE / name).resolve()
        if p.exists():
            for line in p.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    env[k.strip()] = v.strip().strip('"').strip("'")
            break
    for k in ("NOTION_TOKEN", "NOTION_PAGE_ID"):
        if os.environ.get(k):
            env[k] = os.environ[k]
    return env


def main() -> int:
    env = _load_env()
    token = env.get("NOTION_TOKEN")
    dbid = (env.get("NOTION_PAGE_ID") or "").replace("-", "")
    if not token or not dbid:
        print("Couldn't find NOTION_TOKEN / NOTION_PAGE_ID — put this file in "
              "the TradingSync folder next to your .env")
        return 1

    try:
        import MetaTrader5 as mt5
    except ImportError:
        print("MetaTrader5 package missing — run:  pip install MetaTrader5")
        return 1
    if not mt5.initialize():
        print("Couldn't attach to MetaTrader 5 — open the terminal and log in first.")
        return 1
    try:
        acc = mt5.account_info()
        if acc is None:
            print("MT5 gave no account info — is the terminal logged in?")
            return 1
        balance, equity = round(float(acc.balance), 2), round(float(acc.equity), 2)
    finally:
        mt5.shutdown()

    hdr = {"Authorization": f"Bearer {token}", "Content-Type": "application/json", **_NV}

    def _query(db):
        return requests.post(f"https://api.notion.com/v1/databases/{db}/query", headers=hdr,
                             json={"page_size": 1,
                                   "sorts": [{"property": "Close Time",
                                              "direction": "descending"}]},
                             timeout=20)

    override = (env.get("NOTION_DB_ID") or "").replace("-", "")
    if override:
        dbid = override

    r = _query(dbid)
    if r.status_code == 404:
        found = None
        # (a) the id in .env may be the parent PAGE — look inside it
        try:
            kids = requests.get(f"https://api.notion.com/v1/blocks/{dbid}/children",
                                headers=hdr, params={"page_size": 100}, timeout=20)
            for blk in (kids.json() or {}).get("results", []):
                if blk.get("type") == "child_database":
                    found = blk["id"].replace("-", "")
                    break
        except Exception:
            pass
        # (b) otherwise ask Notion for the journal databases we CAN see
        if not found:
            try:
                sr = requests.post("https://api.notion.com/v1/search", headers=hdr,
                                   json={"filter": {"value": "database",
                                                    "property": "object"},
                                         "page_size": 50}, timeout=20)
                cands = []
                for res in (sr.json() or {}).get("results", []):
                    title = "".join(t.get("plain_text", "")
                                    for t in (res.get("title") or []))
                    props = (res.get("properties") or {})
                    if "Position ID" in props or "R Multiple" in props:
                        cands.append((title, res["id"].replace("-", "")))
                if len(cands) == 1:
                    found = cands[0][1]
                elif cands:
                    for title, cid in cands:
                        if "mt5" in title.lower() or "trade log" in title.lower():
                            found = cid
                            break
                    if not found:
                        print("Several journals visible — add this line to .env:")
                        for title, cid in cands:
                            print(f"    NOTION_DB_ID={cid}   # {title}")
                        return 1
            except Exception:
                pass
        if found:
            dbid = found
            r = _query(dbid)
    if r.status_code != 200:
        print(f"Notion refused the query ({r.status_code}): {r.text[:200]}")
        print("Fix: add  NOTION_DB_ID=<your journal database id>  to .env")
        return 1
    results = (r.json() or {}).get("results", [])
    if not results:
        print("No trades in the journal yet — nothing to stamp.")
        return 0

    page_id = results[0]["id"]
    props = {"Balance": {"number": balance}, "Equity": {"number": equity}}
    r2 = requests.patch(f"https://api.notion.com/v1/pages/{page_id}", headers=hdr,
                        json={"properties": props}, timeout=20)
    if r2.status_code != 200:
        print(f"Couldn't write the balance ({r2.status_code}): {r2.text[:160]}")
        return 1
    print(f"Stamped balance ${balance:,.2f} (equity ${equity:,.2f}) onto your latest trade.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
