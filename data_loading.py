"""
Data loading module for Edge Analysis.
"""

from __future__ import annotations
from typing import Optional
import pandas as pd
import streamlit as st
import re

# Import Notion adapter and parsing helpers
from edge_analysis.data.notion_adapter import load_trades_from_notion
from edge_analysis.data.template_adapter import adapt_df  # NEW: Import template adapter
from edge_analysis.core.parsing import (
    infer_instrument,
    normalize_session,
    build_models_list,
    parse_closed_rr,
    classify_outcome_from_fields,
    normalize_account_group,
    build_duration_bin,
)


def _stamp_sync():
    try:
        st.session_state["ea_last_sync"] = pd.Timestamp.now().strftime("%H:%M")
    except Exception:
        pass


@st.cache_data(show_spinner=False, ttl=1800)
def load_live_df(token: Optional[str], dbid: Optional[str]) -> pd.DataFrame:
    _stamp_sync()
    if not (token and dbid):
        return pd.DataFrame()

    # Fetch raw trades from Notion (returns ALL columns, already schema-normalised)
    raw = load_trades_from_notion(token, dbid)
    if raw is None or raw.empty:
        return pd.DataFrame()

    # Detect schema from the normalised frame
    # (notion_adapter already normalised Salty columns; detect_schema on raw would
    # misfire, so we check session_state which was set during load)
    schema = st.session_state.get("detected_schema", "unknown")

    # Apply template mapping for non-Salty schemas (SR schema still benefits from this)
    if schema not in ("salty", "mt5"):
        adapted, template_name = adapt_df(raw, mappings_dir="config/templates")
        df = adapted if template_name else raw
    else:
        df = raw

    df = df.copy()
    df.columns = [c.strip() for c in df.columns]

    # Parse numeric columns
    if "Closed RR" in df.columns:
        df["Closed RR"] = df["Closed RR"].apply(parse_closed_rr)
    if "PnL" in df.columns:
        df["PnL"] = pd.to_numeric(df["PnL"], errors="coerce")

    # Vectorized date operations
    if "Date" in df.columns:
        df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
        dt_accessor = df["Date"].dt
        df["DayName"] = dt_accessor.day_name()
        df["Hour"] = dt_accessor.hour

    # Instrument and session normalisation
    df["Instrument"] = df["Pair"].apply(infer_instrument) if "Pair" in df.columns else "Unknown"
    df["Session Norm"] = df.get("Session", pd.Series(index=df.index, dtype=object)).apply(normalize_session)

    # Entry models list
    if "Multi Entry Model Entry" in df.columns:
        df["Entry Models List"] = df.apply(
            lambda r: build_models_list(r.get("Entry Model"), r.get("Multi Entry Model Entry")),
            axis=1,
        )
    elif "Multi-Entry Model Setup" in df.columns:
        # Salty: "Multi-Entry Model Setup" is Y/N, not a separate model name
        df["Entry Models List"] = df.get("Entry Model", "").apply(lambda v: build_models_list(v, None))
    else:
        df["Entry Models List"] = df.get("Entry Model", "").apply(lambda v: build_models_list(v, None))

    # Entry confluence list — handle both SR "DIV?/Sweep?" and Salty "Entry Confluence" text
    if "Entry Confluence" in df.columns:
        df["Entry Confluence List"] = df["Entry Confluence"].fillna("").astype(str).apply(
            lambda s: [x.strip() for x in re.split(r"[;,]", s) if x.strip()]
        )
    else:
        df["Entry Confluence List"] = [[] for _ in range(len(df))]

    # Outcome classification
    # For Salty, "Result" is already normalised to Win/Loss/BE by notion_adapter
    df["Outcome"] = df.apply(
        lambda r: classify_outcome_from_fields(r.get("Result"), r.get("Closed RR"), r.get("PnL")),
        axis=1,
    )

    # Star ratings
    if "Rating" in df.columns:
        df["Stars"] = df["Rating"].apply(lambda s: s.count("⭐") if isinstance(s, str) else None)
    elif "Trade Quality Rating" in df.columns:
        # Salty: "A+ = perfect model..." — extract letter grade as rough star proxy
        def _grade_to_stars(v):
            if pd.isna(v): return None
            s = str(v).strip().upper()
            if s.startswith("A+"): return 5
            if s.startswith("A"):  return 4
            if s.startswith("B"):  return 3
            if s.startswith("C"):  return 2
            return None
        df["Stars"] = df["Trade Quality Rating"].apply(_grade_to_stars)

    # Risk percentage
    if "Risk Management" in df.columns:
        df["Risk %"] = df["Risk Management"].astype(str).str.extract(r"(\d+(?:\.\d+)?)\s*%")[0].astype(float)

    # Trade duration — Salty has "Trade Duration" as a string bucket ("Under 1 Hour", "1-2HRS" etc.)
    if "Trade Duration" in df.columns:
        df["Trade Duration Num"] = pd.to_numeric(df["Trade Duration"], errors="coerce")
        df["Duration Bin"] = df["Trade Duration"].apply(
            lambda v: v if isinstance(v, str) and v.strip() else build_duration_bin(
                pd.to_numeric(v, errors="coerce")
            )
        )

    # Account grouping (SR only — Salty gets "Salty" sentinel from notion_adapter)
    if "Account" in df.columns:
        df["Account Group"] = df["Account"].apply(normalize_account_group)

    # ── Validity filter ───────────────────────────────────────────────────────
    has_date = df["Date"].notna() if "Date" in df.columns else pd.Series(False, index=df.index)

    conditions = []
    if "PnL" in df.columns:
        conditions.append(df["PnL"].notna())
    if "Closed RR" in df.columns:
        conditions.append(df["Closed RR"].notna())
    if "Result" in df.columns:
        conditions.append(df["Result"].astype(str).str.strip().ne(""))
    if "Entry Model" in df.columns:
        conditions.append(df["Entry Model"].astype(str).str.strip().ne(""))

    if conditions:
        has_signal = conditions[0]
        for cond in conditions[1:]:
            has_signal = has_signal | cond
    else:
        has_signal = pd.Series(False, index=df.index)

    df["Is Complete"] = has_signal
    return df[has_date].copy()
