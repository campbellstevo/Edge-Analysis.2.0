"""Edge Analysis — MT5 auto-sync.

Watches your MetaTrader 5 terminal and writes every CLOSED trade into your
Notion journal automatically: prices, P&L, session, R multiple, MAE/MFE and
more. You keep filling in the thinking (entry model, mental state); the
numbers arrive on their own.

Run it on the same Windows PC as your MT5 terminal:
    python ea_mt5_sync.py            # sync forever (every few minutes)
    python ea_mt5_sync.py --once     # one pass, then exit
"""
from __future__ import annotations

import argparse
import configparser
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    from zoneinfo import ZoneInfo
except ImportError:
    ZoneInfo = None

import requests

_NV = {"Notion-Version": "2022-06-28"}
_CFG = Path(__file__).with_name("config.ini")


def _cfg():
    cp = configparser.ConfigParser()
    if not _CFG.exists():
        sys.exit("config.ini not found — copy config.example.ini to config.ini "
                 "and fill in your Notion token + database id.")
    cp.read(_CFG, encoding="utf-8")
    s = cp["edge-analysis"]
    tok = s.get("notion_token", "").strip()
    dbid = s.get("database_id", "").replace("-", "").strip()
    if not tok or tok.startswith("PASTE") or not dbid or dbid.startswith("PASTE"):
        sys.exit("Open config.ini and paste your Notion token and database id "
                 "(the README shows exactly where to get both).")
    return {
        "token": tok, "dbid": dbid,
        "tz": s.get("timezone", "Australia/Melbourne").strip(),
        "poll": max(1, s.getint("poll_minutes", fallback=5)),
        "days_back": max(1, s.getint("first_run_days_back", fallback=90)),
        "account_label": s.get("account_label", "").strip(),
        "type_of_trade": s.get("type_of_trade", "Live").strip() or "Live",
    }


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json", **_NV}


def _existing_position_ids(cfg) -> set:
    """Every Position ID already in the journal — makes the sync idempotent."""
    out, cursor = set(), None
    while True:
        body = {"page_size": 100}
        if cursor:
            body["start_cursor"] = cursor
        r = requests.post(f"https://api.notion.com/v1/databases/{cfg['dbid']}/query",
                          headers=_hdr(cfg["token"]), json=body, timeout=20)
        if r.status_code != 200:
            sys.exit(f"Notion refused the database query ({r.status_code}). "
                     "Check the token and that the journal is shared with your "
                     "integration (README step 2).")
        data = r.json() or {}
        for page in data.get("results", []):
            pid = ((page.get("properties") or {}).get("Position ID") or {}).get("number")
            if pid is not None:
                out.add(int(pid))
        cursor = data.get("next_cursor")
        if not data.get("has_more") or not cursor:
            return out


def _pip_size(info) -> float:
    point = getattr(info, "point", 0.01) or 0.01
    digits = getattr(info, "digits", 2)
    return point * (10 if digits in (3, 5) else 1)


def _session_from_hour(h: int) -> str:
    if 17 <= h <= 21:
        return "London"
    if h in (22, 23):
        return "London/NY Overlap"
    if 0 <= h <= 6:
        return "NY"
    if 9 <= h <= 16:
        return "Asian"
    return "Off-Session"


