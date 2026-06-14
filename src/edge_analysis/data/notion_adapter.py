from __future__ import annotations
from typing import Any, Dict, List, Optional
import re
import pandas as pd
from notion_client import Client

# ---- simple property flattener (Notion → plain dict) ----
def _flatten_props(props: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for k, v in props.items():
        t = v.get("type")
        if t == "title":
            out[k] = " ".join([r.get("plain_text", "") for r in v.get("title", [])]).strip()
        elif t == "rich_text":
            out[k] = " ".join([r.get("plain_text", "") for r in v.get("rich_text", [])]).strip()
        elif t == "select":
            out[k] = (v.get("select") or {}).get("name")
        elif t == "multi_select":
            out[k] = ", ".join([s.get("name", "") for s in v.get("multi_select", []) if s.get("name")])
        elif t == "number":
            out[k] = v.get("number")
        elif t == "date":
            out[k] = (v.get("date") or {}).get("start")
        elif t == "checkbox":
            out[k] = bool(v.get("checkbox"))
        elif t == "people":
            out[k] = ", ".join([p.get("name", "") for p in v.get("people", []) if p.get("name")])
        elif t == "status":
            out[k] = (v.get("status") or {}).get("name")
        elif t == "url":
            out[k] = v.get("url")
        else:
            out[k] = None
    return out

# ---- helpers / mapping ----
# SR schema (Campbell's)
DATE_FIELDS    = ["Day/Time/Date of Trade", "Date"]
PAIR_FIELDS    = ["Pair", "Instrument"]
SESSION_FIELDS = ["Session"]
ENTRY_FIELDS   = ["Entry Model"]
RESULT_FIELDS  = ["Result"]
RR_FIELDS      = ["Closed RR"]
PNL_FIELDS     = ["PnL"]

# Salty schema additions
SALTY_DATE_FIELDS   = ["Date"]           # Salty uses "Date" (ISO date field)
SALTY_RR_FIELDS     = ["R Result"]       # Salty uses "R Result" not "Closed RR"
SALTY_RESULT_FIELDS = ["Result"]         # Same name, different values


def _first_nonempty(row: Dict[str, Any], fields: List[str]) -> Optional[str]:
    for f in fields:
        val = row.get(f)
        if val not in (None, "", "NaN"):
            return val
    return None

# RR parsing: ranges like "+9-10" -> 9.5; "9—10" -> 9.5; "-1 to -2" -> -1.5
# Also handles Salty format: "-1RR", "+9RR", "8-9RR"
_RR_RANGE_RE = re.compile(r'([+-]?\d+(?:\.\d+)?)\s*(?:-|—|to)\s*([+-]?\d+(?:\.\d+)?)', re.I)
def parse_closed_rr(x):
    if x is None:
        return float("nan")
    if isinstance(x, (int, float)):
        try:
            return float(x)
        except Exception:
            return float("nan")
    s = str(x).strip()
    # Strip trailing "RR" suffix (Salty format: "+9RR", "-1RR", "8-9RR")
    s = re.sub(r'RR$', '', s, flags=re.I).strip()
    if not s:
        return float("nan")
    m = _RR_RANGE_RE.search(s)
    if m:
        a = float(m.group(1)); b = float(m.group(2))
        return (a + b) / 2.0
    # "+10 Plus" / "10 Plus" / "10+"  -> floor value (e.g. 10). Without this the
    # biggest winners parse to NaN and drop out of all RR / PnL stats.
    m_plus = re.search(r"([+-]?\d+(?:\.\d+)?)\s*(?:\+|plus\b)", s, re.I)
    if m_plus:
        return float(m_plus.group(1))
    try:
        return float(s.replace("+", ""))
    except Exception:
        return float("nan")


# ── Schema detection ──────────────────────────────────────────────────────────
# Fingerprint columns to identify which Notion database is connected.
# Returns "sr" (Campbell's schema), "salty" (mentor's schema), or "unknown".

_SR_SIGNATURE_COLS = {
    "Day/Time/Date of Trade", "2h session window", "Mental State",
    "Execution/Bias", "DIV?", "Sweep?", "Targeted RR",
}
_SALTY_SIGNATURE_COLS = {
    "Trade No. ", "R Result", "Running R ", "Deviation Score",
    "HTF/MTF Bias Strength", "Confirmation/Risk", "Double Confirmation",
    "+S (Execution)", "Did price hit full TP without you?",
}
# MT5 Trade Log schema (auto-imported from MetaTrader 5).
# These columns are unique to the MT5 template (not in SR or Salty).
_MT5_SIGNATURE_COLS = {
    "R Multiple", "MAE (R)", "MFE (R)", "Position ID", "PnL (USD)",
    "Open Time", "Close Time", "Lot Size", "Entry Price", "Exit Price", "Pips",
}

def detect_schema(df: pd.DataFrame) -> str:
    """
    Detect which schema the DataFrame came from.
    Returns 'sr', 'salty', or 'unknown'.
    """
    cols = set(df.columns)
    sr_hits    = len(cols & _SR_SIGNATURE_COLS)
    salty_hits = len(cols & _SALTY_SIGNATURE_COLS)
    mt5_hits   = len(cols & _MT5_SIGNATURE_COLS)
    if mt5_hits >= 3 and mt5_hits >= sr_hits and mt5_hits >= salty_hits:
        return "mt5"
    if salty_hits >= 3 and salty_hits > sr_hits:
        return "salty"
    if sr_hits >= 3:
        return "sr"
    return "unknown"


# ── Salty column normalisation ────────────────────────────────────────────────
# Maps Salty's raw column names to canonical names used throughout the app.
_SALTY_COLUMN_MAP = {
    "Pair":                         "Pair",            # same
    "Date":                         "Date",            # same
    "Time of Trade":                "Time of Trade",
    "Trade No. ":                   "Trade No",
    "R Result":                     "Closed RR",       # canonical RR field
    "Running R ":                   "Running R",
    "Expectancy ":                  "Expectancy",
    "Planned Entry Price":          "Planned Entry Price",
    "Executed Entry Price":         "Executed Entry Price",
    "Deviation Score":              "Deviation Score",
    "Planned SL ":                  "Planned SL",
    "Executed SL":                  "Executed SL",
    "Planned Take Profit ":         "Planned Take Profit",
    "Executed Take Profit":         "Executed Take Profit",
    "Did price hit full TP without you?": "Hit Full TP",
    "Entry Confluences":            "Entry Confluence",  # → confluences tab
    "Long or Short":                "Direction",
    "3SL Window":                   "Session",          # Salty uses this as session name
    "Type of Trade":                "Type of Trade",
    "Entry Model":                  "Entry Model",      # same
    "Entry Model Timeframe":        "Entry Timeframe",
    "+S (Execution)":               "Execution Score",
    "Divergence (Execution)":       "DIV?",             # map to SR's DIV? field
    "RR":                           "Targeted RR",      # planned RR = targeted
    "Price Delivery":               "Price Delivery",
    "Rules Followed? Y/N":          "Rules Followed",
    "Trade Quality Rating":         "Trade Quality Rating",
    "Trade of the Day":             "A+ Setup?",        # closest equivalent
    "HTF/MTF Bias Strength":        "HTF/MTF Bias Strength",
    "Conditions MTF/HTF":           "Conditions HTF",
    "Confirmation/Risk":            "Confirmation/Risk",
    "Double Confirmation":          "Multi-Entry Model Setup",  # closest equivalent
    "Result":                       "Result",           # same
    "Target ":                      "Target",
    "Stop Loss Logic":              "Stop Loss Logic",
    "Entry + Confirmation":         "Entry + Confirmation",
    "Trade Duration":               "Trade Duration",
    "Risk Management":              "Risk Management",
    "Breakeven Criteria":           "Breakeven Criteria",
    "1M/3M/5M Break":               "LTF Break",
    "15M/30M/1HR Break":            "HTF Break",
    "MTF Tier Pricing":             "Tiers in pricing MTF",
    "HTF Tier Pricing":             "Tiers in pricing HTF",
    "News Proximity":               "News Aspect",
    "Emotional State Before Entry": "Mental State",     # map to SR's Mental State
    "Post Trade Emotions":          "Post Trade Emotions",
    "Teachings/Learning Curve":     "Teachings/Learning Curve",
}

# Salty "Result" values → canonical Outcome values used by the app
_SALTY_RESULT_MAP = {
    "Win":       "Win",
    "Loss":      "Loss",
    "BE":        "BE",
    "Breakeven": "BE",
}


def normalise_salty_df(df: pd.DataFrame) -> pd.DataFrame:
    """
    Rename Salty columns to canonical names and normalise key fields
    so the rest of the app can treat both schemas identically.
    """
    out = df.copy()

    # Rename columns
    rename = {src: dst for src, dst in _SALTY_COLUMN_MAP.items() if src in out.columns}
    out = out.rename(columns=rename)

    # Normalise Result → canonical Outcome values
    if "Result" in out.columns:
        out["Result"] = out["Result"].map(
            lambda v: _SALTY_RESULT_MAP.get(str(v).strip(), str(v).strip()) if pd.notna(v) else v
        )

    # Salty has no "Account" column — fill with a sentinel so Account tab shows gracefully
    if "Account" not in out.columns:
        out["Account"] = "Salty"

    # Salty has no "2h session window" — fill with NaN so 3SL tab degrades gracefully
    if "2h session window" not in out.columns:
        out["2h session window"] = None

    # Salty has no separate Mental State field after rename? Already mapped above.
    # Ensure Execution/Bias is absent so Mental State Gate doesn't crash
    # (Salty doesn't have the 4-way Execution/Bias split)

    # Salty "3SL Window" → "Session": values are "London", "Asia", etc. — already correct.
    # But also set Session Norm directly so session detection works.
    if "Session" in out.columns and "Session Norm" not in out.columns:
        out["Session Norm"] = out["Session"]

    return out


# -- MT5 Trade Log normalisation ----------------------------------------------
_MT5_COLUMN_MAP = {
    "Symbol":            "Pair",
    "Entry Confluences": "Entry Confluence",
    "PnL (USD)":         "PnL",
    "Duration":          "Trade Duration",
}

def normalise_mt5_df(df: pd.DataFrame) -> pd.DataFrame:
    """Rename MT5 columns that differ from the app's canonical names.
    Date comes from "Open Time" and RR from numeric "R Multiple" (set in loader)."""
    out = df.copy()
    rename = {src: dst for src, dst in _MT5_COLUMN_MAP.items() if src in out.columns}
    out = out.rename(columns=rename)

    if "Result" in out.columns:
        _fix = {"win": "Win", "loss": "Loss", "be": "BE", "breakeven": "BE"}
        out["Result"] = out["Result"].map(
            lambda v: _fix.get(str(v).strip().lower(), str(v).strip()) if pd.notna(v) else v
        )

    if "Session" in out.columns and "Session Norm" not in out.columns:
        out["Session Norm"] = out["Session"]

    return out


# ── main loader ──────────────────────────────────────────────────────────────
def load_trades_from_notion(token: str, database_id: str, page_size: int = 100) -> pd.DataFrame:
    client = Client(auth=token)

    results: List[Dict[str, Any]] = []
    next_cursor: Optional[str] = None
    while True:
        resp = client.databases.query(
            database_id=database_id,
            page_size=page_size,
            start_cursor=next_cursor
        )
        results.extend(resp.get("results", []))
        if not resp.get("has_more"):
            break
        next_cursor = resp.get("next_cursor")

    rows = [_flatten_props(r.get("properties", {})) for r in results]
    df = pd.DataFrame(rows)

    if df.empty:
        return pd.DataFrame(columns=["Date", "Pair", "Session", "Entry Model", "Result", "Closed RR", "PnL"])

    # ── Detect schema and normalise ──────────────────────────────────────────
    schema = detect_schema(df)

    if schema == "salty":
        df = normalise_salty_df(df)
        # After normalisation, "Closed RR" came from "R Result"
        rr_source = ["Closed RR"]
        date_source = ["Date"]
    elif schema == "mt5":
        df = normalise_mt5_df(df)
        # MT5 gives an EXACT numeric R via "R Multiple"; date from Open Time.
        rr_source = ["R Multiple"]
        date_source = ["Open Time", "Close Time"]
    else:
        # SR schema
        rr_source = RR_FIELDS
        date_source = DATE_FIELDS

    # Store detected schema for downstream use
    # (tabs.py reads this from session_state)
    try:
        import streamlit as st
        st.session_state["detected_schema"] = schema
    except Exception:
        pass

    # Parse the Date field
    if any(field in df.columns for field in date_source):
        df["Date"] = pd.to_datetime(
            df.apply(lambda r: _first_nonempty(r, date_source), axis=1),
            errors="coerce",
            utc=True
        ).dt.tz_localize(None)

    # Parse Closed RR
    if any(field in df.columns for field in rr_source):
        df["Closed RR"] = df.apply(lambda r: parse_closed_rr(_first_nonempty(r, rr_source)), axis=1)

    # Parse PnL if present
    if any(field in df.columns for field in PNL_FIELDS):
        df["PnL"] = pd.to_numeric(df.apply(lambda r: _first_nonempty(r, PNL_FIELDS), axis=1), errors="coerce")

    return df