def _collect_closed_positions(mt5, cfg):
    """Group history deals into closed positions with everything computed."""
    now = datetime.now(timezone.utc)
    frm = now - timedelta(days=cfg["days_back"])
    deals = mt5.history_deals_get(frm, now + timedelta(days=1)) or []
    by_pos = {}
    for d in deals:
        if getattr(d, "position_id", 0):
            by_pos.setdefault(d.position_id, []).append(d)
    tz = ZoneInfo(cfg["tz"]) if ZoneInfo else timezone.utc
    out = []
    for pid, ds in by_pos.items():
        ins = [d for d in ds if d.entry == mt5.DEAL_ENTRY_IN]
        outs = [d for d in ds if d.entry in (mt5.DEAL_ENTRY_OUT, mt5.DEAL_ENTRY_INOUT,
                                             getattr(mt5, "DEAL_ENTRY_OUT_BY", 3))]
        if not ins or not outs:
            continue  # still open
        sym = ins[0].symbol
        vol_in = sum(d.volume for d in ins) or 1e-9
        vol_out = sum(d.volume for d in outs) or 1e-9
        entry = sum(d.price * d.volume for d in ins) / vol_in
        exitp = sum(d.price * d.volume for d in outs) / vol_out
        long_ = ins[0].type == mt5.DEAL_TYPE_BUY
        open_t = datetime.fromtimestamp(min(d.time for d in ins), tz=timezone.utc)
        close_t = datetime.fromtimestamp(max(d.time for d in outs), tz=timezone.utc)
        pnl = sum(d.profit for d in ds)
        comm = sum(getattr(d, "commission", 0.0) for d in ds)
        swap = sum(getattr(d, "swap", 0.0) for d in ds)

        info = mt5.symbol_info(sym)
        pip = _pip_size(info) if info else 0.1
        pips = ((exitp - entry) if long_ else (entry - exitp)) / pip

        # SL/TP from the position's order history (last non-zero wins)
        sl = tp = 0.0
        for o in (mt5.history_orders_get(position=pid) or []):
            if getattr(o, "sl", 0.0):
                sl = o.sl
            if getattr(o, "tp", 0.0):
                tp = o.tp
        risk_pips = abs(entry - sl) / pip if sl else 0.0
        r_mult = (pips / risk_pips) if risk_pips else None
        planned = (abs(tp - entry) / abs(entry - sl)) if (sl and tp) else None

        # MAE / MFE from 1-minute candles across the life of the trade
        mae_r = mfe_r = None
        try:
            rates = mt5.copy_rates_range(sym, mt5.TIMEFRAME_M1,
                                         open_t - timedelta(minutes=1),
                                         close_t + timedelta(minutes=1))
            if rates is not None and len(rates) and risk_pips:
                highs = max(r["high"] for r in rates)
                lows = min(r["low"] for r in rates)
                fav = (highs - entry) if long_ else (entry - lows)
                adv = (entry - lows) if long_ else (highs - entry)
                mfe_r = round((fav / pip) / risk_pips, 2)
                mae_r = round(-(adv / pip) / risk_pips, 2)
        except Exception:
            pass

        local = close_t.astimezone(tz)
        hold_min = int((close_t - open_t).total_seconds() // 60)
        result = "Win" if (r_mult or 0) > 0.15 else ("Loss" if (r_mult or 0) < -0.15 else "BE")
        if r_mult is None:
            result = "Win" if pnl > 0 else ("Loss" if pnl < 0 else "BE")
        out.append({
            "pid": int(pid), "symbol": sym, "long": long_,
            "open": open_t.astimezone(tz), "close": local,
            "entry": entry, "exit": exitp, "lots": round(vol_in, 2),
            "pnl": round(pnl, 2), "comm": round(comm, 2), "swap": round(swap, 2),
            "pips": round(pips, 1), "sl": sl or None, "tp": tp or None,
            "risk_pips": round(risk_pips, 1) if risk_pips else None,
            "r": round(r_mult, 2) if r_mult is not None else None,
            "planned": round(planned, 2) if planned else None,
            "mae": mae_r, "mfe": mfe_r, "hold": hold_min,
            "eff": (round((r_mult / mfe_r) * 100, 1)
                    if (r_mult is not None and mfe_r and mfe_r > 0) else None),
            "giveback": (round(mfe_r - r_mult, 2)
                         if (r_mult is not None and mfe_r is not None) else None),
            "result": result,
        })
    return out


def _props(t, cfg) -> dict:
    num = lambda v: {"number": v} if v is not None else None
    sel = lambda v: {"select": {"name": v}} if v else None
    msel = lambda v: {"multi_select": [{"name": v}]} if v else None
    date = lambda v: {"date": {"start": v.isoformat()}} if v else None
    p = {
        "Symbol": {"title": [{"type": "text", "text": {"content": t["symbol"]}}]},
        "Position ID": num(t["pid"]),
        "Open Time": date(t["open"]), "Close Time": date(t["close"]),
        "Direction": sel("Long" if t["long"] else "Short"),
        "Entry Price": num(round(t["entry"], 3)), "Exit Price": num(round(t["exit"], 3)),
        "Lot Size": num(t["lots"]), "PnL (USD)": num(t["pnl"]),
        "Commission": num(t["comm"]), "Swap": num(t["swap"]),
        "Pips": num(t["pips"]), "SL": num(t["sl"]), "TP": num(t["tp"]),
        "Risk (pips)": num(t["risk_pips"]), "R Multiple": num(t["r"]),
        "Planned R:R": num(t["planned"]),
        "MAE (R)": num(t["mae"]), "MFE (R)": num(t["mfe"]),
        "MFE Efficiency %": num(t["eff"]), "Give-back after MFE (R)": num(t["giveback"]),
        "Hold Time (min)": num(t["hold"]),
        "Duration": {"rich_text": [{"type": "text",
                     "text": {"content": f"{t['hold'] // 60}h {t['hold'] % 60}m"}}]},
        "Result": sel(t["result"]),
        "Session": sel(_session_from_hour(t["close"].hour)),
        "Day": sel(t["close"].strftime("%a")),
        "Hour (Melb)": num(t["close"].hour),
        "Month": {"rich_text": [{"type": "text",
                  "text": {"content": t["close"].strftime("%b %Y")}}]},
        "Type of Trade": msel(cfg["type_of_trade"]),
    }
    if cfg["account_label"]:
        p["Account"] = {"rich_text": [{"type": "text",
                        "text": {"content": cfg["account_label"]}}]}
    return {k: v for k, v in p.items() if v is not None}


def _push(t, cfg) -> bool:
    r = requests.post("https://api.notion.com/v1/pages", headers=_hdr(cfg["token"]),
                      json={"parent": {"database_id": cfg["dbid"]},
                            "properties": _props(t, cfg)}, timeout=20)
    if r.status_code == 200:
        return True
    print(f"  ! Notion rejected trade {t['pid']} ({r.status_code}): "
          f"{(r.json() or {}).get('message', '')[:140]}")
    return False


def sync_once(cfg) -> int:
    import MetaTrader5 as mt5
    if not mt5.initialize():
        sys.exit("Couldn't attach to MetaTrader 5 — make sure the MT5 terminal "
                 "is open on this PC, then run again.")
    try:
        have = _existing_position_ids(cfg)
        closed = _collect_closed_positions(mt5, cfg)
        new = [t for t in closed if t["pid"] not in have]
        n = 0
        for t in sorted(new, key=lambda x: x["close"]):
            if _push(t, cfg):
                print(f"  + {t['close']:%d %b %H:%M}  {t['symbol']}  "
                      f"{'L' if t['long'] else 'S'}  {t['r'] if t['r'] is not None else t['pnl']}")
                n += 1
        return n
    finally:
        mt5.shutdown()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true", help="one pass, then exit")
    args = ap.parse_args()
    cfg = _cfg()
    print("Edge Analysis MT5 sync — journal database "
          f"…{cfg['dbid'][-6:]} · every {cfg['poll']} min")
    while True:
        try:
            n = sync_once(cfg)
            print(f"[{datetime.now():%H:%M}] synced {n} new trade(s)" if n
                  else f"[{datetime.now():%H:%M}] nothing new")
        except SystemExit:
            raise
        except Exception as e:
            print(f"[{datetime.now():%H:%M}] hiccup: {e} — retrying next pass")
        if args.once:
            break
        time.sleep(cfg["poll"] * 60)


if __name__ == "__main__":
    main()
