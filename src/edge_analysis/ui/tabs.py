from __future__ import annotations
import numpy as np
import pandas as pd
import altair as alt
import streamlit as st
from pathlib import Path
import re
import os
import html as _html
from datetime import time as dt_time, timedelta
from zoneinfo import ZoneInfo

from edge_analysis.ui.components import (
    render_entry_model_table,
    render_session_performance_table,
    render_day_performance_table,
    render_timeframe_table,
)

from edge_analysis.data.template_adapter import adapt_auto

CONFLUENCE_OPTIONS = ["DIV", "Sweep", "DIV & Sweep"]

# Psychology thresholds
OVERTRADE_LIMIT = 3          # max trades per day before flagged
REVENGE_WINDOW_MINS = 120    # minutes after a loss before next entry = revenge
ASIA_WARN_THRESHOLD = 45.0   # % of trades in Asia before session alert fires

# ── Schema helpers ────────────────────────────────────────────────────────────
def _get_schema() -> str:
    """Return detected schema: 'sr', 'salty', or 'unknown'."""
    try:
        import streamlit as st
        return st.session_state.get("detected_schema", "sr")
    except Exception:
        return "sr"

def _is_salty() -> bool:
    return _get_schema() == "salty"


_MT5_COLS = {"R Multiple", "MAE (R)", "MFE (R)", "Open Time", "Close Time",
             "Lot Size", "Position ID", "MFE Efficiency %", "Spread at Entry"}

def _df_is_mt5(df) -> bool:
    """Detect the MT5 Trade Log straight from the dataframe columns.
    Robust to Streamlit caching (which can skip the session_state schema flag)."""
    try:
        return len(set(df.columns) & _MT5_COLS) >= 3
    except Exception:
        return False

def _unavailable(label: str) -> None:
    """Quiet note when a section has no data for this template."""
    st.caption(f"{label}: nothing to show yet — once you log this in Notion, it fills in automatically.")


_INSIGHT_BUDGET = None


class _budget:
    """Card-scope cap on insight boxes: with _budget(1): ... shows at most one."""
    def __init__(self, n=1):
        self.n = n
    def __enter__(self):
        global _INSIGHT_BUDGET
        _INSIGHT_BUDGET = self.n
    def __exit__(self, *a):
        global _INSIGHT_BUDGET
        _INSIGHT_BUDGET = None


def _card_header(title: str, sub: str = "") -> None:
    st.markdown(
        f"<div style='font-size:21px;font-weight:800;color:#0f172a;'>{title}</div>"
        + (f"<div style='font-size:14px;color:#8a93a6;margin:2px 0 8px;'>{sub}</div>" if sub else ""),
        unsafe_allow_html=True)


def _insight_box(body: str, kind: str = "info") -> None:
    global _INSIGHT_BUDGET
    if _INSIGHT_BUDGET is not None:
        if _INSIGHT_BUDGET <= 0:
            return
        _INSIGHT_BUDGET -= 1
    return _insight_box_raw(body, kind)


def _insight_box_raw(body: str, kind: str = "info") -> None:
    """Live-data insight callout. Always purple — kind only affects the prefix icon."""
    icons = {"info": "", "warn": "⚠ ", "good": "✓ ", "bad": "✕ "}
    prefix = icons.get(kind, "")
    st.markdown(
        f'<div style="background:#f0ebff;border-left:4px solid #4800ff;border-radius:6px;'
        f'padding:14px 18px;font-size:14px;line-height:1.8;margin:12px 0;">'
        f'{prefix}{body}</div>',
        unsafe_allow_html=True,
    )


def _asset_label(name: str) -> str:
    return "GOLD" if str(name) == "Gold" else str(name)


# ─────────────────────────── Session/Date helpers ────────────────────────────
def _extract_iso_from_notion(v):
    try:
        if isinstance(v, dict):
            return v.get("start") or v.get("date") or v.get("timestamp") or v.get("name")
        if isinstance(v, (list, tuple)) and v:
            return _extract_iso_from_notion(v[0])
    except Exception:
        pass
    return v


def _coerce_datetime_series(df: pd.DataFrame, tz_name: str = "UTC"):
    cand_single = [
        "Date & Time", "Datetime", "Entry Datetime", "Opened At",
        "Timestamp", "Created", "Created At", "Entry Time (UTC)", "Time & Date",
    ]
    cand_date = ["Date", "Trade Date", "Entry Date"]
    cand_time = ["Time", "Trade Time", "Entry Time"]

    for c in cand_single:
        if c in df.columns:
            s = df[c].map(_extract_iso_from_notion)

            def _num_to_ts(x):
                try:
                    if x is None or (isinstance(x, float) and pd.isna(x)):
                        return None
                    if isinstance(x, (int, float)) and not isinstance(x, bool):
                        x = int(x)
                        if x > 10 ** 11:
                            return pd.to_datetime(x, unit="ms", utc=True)
                        return pd.to_datetime(x, unit="s", utc=True)
                    return x
                except Exception:
                    return x

            s = s.map(_num_to_ts)
            s_dt = pd.to_datetime(s, utc=True, errors="coerce")
            break
    else:
        s_dt = None

    if s_dt is None:
        dcol = next((c for c in cand_date if c in df.columns), None)
        tcol = next((c for c in cand_time if c in df.columns), None)
        if dcol and tcol:
            s_date = pd.to_datetime(df[dcol].map(_extract_iso_from_notion), errors="coerce")
            s_time = df[tcol].astype(str).str.strip().replace({"": "00:00"})
            s_dt = pd.to_datetime(
                s_date.dt.strftime("%Y-%m-%d") + " " + s_time, errors="coerce"
            )

    if s_dt is None:
        dcol = next((c for c in cand_date if c in df.columns), None)
        if dcol:
            s_date = pd.to_datetime(df[dcol].map(_extract_iso_from_notion), errors="coerce")
            s_dt = pd.to_datetime(s_date.dt.strftime("%Y-%m-%d") + " 00:00", errors="coerce")

    if s_dt is None:
        return None

    try:
        tz = ZoneInfo(str(tz_name or "UTC"))
        if s_dt.dt.tz is None:
            s_dt = s_dt.dt.tz_localize(tz).dt.tz_convert("UTC")
        else:
            s_dt = s_dt.dt.tz_convert("UTC")
    except Exception:
        if s_dt.dt.tz is None:
            s_dt = s_dt.dt.tz_localize("UTC")
        else:
            s_dt = s_dt.dt.tz_convert("UTC")

    return s_dt


_SESSIONS = {
    "Asia":     {"tz": ZoneInfo("Asia/Tokyo"),        "start": dt_time(9, 0),  "end": dt_time(18, 0)},
    "London":   {"tz": ZoneInfo("Europe/London"),     "start": dt_time(8, 0),  "end": dt_time(17, 0)},
    "New York": {"tz": ZoneInfo("America/New_York"),  "start": dt_time(8, 0),  "end": dt_time(17, 0)},
}


def _time_in_window(local_dt: pd.Timestamp, start: dt_time, end: dt_time) -> bool:
    if pd.isna(local_dt):
        return False
    t = local_dt.timetz()
    if start <= end:
        return start <= t < end
    return (t >= start) or (t < end)


def _classify_session_market_local(ts_aware: pd.Timestamp) -> str | None:
    if ts_aware is None or pd.isna(ts_aware):
        return None
    active = []
    for name, cfg in _SESSIONS.items():
        local = ts_aware.astimezone(cfg["tz"])
        if _time_in_window(local, cfg["start"], cfg["end"]):
            active.append(name)
    if not active:
        return "Other"
    for winner in ["New York", "London", "Asia"]:
        if winner in active:
            return winner


def _clean_session_value(v):
    if v is None:
        return None
    s = str(v).strip()
    if not s:
        return None
    sl = s.lower()
    if "asia" in sl:
        return "Asia"
    if "london" in sl:
        return "London"
    if "new york" in sl or sl in {"ny", "ny session"}:
        return "New York"
    return s


def _ensure_session_and_day(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return df
    out = df.copy()

    if "Session Norm" in out.columns and not out["Session Norm"].isna().all():
        out["Session Norm"] = out["Session Norm"].map(_clean_session_value)
        if "DayName" not in out.columns or out["DayName"].isna().all():
            s_dt = _coerce_datetime_series(out, tz_name=os.getenv("EDGE_SESSIONS_TZ", "Australia/Sydney"))
            if s_dt is not None:
                try:
                    local_tz = ZoneInfo(os.getenv("EDGE_LOCAL_TZ", "Australia/Sydney"))
                    out["DayName"] = s_dt.dt.tz_convert(local_tz).dt.day_name()
                except Exception:
                    out["DayName"] = s_dt.dt.day_name()
        return out

    if "Session" in out.columns:
        out["Session Norm"] = out["Session"].map(_clean_session_value)
        if "DayName" not in out.columns or out["DayName"].isna().all():
            s_dt = _coerce_datetime_series(out, tz_name=os.getenv("EDGE_SESSIONS_TZ", "Australia/Sydney"))
            if s_dt is not None:
                try:
                    local_tz = ZoneInfo(os.getenv("EDGE_LOCAL_TZ", "Australia/Sydney"))
                    out["DayName"] = s_dt.dt.tz_convert(local_tz).dt.day_name()
                except Exception:
                    out["DayName"] = s_dt.dt.day_name()
            elif "Date" in out.columns:
                dts = pd.to_datetime(out["Date"], errors="coerce")
                out["DayName"] = dts.dt.day_name()
        return out

    s_dt_utc = _coerce_datetime_series(out, tz_name=os.getenv("EDGE_SESSIONS_TZ", "Australia/Sydney"))
    if s_dt_utc is None:
        out["Session Norm"] = None
        if "DayName" not in out.columns:
            out["DayName"] = None
        return out

    out["__ts_utc"] = s_dt_utc
    out["Session Norm"] = out["__ts_utc"].map(_classify_session_market_local)
    try:
        local_tz = ZoneInfo(os.getenv("EDGE_LOCAL_TZ", "Australia/Sydney"))
        out["DayName"] = out["__ts_utc"].dt.tz_convert(local_tz).dt.day_name()
    except Exception:
        out["DayName"] = out["__ts_utc"].dt.day_name()

    return out.drop(columns=["__ts_utc"])


# ── Completion-aware helper ───────────────────────────────────────────────────
def _prep_perf_df(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return df
    out = df.copy()
    if "Is Complete" in out.columns:
        out = out[out["Is Complete"] == True].copy()
    if "Outcome Canonical" in out.columns:
        if "Outcome" not in out.columns:
            out["Outcome"] = out["Outcome Canonical"]
        else:
            mask_bad = ~out["Outcome"].isin(["Win", "BE", "Loss"])
            out.loc[mask_bad, "Outcome"] = out.loc[mask_bad, "Outcome Canonical"]
    if "Closed RR Num" in out.columns:
        if "Closed RR" not in out.columns:
            out["Closed RR"] = out["Closed RR Num"]
        else:
            mask_nan = out["Closed RR"].isna()
            out.loc[mask_nan, "Closed RR"] = out["Closed RR Num"]
    try:
        out = _ensure_session_and_day(out)
    except Exception:
        pass
    return out


def outcome_rates_from(df):
    if df.empty or "Outcome" not in df.columns:
        return dict(total=0, counted=0, wins=0, bes=0, losses=0,
                    win_rate=0.0, be_rate=0.0, loss_rate=0.0)
    counted = df[df["Outcome"].isin(["Win", "BE", "Loss"])]
    counted_n = len(counted)
    wins = int(counted["Outcome"].eq("Win").sum())
    bes = int(counted["Outcome"].eq("BE").sum())
    losses = int(counted["Outcome"].eq("Loss").sum())
    return dict(
        total=len(df), counted=counted_n, wins=wins, bes=bes, losses=losses,
        win_rate=round((wins / max(1, counted_n)) * 100.0, 2),
        be_rate=round((bes / max(1, counted_n)) * 100.0, 2),
        loss_rate=round((losses / max(1, counted_n)) * 100.0, 2),
    )


def _rr_stats(df: pd.DataFrame):
    if df is None or df.empty or "Closed RR" not in df.columns:
        return (None, None)
    rr = pd.to_numeric(df["Closed RR"], errors="coerce").dropna()
    if rr.empty:
        return (None, None)
    return (float(rr.sum()), float(rr.mean()))


def generate_overall_stats(df: pd.DataFrame):
    if df.empty:
        return dict(total=0, wins=0, losses=0, bes=0, win_rate=0.0, loss_rate=0.0,
                    be_rate=0.0, avg_rr=0.0, avg_pnl=0.0, total_pnl=0.0, unknown=0)
    rates = outcome_rates_from(df)
    unknown = rates["total"] - rates["counted"]
    if {"Closed RR", "Outcome"} <= set(df.columns):
        wins_only = df[df["Outcome"] == "Win"]
        avg_rr = (float(wins_only["Closed RR"].mean())
                  if not wins_only.empty and not wins_only["Closed RR"].isna().all() else 0.0)
    else:
        avg_rr = 0.0
    avg_pnl = float(df["PnL"].mean()) if "PnL" in df.columns and not df["PnL"].isna().all() else 0.0
    total_pnl = float(df["PnL"].sum()) if "PnL" in df.columns and not df["PnL"].isna().all() else 0.0
    return dict(total=rates["total"], wins=rates["wins"], losses=rates["losses"], bes=rates["bes"],
                win_rate=rates["win_rate"], loss_rate=rates["loss_rate"], be_rate=rates["be_rate"],
                avg_rr=avg_rr, avg_pnl=avg_pnl, total_pnl=total_pnl, unknown=unknown)


def _to_alt_values(df: pd.DataFrame):
    if df is None or len(df) == 0:
        return []
    d = df.reset_index(drop=True).copy()
    for c in d.columns:
        col = d[c]
        if pd.api.types.is_datetime64_any_dtype(col):
            tmp = pd.to_datetime(col, errors="coerce")
            if getattr(tmp.dt, "tz", None) is not None:
                tmp = tmp.dt.tz_localize(None)
            d[c] = tmp.dt.to_pydatetime()
        elif pd.api.types.is_integer_dtype(col):
            d[c] = col.apply(lambda v: None if pd.isna(v) else int(v))
        elif pd.api.types.is_float_dtype(col):
            d[c] = col.apply(lambda v: None if pd.isna(v) else float(v))
        else:
            d[c] = col.astype(object)
    return d.to_dict(orient="records")


def _ensure_entry_models_list(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return df
    out = df.copy()
    if "Entry Models List" in out.columns:
        def _coerce_to_list(v):
            if isinstance(v, (list, tuple)):
                return list(v)
            if pd.isna(v) or v == "":
                return []
            return [str(v)]
        out["Entry Models List"] = out["Entry Models List"].apply(_coerce_to_list)
        return out
    lower_map = {str(c).strip().lower(): c for c in out.columns}
    alt_col = None
    for key in ("entry models", "entry model", "entry models list"):
        if key in lower_map:
            alt_col = lower_map[key]
            break

    def _split_models(x):
        if isinstance(x, (list, tuple)):
            return [str(i).strip() for i in x if str(i).strip()]
        if pd.isna(x):
            return []
        s = str(x)
        parts = [p.strip() for p in re.split(r"[;,/|+]", s) if p.strip()]
        return parts if parts else ([] if s.strip() == "" else [s.strip()])

    if alt_col:
        out["Entry Models List"] = out[alt_col].apply(_split_models)
    else:
        out["Entry Models List"] = [[] for _ in range(len(out))]
    return out


def _ensure_instrument_column(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return df
    out = df.copy()
    lower_map = {str(c).strip().lower(): c for c in out.columns}

    def pick(*names):
        for n in names:
            if n in lower_map:
                return lower_map[n]
        return None

    if "Instrument" in out.columns:
        alt = pick("pair", "symbol", "ticker", "market", "asset")
        if alt is not None:
            mask = out["Instrument"].isna() | (out["Instrument"].astype(str).str.strip() == "")
            out.loc[mask, "Instrument"] = out.loc[mask, alt]
        return out
    alt = pick("instrument", "pair", "symbol", "ticker", "market", "asset")
    if alt is not None:
        out["Instrument"] = out[alt]
    return out


# ───────────────────────────── Early Close helpers ───────────────────────────

def _parse_closed_rr_mid(val) -> float:
    if pd.isna(val):
        return np.nan
    v = str(val).strip()
    if v == "+0":
        return 0.0
    if v == "-1":
        return -1.0
    m = re.match(r"[+\-]?(\d+\.?\d*)-(\d+\.?\d*)", v)
    if m:
        lo, hi = float(m.group(1)), float(m.group(2))
        mid = (lo + hi) / 2
        return mid if not v.startswith("-") else -mid
    m2 = re.match(r"([+\-]?\d+\.?\d*)", v)
    if m2:
        return float(m2.group(1))
    return np.nan


def _parse_targeted_rr_mid(val) -> float:
    if pd.isna(val):
        return np.nan
    v = str(val).strip().upper().replace("RR", "").strip()
    if v.endswith("+"):
        return float(v.replace("+", "")) + 0.5
    m = re.match(r"(\d+\.?\d*)-(\d+\.?\d*)", v)
    if m:
        return (float(m.group(1)) + float(m.group(2))) / 2
    return np.nan


# ───────────────────────────── Growth tab ────────────────────────────────────
def _st_rerun_safe():
    try:
        st.rerun()
    except Exception:
        try:
            st.experimental_rerun()
        except Exception:
            pass


def _pnl_is_net(g: pd.DataFrame) -> bool:
    """MT5-synced journals already store P&L net of commission and swap —
    adding the cost columns again double-charges every trade."""
    return "Position ID" in g.columns or "MFE Efficiency %" in g.columns


def _pnl_series(g: pd.DataFrame):
    """Per-trade dollar result, net of costs (counted once)."""
    pnl = None
    for c in ("PnL", "PnL (USD)"):
        if c in g.columns:
            pnl = pd.to_numeric(g[c], errors="coerce")
            break
    if pnl is None:
        return None
    if not _pnl_is_net(g):
        for c in ("Commission", "Swap"):
            if c in g.columns:
                pnl = pnl.add(pd.to_numeric(g[c], errors="coerce").fillna(0.0),
                              fill_value=0.0)
    return pnl


def _balance_from_journal(g: pd.DataFrame):
    """Balance straight from the broker, when the journal carries one.

    Works for any trader, including people running several accounts through one
    journal: take the LATEST balance for each account and add them, so the
    figure is their real capital rather than whichever account synced last.
    Filtering to a single account naturally narrows it to that account.
    """
    col = next((c for c in ("Balance", "Account Balance", "Equity",
                            "Balance After", "Running Balance") if c in g.columns), None)
    if col is None:
        return None
    v = pd.to_numeric(g[col], errors="coerce")
    ok = v.notna() & (v > 0)
    if not bool(ok.any()):
        return None

    acct = next((c for c in ("Account", "Account Name", "Account ID")
                 if c in g.columns), None)
    dates = g["__Date"] if "__Date" in g.columns else None

    def _latest(idx):
        if dates is not None and dates.loc[idx].notna().any():
            return float(v.loc[dates.loc[idx].idxmax()])
        return float(v.loc[idx].iloc[-1])

    if acct is not None:
        labels = g.loc[ok, acct].astype(str).str.strip().replace({"": "\u2014", "nan": "\u2014"})
        groups = {a: pd.Index(idx) for a, idx in labels.groupby(labels).groups.items()}
        if len(groups) > 1:
            # NEVER sum balances: a prop combine beside a live account is not
            # extra capital. Prefer the nominated track-record account; failing
            # that, the account with the most trades in view.
            track = str(st.session_state.get("ea_track_account") or "")
            pick = track if track in groups else max(groups, key=lambda a: len(groups[a]))
            st.session_state["ea_bal_accounts"] = len(groups)
            st.session_state["ea_bal_account"] = pick
            try:
                return _latest(groups[pick])
            except Exception:
                pass
    st.session_state.pop("ea_bal_accounts", None)
    st.session_state.pop("ea_bal_account", None)
    return _latest(v[ok].index)


def _balance_track(g: pd.DataFrame, current: float):
    """Rebuild the balance behind every trade by walking your P&L back from today.
    Returns (series indexed like g, dict of month-start balances). Deposits and
    withdrawals aren't visible in trade data — those shift the whole track."""
    pnl = _pnl_series(g)
    if pnl is None or "__Date" not in g.columns or current is None or current <= 0:
        return None, {}
    d = pd.DataFrame({"dt": g["__Date"], "pnl": pnl.fillna(0.0)}).sort_values("dt")
    closing = current - (d["pnl"][::-1].cumsum()[::-1]) + d["pnl"]   # balance after each trade
    opening = closing - d["pnl"]                                     # balance before each trade
    starts = {}
    for per, sub in opening.groupby(d["dt"].dt.to_period("M")):
        starts[per] = float(sub.iloc[0])

    # Walking backwards is blind to deposits and withdrawals: fund the account
    # and every earlier month looks bigger than it was, which shrinks its
    # percentage. Where a month has enough full-stop losses, size tells us the
    # truth instead — a percentage-risk trader's stop IS a slice of that
    # month's balance, and no funding transfer can distort it.
    try:
        risk = float(st.session_state.get("ea_m_risk") or 0)
        if risk > 0:
            rr = pd.to_numeric(g.get("PnL_from_RR"), errors="coerce")
            full = (rr <= -0.85) & (rr >= -1.15) & pnl.notna() & (pnl < 0)
            if bool(full.any()):
                by_month = pnl[full].abs().groupby(g.loc[full, "__Date"].dt.to_period("M"))
                for per, vals in by_month:
                    if len(vals) >= 3:
                        implied = float(vals.median()) / (risk / 100.0)
                        if implied > 0:
                            starts[per] = implied
    except Exception:
        pass
    return opening.reindex(g.index), starts


def _period_pct(g: pd.DataFrame, mask, balance: float):
    """Return % for a slice of trades: net dollars (incl. costs) over the balance
    at the start of the month those trades sit in. None when it can't be known."""
    pnl = _pnl_series(g)
    if pnl is None or balance is None or balance <= 0 or "__Date" not in g.columns:
        return None
    _rr_raw = g.get("PnL_from_RR")
    if isinstance(_rr_raw, pd.DataFrame):          # duplicated column name
        _rr_raw = _rr_raw.iloc[:, 0]
    rr_ok = pd.to_numeric(_rr_raw, errors="coerce").notna()
    sel = mask & rr_ok
    if not bool(sel.any()):
        return 0.0
    _, starts = _balance_track(g, balance)
    per = g.loc[sel, "__Date"].min().to_period("M")
    base = starts.get(per, balance)
    if not base or base <= 0:
        return None
    return float(pnl[sel].fillna(0.0).sum()) / float(base) * 100.0


def _median_stop_usd(g: pd.DataFrame):
    """Median dollar loss on a full-stop (~-1R) trade, or None."""
    try:
        rr = pd.to_numeric(g.get("PnL_from_RR"), errors="coerce")
        pnl = None
        for c in ("PnL", "PnL (USD)"):
            if c in g.columns:
                pnl = pd.to_numeric(g[c], errors="coerce")
                break
        if pnl is None or rr is None:
            return None
        full = (rr <= -0.85) & (rr >= -1.15) & pnl.notna() & (pnl < 0)
        if int(full.sum()) >= 3:
            return float(pnl[full].abs().median())
    except Exception:
        pass
    return None


def _derive_balance(g: pd.DataFrame, assumed_risk_pct: float = 1.0) -> int:
    """Balance implied by your own stops: a full stop should cost 1% of account.
    Beats inventing a default, and the user can still override it in the editor."""
    med = _median_stop_usd(g)
    if med and med > 0 and assumed_risk_pct > 0:
        bal = med / (assumed_risk_pct / 100.0)
        return int(min(200000, max(500, round(bal / 100.0) * 100)))
    return 10000


def _risk_pct(g: pd.DataFrame) -> float:
    """Risk per trade as % of account. Your PLAN setting wins when you've set
    one — it is the ground truth for what an R is worth. Only when it's unset
    do we infer it from stop sizes (which deposits can distort, since a funding
    transfer is invisible in trade data)."""
    _set = st.session_state.get("ea_m_risk")
    if _set:
        try:
            _v = float(_set)
            if 0.01 <= _v <= 20:
                return _v
        except (TypeError, ValueError):
            pass
    # Unset: infer, but snap hard to the nearest standard policy. Traders risk
    # round numbers; the estimate is noisy enough that a raw 0.87% is more
    # likely a 1% plan measured through slippage than a real 0.87% policy.
    _m = _risk_pct_measured(g)
    for _q in (0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0):
        if abs(_m - _q) <= 0.2:
            return _q
    return _m


def _risk_pct_measured(g: pd.DataFrame) -> float:
    """Risk per trade as % of account, measured from real full-stop losses
    (|$| lost on a ~-1R trade / balance). Falls back to 1%."""
    bal = float(st.session_state.get("ea_m_bal", 10000) or 0)
    if bal <= 0:
        return 1.0
    try:
        rr = pd.to_numeric(g.get("PnL_from_RR"), errors="coerce")
        pnl = None
        for c in ("PnL", "PnL (USD)"):
            if c in g.columns:
                pnl = pd.to_numeric(g[c], errors="coerce")
                break
        if pnl is None:
            return 1.0
        full = (rr <= -0.85) & (rr >= -1.15) & pnl.notna() & (pnl < 0)
        if int(full.sum()) >= 3:
            # each stop against the balance BEHIND that trade — on a compounding
            # account, dividing old stops by today's balance understates risk
            try:
                opening, _ = _balance_track(g, bal)
                if opening is not None:
                    per = (pnl[full].abs() / opening[full].clip(lower=1.0)) * 100.0
                    per = per[per.notna()]
                    if len(per) >= 3:
                        _rp = float(max(0.05, min(10.0, per.median())))
                        # stops carry slippage/spread noise; a trader's risk POLICY
                        # is almost always a round number — snap when within a hair
                        for _q in (0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 2.5, 3.0):
                            if abs(_rp - _q) <= 0.035:
                                return _q
                        return _rp
            except Exception:
                pass
            return float(max(0.05, min(10.0, pnl[full].abs().median() / bal * 100.0)))
    except Exception:
        pass
    return 1.0


def _as_pct(r_value: float, risk_pct: float) -> float:
    """R expressed as % of account at the measured risk per trade."""
    return float(r_value) * float(risk_pct)


def _pct_txt(r_value: float, risk_pct: float, dp: int = 2) -> str:
    return f"{_as_pct(r_value, risk_pct):+.{dp}f}%"


def _digest_card(f: pd.DataFrame) -> None:
    """The reason to open the app: your weaknesses priced in R, worst first."""
    try:
        from edge_analysis.digest import findings
        fs = findings(f)
    except Exception:
        return
    if not fs:
        return
    import html as _h2
    with st.container(border=True):
        st.markdown('<div class="ea-card-anchor"></div>', unsafe_allow_html=True)
        _card_header("What needs work",
                     "Your three biggest leaks across the trades in view \u2014 "
                     "fix the top one first.")
        rows = []
        for i, f_ in enumerate(fs[:3], 1):
            _sev = "#ef4444" if i == 1 else ("#f59e0b" if i == 2 else "#94a3b8")
            _lab = _h2.escape(str(f_["label"]))
            _ev = _h2.escape(str(f_["evidence"]).split(" \u2014 ")[0])
            _bord = "" if i == 1 else "border-top:1px solid #eef0f6;"
            _stk = f_["stake"]
            rows.append(
                "<div style='display:flex;justify-content:space-between;"
                "align-items:flex-start;gap:16px;padding:13px 2px;" + _bord + "'>"
                "<div style='min-width:0;'>"
                "<div style='font-size:11px;font-weight:700;letter-spacing:0.07em;"
                f"color:{_sev};'>NO. {i}</div>"
                "<div style='font-size:16.5px;font-weight:800;color:#0f172a;"
                f"margin:1px 0 2px;'>{_lab}</div>"
                f"<div style='font-size:13px;color:#64748b;'>{_ev}</div></div>"
                "<div style='text-align:right;flex:0 0 auto;'>"
                "<div style='font-size:21px;font-weight:800;"
                f"color:{_sev};white-space:nowrap;'>&minus;{_stk:g}R</div>"
                "<div style='font-size:11px;font-weight:600;letter-spacing:0.06em;"
                "color:#94a3b8;'>AT STAKE</div></div></div>")
        st.markdown("".join(rows), unsafe_allow_html=True)


def _track_only(f: pd.DataFrame):
    """The month card is a TRACK RECORD: one account, one set of plan rules.
    A profit target, a max monthly loss and a trade cap belong to the account
    they were written for — carrying them onto a prop combine is meaningless.
    Returns (frame, account_label, other_accounts_in_view)."""
    acct = st.session_state.get("ea_track_account")
    if not acct or f is None or f.empty or "Account" not in f.columns:
        return f, None, 0
    col = f["Account"].astype(str).str.strip()
    others = int(col[col.notna() & ~col.isin(["", "nan", "None"])].nunique() - 1)
    sub = f[col == str(acct)]
    if sub.empty:
        return f, None, 0
    return sub, str(acct), max(0, others)


def _perf_settings(g: pd.DataFrame):
    """Monthly target / max-loss: auto from the data, editable via the pencil popover."""
    mr = g.set_index("__Date")["PnL_from_RR"].resample("MS").agg(["sum", "count"])
    mr = mr[mr["count"] > 0]
    if len(mr) >= 2:
        exp_t = float(pd.to_numeric(g["PnL_from_RR"], errors="coerce").dropna().mean() or 0)
        tpm = float(mr["count"].mean())
        sd_m = float(mr["sum"].std()) if len(mr) >= 3 else float(mr["sum"].abs().mean())
        auto_tgt = max(1.0, round(exp_t * tpm - 0.25 * (sd_m or 0.0), 1))
    else:
        auto_tgt = 5.0
    auto_stop = -6.0
    # Saved plan wins over the auto seed. Applied here because this runs before
    # the ✎ sliders are instantiated — the only moment Streamlit allows it.
    _saved = st.session_state.get("ea_mplan_saved")
    if _saved and not st.session_state.get("ea_plan_user_edited"):
        try:
            st.session_state["ea_m_tgt"] = float(_saved["t"])
            st.session_state["ea_m_stop"] = float(_saved["s"])
            if "c" in _saved:
                st.session_state["ea_m_cap"] = int(_saved["c"])
            if "r" in _saved:
                st.session_state["ea_m_risk"] = float(_saved["r"])
            if "b" in _saved:
                _rolled = st.session_state.get("ea_m_bal_rolled")
                if _rolled is not None:
                    st.session_state["ea_m_bal"] = float(_rolled)
                    st.session_state.pop("ea_m_bal_auto", None)
                elif _saved.get("d"):
                    # anchored and nothing banked since — the figure still holds
                    st.session_state["ea_m_bal"] = float(_saved["b"])
                    st.session_state.pop("ea_m_bal_auto", None)
                # else: a balance saved before anchoring existed. Trusting it
                # would freeze the account at whatever it was that day, so we
                # fall through to the figure derived from live position sizes.
        except (KeyError, TypeError, ValueError):
            pass
    if "ea_m_tgt" not in st.session_state:
        st.session_state["ea_m_tgt"] = float(auto_tgt)
    if "ea_m_stop" not in st.session_state:
        st.session_state["ea_m_stop"] = float(auto_stop)
    if "ea_m_cap" not in st.session_state:
        st.session_state["ea_m_cap"] = 12
    if "ea_m_risk" not in st.session_state:
        st.session_state["ea_m_risk"] = 1.0  # the standard, and what most plans say
    _from_journal = _balance_from_journal(g)
    if _from_journal:
        st.session_state["ea_m_bal"] = float(_from_journal)
        st.session_state["ea_m_bal_src"] = "from your journal"
    elif "ea_m_bal" not in st.session_state:
        st.session_state["ea_m_bal"] = float(_derive_balance(g))
        st.session_state["ea_m_bal_auto"] = True
        st.session_state["ea_m_bal_src"] = "from your stop sizes"
    st.session_state["ea_m_tgt"] = float(min(20.0, max(0.5, st.session_state["ea_m_tgt"])))
    st.session_state["ea_m_stop"] = float(min(-1.0, max(-15.0, st.session_state["ea_m_stop"])))
    st.session_state["ea_m_cap"] = int(min(40, max(1, st.session_state["ea_m_cap"])))
    st.session_state["ea_m_bal"] = float(min(1000000.0, max(1.0, float(st.session_state["ea_m_bal"]))))
    return (float(st.session_state["ea_m_tgt"]),
            float(st.session_state["ea_m_stop"]), auto_tgt)


def _perf_prep(f: pd.DataFrame):
    """Shared date/R prep for the Performance cards. Returns g with __Date."""
    if f is None or f.empty:
        return None
    g = f.copy()
    date_col = None
    if "Date" in g.columns:
        date_col = "Date"
    else:
        for c in g.columns:
            cl = str(c).strip().lower()
            if cl == "date" or "date" in cl or "time" in cl:
                date_col = c
                break
    if not date_col:
        return None
    g["__Date"] = g[date_col].astype(str).str.replace(r"\s*\(GMT.*\)$", "", regex=True)
    g["__Date"] = pd.to_datetime(g["__Date"], errors="coerce")
    g = g[g["__Date"].notna()].copy()
    if g.empty:
        return None
    try:
        if getattr(g["__Date"].dt, "tz", None) is not None:
            g["__Date"] = g["__Date"].dt.tz_localize(None)
    except Exception:
        pass
    try:
        from edge_analysis.ui.plan_tabs import get_tz_offset
        g["__Date"] = g["__Date"] + pd.Timedelta(hours=get_tz_offset(g))
    except Exception:
        pass
    if "PnL_from_RR" not in g.columns:
        rr_col = "Closed RR Num" if "Closed RR Num" in g.columns else "Closed RR"
        g["PnL_from_RR"] = g.get(rr_col, 0.0).fillna(0.0)
    return g.sort_values("__Date")


def _month_card(f: pd.DataFrame, styler) -> None:
    """Card 1 — This month: month R + week delta, target/stop pills, chart, progress, chips."""
    g = _perf_prep(f)
    if g is None:
        st.info("No dated rows yet. Add some trades or adjust filters.")
        return
    TGT_R, STOP_R, auto_tgt = _perf_settings(g)
    daily = g.set_index("__Date")["PnL_from_RR"].groupby(pd.Grouper(freq="D")).sum().dropna()
    now_p = pd.Timestamp.now().to_period("M")
    md = daily[daily.index.to_period("M") == now_p].cumsum().reset_index()
    md.columns = ["Date", "Cum"]
    cur = float(md["Cum"].iloc[-1]) if not md.empty else 0.0
    n_tr = int((g["__Date"].dt.to_period("M") == now_p).sum())
    wk_r = float(g.loc[g["__Date"] >= (pd.Timestamp.now() - pd.Timedelta(days=7)),
                       "PnL_from_RR"].sum())

    with st.container(border=True):
        st.markdown('<div class="ea-card-anchor"></div>', unsafe_allow_html=True)
        h1, h2 = st.columns([1.25, 1])
        with h1:
            wc = "#16a34a" if wk_r >= 0 else "#ef4444"
            arrow = "▲" if wk_r >= 0 else "▼"
            cc = "#16a34a" if cur >= 0 else "#ef4444"
            _rp = _risk_pct(g)
            _bal_disp = float(st.session_state.get("ea_m_bal", 0) or 0)
            # No "measured risk" claim on the hero: it divides each stop's
            # realised loss (slippage and partial fills included) by a balance
            # reconstructed from P&L alone — which a deposit silently breaks.
            # A number we can't stand behind is worse than no number.
            _risk_note = ""
            _roll = st.session_state.get("ea_m_bal_rolled_from")
            _src = st.session_state.get("ea_m_bal_src")
            _naccts = st.session_state.get("ea_bal_accounts")
            if _naccts and _naccts > 1:
                _who = str(st.session_state.get("ea_bal_account") or "").split("@")[0][:20]
                _bal_note = f" \u2014 {_who}"
            elif _roll:
                _bal_note = (f" (your ${_roll[0]:,.0f} from {_roll[1]} plus "
                             f"{_roll[2]} trade{'s' if _roll[2] != 1 else ''} since)")
            elif _src and st.session_state.get("ea_m_bal_auto"):
                _bal_note = " (" + str(_src) + " \u2014 set it in \u270e)"
            else:
                _bal_note = ""
            _mtd_pct = _period_pct(g, g["__Date"].dt.to_period("M") == now_p, _bal_disp)
            _wk_pct = _period_pct(
                g, g["__Date"] >= (pd.Timestamp.now() - pd.Timedelta(days=7)), _bal_disp)
            _cur_txt = f"{_mtd_pct:+.2f}%" if _mtd_pct is not None else _pct_txt(cur, _rp)
            _wk_txt = f"{_wk_pct:+.2f}%" if _wk_pct is not None else _pct_txt(wk_r, _rp)
            st.markdown(
                f"<div style='font-size:12px;font-weight:700;letter-spacing:0.08em;"
                f"color:#94a3b8;'>{pd.Timestamp.now().strftime('%B').upper()}</div>"
                f"<div style='font-size:38px;font-weight:800;color:{cc};line-height:1.1;'>"
                f"{_cur_txt}"
                f"<span style='font-size:15px;font-weight:700;color:{wc};margin-left:14px;'>"
                f"{arrow} {_wk_txt} this week</span></div>"
                f"<div style='font-size:12.5px;color:#8a93a6;margin-top:2px;'>"
                f"{cur:+,.1f}R \u00b7 {n_tr} trades \u00b7 risk {_rp:.2f}%/trade on "
                f"${_bal_disp:,.0f}{_bal_note}{_risk_note}</div>",
                unsafe_allow_html=True)
        with h2:
            p1, p2 = st.columns([2.6, 1])
            with p1:
                st.markdown(
                    "<div style='display:flex;gap:8px;justify-content:flex-end;flex-wrap:wrap;"
                    "margin-top:6px;'>"
                    f"<span style='background:#e2f5e9;color:#14532d;font-weight:800;font-size:13.5px;"
                    f"border-radius:999px;padding:7px 14px;'>Target&nbsp; "
                    f"{_as_pct(TGT_R, _rp):+.1f}%&nbsp;<span style='font-weight:600;opacity:0.7;'>"
                    f"({TGT_R:.1f}R)</span></span>"
                    f"<span style='background:#fde8e8;color:#7f1d1d;font-weight:800;font-size:13.5px;"
                    f"border-radius:999px;padding:7px 14px;'>Max loss&nbsp; "
                    f"{_as_pct(STOP_R, _rp):+.1f}%&nbsp;<span style='font-weight:600;opacity:0.7;'>"
                    f"({STOP_R:.1f}R)</span></span>"
                    "</div>"
                    "<div style='text-align:right;font-size:11.5px;color:#94a3b8;margin-top:5px;'>"
                    "auto from your data · edit →</div>",
                    unsafe_allow_html=True)
            with p2:
                try:
                    pop = st.popover("✎")
                except Exception:
                    pop = st.expander("✎")
                def _plan_dirty():
                    st.session_state["ea_mplan_dirty"] = True
                    st.session_state["ea_plan_user_edited"] = True

                with pop:
                    def _preset(t_, s_, c_):
                        st.session_state["ea_m_tgt"] = float(t_)
                        st.session_state["ea_m_stop"] = float(s_)
                        st.session_state["ea_m_cap"] = int(c_)
                        st.session_state["ea_mplan_dirty"] = True
                        st.session_state["ea_plan_user_edited"] = True
                    st.markdown("<div style='font-size:11px;font-weight:700;"
                                "letter-spacing:0.06em;color:#94a3b8;'>PICK A PACE</div>",
                                unsafe_allow_html=True)
                    pc1, pc2 = st.columns(2)
                    with pc1:
                        st.button(f"Auto ({auto_tgt:+.0f}R)", key="pp_auto",
                                  use_container_width=True,
                                  on_click=_preset, args=(auto_tgt, -6.0, 12))
                        st.button("Standard 5% (+5R)", key="pp_std",
                                  use_container_width=True,
                                  on_click=_preset, args=(5.0, -6.0, 12))
                    with pc2:
                        st.button("Steady (+3R)", key="pp_steady",
                                  use_container_width=True,
                                  on_click=_preset, args=(3.0, -4.0, 8))
                        st.button("Aggressive (+8R)", key="pp_aggr",
                                  use_container_width=True,
                                  on_click=_preset, args=(8.0, -8.0, 20))
                    st.markdown("<div style='font-size:11px;font-weight:700;"
                                "letter-spacing:0.06em;color:#94a3b8;margin-top:6px;'>"
                                "FINE-TUNE</div>", unsafe_allow_html=True)
                    with st.form("plan_form", border=False):
                        st.slider("Monthly target (R)", min_value=0.5, max_value=20.0,
                                  value=float(st.session_state.get("ea_m_tgt", 5.0)),
                                  step=0.5, format="%.1f", key="ea_m_tgt")
                        st.slider("Max monthly loss (R)", min_value=-15.0, max_value=-1.0,
                                  value=float(st.session_state.get("ea_m_stop", -6.0)),
                                  step=0.5, format="%.1f", key="ea_m_stop")
                        st.slider("Trades per month", min_value=1, max_value=40,
                                  value=int(st.session_state.get("ea_m_cap", 12)),
                                  step=1, key="ea_m_cap")
                        st.slider("Risk per trade (%)", min_value=0.1, max_value=5.0,
                                  value=float(st.session_state.get("ea_m_risk", 1.0)),
                                  step=0.05, format="%.2f", key="ea_m_risk",
                                  help="What one R is worth. Your plan's number, "
                                       "not a guess from past stop sizes.")
                        st.number_input("Account balance ($) — today", min_value=1.0,
                                        max_value=1000000.0, step=50.0, format="%.2f",
                                        value=float(st.session_state.get("ea_m_bal", 10000.0)),
                                        key="ea_m_bal",
                                        help="Today's balance. Past months use the balance "
                                             "rebuilt from your own trade P&L, so each month "
                                             "is a true return. Deposits/withdrawals shift it.")
                        st.form_submit_button("Save", type="primary", on_click=_plan_dirty,
                                              use_container_width=True)

        if md.empty:
            st.info("No trades this month yet.")
        else:
            firstd = pd.Timestamp(now_p.start_time.date())
            lastd = pd.Timestamp(now_p.end_time.date())
            ylo = min(STOP_R - 1.5, float(md["Cum"].min()) - 1)
            yhi = max(TGT_R + 1.5, float(md["Cum"].max()) + 1)
            ysc = alt.Scale(domain=[ylo, yhi])
            xsc = alt.Scale(domain=[firstd.isoformat(), lastd.isoformat()])
            xax = alt.Axis(format="%d", labelColor="#94a3b8", grid=False, tickCount=10)
            vals = _to_alt_values(md[["Date", "Cum"]])
            lays = []
            for yv, col in ((0.0, "#cbd5e1"), (TGT_R, "#16a34a"), (STOP_R, "#ef4444")):
                lays.append(alt.Chart(alt.Data(values=[{"y": yv}]))
                            .mark_rule(color=col, strokeDash=[5, 5] if yv else [2, 3],
                                       strokeWidth=2 if yv else 1.5)
                            .encode(y=alt.Y("y:Q", title=None)))
            base = alt.Chart(alt.Data(values=vals))
            ln = base.mark_line(color="#4800ff", strokeWidth=3).encode(
                x=alt.X("Date:T", title=None, scale=xsc, axis=xax),
                y=alt.Y("Cum:Q", title=None, scale=ysc))
            pt = (alt.Chart(alt.Data(values=[vals[-1]]))
                  .mark_circle(color="#4800ff", size=110, stroke="#ffffff", strokeWidth=2)
                  .encode(x=alt.X("Date:T", title=None, scale=xsc),
                          y=alt.Y("Cum:Q", title=None, scale=ysc)))
            st.altair_chart(styler(alt.layer(*lays, ln, pt).properties(height=290)),
                            use_container_width=True)

            # One basis for the month: the real money figure in the hero. The
            # plan's target/stop are converted at the planned risk, so the bar
            # can't disagree with the number directly above it.
            _now_pct = _mtd_pct if _mtd_pct is not None else _as_pct(cur, _rp)
            _tgt_pct = _as_pct(TGT_R, _rp)
            _stop_pct = _as_pct(STOP_R, _rp)
            if cur >= 0:
                bar_title = "PROGRESS TO TARGET"
                barw = max(0.0, min(1.0, _now_pct / _tgt_pct)) if _tgt_pct > 0 else 0.0
                barc = "#16a34a"
                sub = (f"{_now_pct:+.2f}% now \u00b7 "
                       f"{max(0.0, _tgt_pct - _now_pct):.2f}% to go")
            else:
                bar_title = "STOP USED"
                barw = max(0.0, min(1.0, _now_pct / _stop_pct)) if _stop_pct < 0 else 0.0
                barc = "#ef4444"
                sub = (f"{_now_pct:+.2f}% now \u00b7 {barw * 100:.0f}% of the "
                       f"{_stop_pct:+.1f}% stop used \u00b7 "
                       f"{abs(_now_pct - _stop_pct):.2f}% of room left")
            st.markdown(
                f"<div style='font-size:11px;font-weight:700;letter-spacing:0.06em;"
                f"color:#94a3b8;margin-top:2px;'>{bar_title}</div>"
                f"<div style='background:#f1f5f9;border-radius:7px;height:13px;margin:7px 0 6px;'>"
                f"<div style='width:{barw * 100:.1f}%;height:13px;border-radius:7px;"
                f"background:{barc};'></div></div>"
                f"<div style='font-size:13px;color:#64748b;'>{sub}</div>",
                unsafe_allow_html=True)

            maxdd = float((md["Cum"].cummax() - md["Cum"]).max())
            cap = int(st.session_state.get("ea_m_cap", 12))
            pace_c = "#ef4444" if n_tr > cap else "#0f172a"
            chips = [("TO TARGET", f"{max(0.0, _tgt_pct - _now_pct):.2f}%",
                      "#16a34a" if _now_pct >= _tgt_pct else "#0f172a"),
                     ("MAX DRAWDOWN", f"-{_as_pct(maxdd, _rp):.2f}%",
                      "#ef4444" if maxdd > 0 else "#64748b"),
                     ("STOP ROOM", f"{abs(_now_pct - _stop_pct):.2f}%",
                      "#ef4444" if cur - STOP_R < 2 else "#0f172a"),
                     ("TRADES · PACE", f"{n_tr} of {cap}" + (" ⚠" if n_tr > cap else ""),
                      "#ef4444" if n_tr > cap else pace_c)]
            st.markdown(
                "<div style='display:flex;gap:12px;flex-wrap:wrap;margin-top:12px;'>" + "".join(
                    f"<div style='flex:1;min-width:140px;background:#f8f9fc;border-radius:12px;"
                    f"padding:12px 14px;'>"
                    f"<div style='font-size:11px;font-weight:600;letter-spacing:0.06em;"
                    f"color:#94a3b8;'>{k}</div>"
                    f"<div style='font-size:21px;font-weight:800;color:{c};'>{v}</div></div>"
                    for k, v, c in chips) + "</div>", unsafe_allow_html=True)


def _alltime_card(f: pd.DataFrame, styler) -> None:
    """Card 3 — All time: curve with R/$ + bucket in the header, one unified stat row."""
    g = _perf_prep(f)
    if g is None:
        return
    _ucol = next((c for c in ("PnL (USD)", "PnL") if c in g.columns), None)
    usd = pd.to_numeric(g.get(_ucol), errors="coerce") if _ucol else None
    has_usd = usd is not None and usd.notna().any()
    with st.container(border=True):
        st.markdown('<div class="ea-card-anchor"></div>', unsafe_allow_html=True)
        h1, h2, h3 = st.columns([2.2, 0.9, 1])
        with h1:
            st.markdown("<div style='font-size:21px;font-weight:800;color:#0f172a;"
                        "margin-top:4px;'>All time</div>", unsafe_allow_html=True)
        with h2:
            view = "R"
            _bal = float(st.session_state.get("ea_m_bal", 10000) or 0)
            _units = (["%", "$", "R"] if (has_usd and _bal > 0)
                      else (["$", "R"] if has_usd else ["R"]))
            if len(_units) > 1:
                view = st.radio("Units", _units, horizontal=True, key="eq_units",
                                label_visibility="collapsed") or _units[0]
        with h3:
            bucket = st.selectbox("Time Bucket", ["Day", "Week", "Month"], index=2,
                                  key="growth_bucket", label_visibility="collapsed")
        gi = g.set_index("__Date")
        if view == "%" and has_usd and _bal > 0:
            ser = pd.Series((usd.values / _bal) * 100.0, index=g["__Date"]).dropna()
            unit = "%"
        elif view == "$" and has_usd:
            ser = pd.Series(usd.values, index=g["__Date"]).dropna()
            unit = "$"
        else:
            ser = gi["PnL_from_RR"]
            unit = "R"
        TGT_R = float(st.session_state.get("ea_m_tgt", 5.0))
        STOP_R = float(st.session_state.get("ea_m_stop", -6.0))
        if bucket == "Month":
            mo = ser.resample("MS").sum()
            mo = mo[ser.resample("MS").size() > 0]
            rows = [{"Month": ts.strftime("%b"), "Net": round(float(v), 2),
                     "Colour": "good" if v >= 0 else "bad",
                     "Lab": (f"{v:+.1f}R" if unit == "R"
                             else (f"{v:+.2f}%" if unit == "%"
                                   else f"{'-' if v < 0 else ''}${abs(v):,.0f}"))}
                    for ts, v in mo.items()]
            order = [r["Month"] for r in rows]
            _rp_dom = _risk_pct(g)
            _lo_ref = (STOP_R if unit == "R" else
                       (_as_pct(STOP_R, _rp_dom) if unit == "%" else 0.0))
            _hi_ref = (TGT_R if unit == "R" else
                       (_as_pct(TGT_R, _rp_dom) if unit == "%" else 0.0))
            lo = min(min((r["Net"] for r in rows), default=0.0), _lo_ref)
            hi = max(max((r["Net"] for r in rows), default=0.0), _hi_ref)
            span = max(hi - lo, 1.0)
            dom = [lo - span * 0.18, hi + span * 0.24]
            base = alt.Chart(alt.Data(values=rows))
            xenc = alt.X("Month:N", sort=order, title=None,
                         axis=alt.Axis(labelAngle=0, labelFontSize=13,
                                       labelColor="#0f172a", ticks=False, domain=False))
            bars = base.mark_bar(size=44, cornerRadiusTopLeft=7, cornerRadiusTopRight=7).encode(
                x=xenc,
                y=alt.Y("Net:Q", title=None, scale=alt.Scale(domain=dom),
                        axis=alt.Axis(format="+.0f", grid=True, gridColor="#eef0f5",
                                      labelColor="#94a3b8")),
                color=alt.Color("Colour:N", legend=None,
                                scale=alt.Scale(domain=["good", "bad"],
                                                range=["#16a34a", "#ef4444"])),
                tooltip=[alt.Tooltip("Month:N"), alt.Tooltip("Net:Q", format="+.2f")])
            txt = base.mark_text(dy=-12, fontSize=12, fontWeight="bold", color="#334155").encode(
                x=xenc, y=alt.Y("Net:Q", scale=alt.Scale(domain=dom)), text="Lab:N")
            lays = [bars, txt,
                    alt.Chart(alt.Data(values=[{"y": 0}]))
                    .mark_rule(color="#cbd5e1", strokeWidth=1.5).encode(y=alt.Y("y:Q", title=None))]
            _rp_a = _risk_pct(g)
            _tgt_line = TGT_R if unit == "R" else (_as_pct(TGT_R, _rp_a) if unit == "%" else None)
            _stop_line = STOP_R if unit == "R" else (_as_pct(STOP_R, _rp_a) if unit == "%" else None)
            if _tgt_line is not None:
                lays.append(alt.Chart(alt.Data(values=[{"y": _tgt_line}]))
                            .mark_rule(color="#16a34a", strokeDash=[6, 5], strokeWidth=2)
                            .encode(y=alt.Y("y:Q", title=None)))
                lays.append(alt.Chart(alt.Data(values=[{"y": _stop_line}]))
                            .mark_rule(color="#ef4444", strokeDash=[6, 5], strokeWidth=2)
                            .encode(y=alt.Y("y:Q", title=None)))
            st.altair_chart(styler(alt.layer(*lays).properties(height=300)),
                            use_container_width=True)
            if unit == "R":
                st.caption(f"Each bar = the month's net result \u00b7 green dash = "
                           f"{TGT_R:+.1f}R target \u00b7 red dash = {STOP_R:+.0f}R max loss.")
            elif unit == "%":
                st.caption(f"Each bar = the month's net result as % of account \u00b7 green dash "
                           f"= {_as_pct(TGT_R, _rp_a):+.1f}% target \u00b7 red dash = "
                           f"{_as_pct(STOP_R, _rp_a):+.1f}% max loss \u00b7 measured risk "
                           f"{_rp_a:.2f}%/trade.")
        else:
            freq = {"Day": "D", "Week": "W-MON"}[bucket]
            eq = ser.resample(freq).sum().cumsum().reset_index()
            eq.columns = ["Bucket", "Cum"]
            eq = eq[eq["Bucket"].notna()]
            vals = _to_alt_values(eq)
            if vals:
                xenc = alt.X("Bucket:T", title=None,
                             axis=alt.Axis(format="%d %b", labelAngle=-45,
                                           labelColor="#94a3b8", labelOverlap="greedy",
                                           tickCount=min(10, len(eq))))
                ytitle = "Cumulative " + unit
                area = (alt.Chart(alt.Data(values=vals)).mark_area(opacity=0.12, color="#4800ff")
                        .encode(x=xenc, y=alt.Y("Cum:Q", title=ytitle,
                                                scale=alt.Scale(padding=14))))
                line = (alt.Chart(alt.Data(values=vals)).mark_line(strokeWidth=2, color="#4800ff")
                        .encode(x=xenc, y=alt.Y("Cum:Q", title=None, scale=alt.Scale(padding=14))))
                st.altair_chart(styler(alt.layer(area, line).properties(height=290)),
                                use_container_width=True)
                st.caption("Cumulative curve \u00b7 switch the bucket to Month to see each month "
                           "against your target and max loss.")
            else:
                st.info("Not enough data for the equity chart.")

        rrs = pd.to_numeric(g["PnL_from_RR"], errors="coerce").dropna()
        n = int(len(rrs))
        wins = rrs[rrs > 0.15]
        win_pct = 100.0 * len(wins) / n if n else 0.0
        avg_win = float(wins.mean()) if len(wins) else float("nan")
        expc = float(rrs.mean()) if n else float("nan")
        gw = float(rrs[rrs > 0].sum()); gl = float(abs(rrs[rrs < 0].sum()))
        pf = gw / gl if gl > 0 else float("nan")
        net = float(rrs.sum())
        chips = [("NET", f"{net:+.1f}R", "#16a34a" if net >= 0 else "#ef4444"),
                 ("TRADES", f"{n}", "#0f172a"),
                 ("WIN", f"{win_pct:.0f}%", "#0f172a"),
                 ("AVG WIN", "—" if avg_win != avg_win else f"{avg_win:.2f}R", "#4800ff"),
                 ("EXPECTANCY", "—" if expc != expc else f"{expc:+.2f}R",
                  "#16a34a" if expc == expc and expc >= 0 else "#ef4444"),
                 ("PROFIT FACTOR", "—" if pf != pf else f"{pf:.2f}",
                  "#16a34a" if pf == pf and pf >= 1 else "#ef4444")]
        if has_usd:
            net_u = float(usd.dropna().sum())
            chips.append(("NET $", f"{'-' if net_u < 0 else ''}${abs(net_u):,.0f}",
                          "#16a34a" if net_u >= 0 else "#ef4444"))
        st.markdown(
            "<div style='display:flex;gap:10px;flex-wrap:wrap;margin-top:10px;'>" + "".join(
                f"<div style='flex:1;min-width:118px;background:#f8f9fc;border-radius:12px;"
                f"padding:11px 13px;'>"
                f"<div style='font-size:10.5px;font-weight:600;letter-spacing:0.05em;"
                f"color:#94a3b8;'>{k}</div>"
                f"<div style='font-size:19px;font-weight:800;color:{c};'>{v}</div></div>"
                for k, v, c in chips) + "</div>", unsafe_allow_html=True)


# ── Account comparison cards ──────────────────────────────────────────────────
def _account_comparison_tab(f: pd.DataFrame, styler):
    # fully silent when there is nothing to compare
    if f is not None and not f.empty:
        _lm = {str(c).strip().lower(): c for c in f.columns}
        _ac = _lm.get("account") or _lm.get("accounts") or _lm.get("account name")
        if _ac is not None:
            _vals = f[_ac].astype(str).str.strip()
            _vals = _vals[~_vals.isin(["", "nan", "NaN", "None"])]
            if _vals.nunique() <= 1:
                return
    st.markdown('<div class="section">', unsafe_allow_html=True)
    st.markdown("### Account Comparison")

    if f is None or f.empty:
        st.info("No trades for current filters.")
        st.markdown("</div>", unsafe_allow_html=True)
        return

    lower_map = {str(c).strip().lower(): c for c in f.columns}
    acct_col = lower_map.get("account") or lower_map.get("accounts") or lower_map.get("account name")
    if acct_col is None:
        pass
        st.markdown("</div>", unsafe_allow_html=True)
        return

    g = f.copy()
    g["__Account"] = g[acct_col].astype(str).str.strip()
    g = g[~g["__Account"].isin(["", "nan", "NaN", "None"])]
    if g.empty:
        pass
        st.markdown("</div>", unsafe_allow_html=True)
        return
    if g["__Account"].nunique() <= 1:
        st.caption("Only one account in this slice — nothing to compare.")
        st.markdown("</div>", unsafe_allow_html=True)
        return

    counted = g[g["Outcome"].isin(["Win", "BE", "Loss"])]
    if counted.empty:
        pass
        st.markdown("</div>", unsafe_allow_html=True)
        return

    rows = []
    for acct, grp in counted.groupby("__Account"):
        r = outcome_rates_from(grp)
        net_rr, avg_rr = _rr_stats(grp)
        rows.append(dict(
            account=acct,
            trades=len(grp),
            win_rate=r["win_rate"],
            be_rate=r["be_rate"],
            loss_rate=r["loss_rate"],
            net_pnl=net_rr or 0.0,
            avg_rr=round(avg_rr, 2) if avg_rr is not None else 0.0,
        ))

    if not rows:
        pass
        st.markdown("</div>", unsafe_allow_html=True)
        return

    per_row = 3
    for i in range(0, len(rows), per_row):
        chunk = rows[i: i + per_row]
        cols = st.columns(len(chunk))
        for col, row in zip(cols, chunk):
            net_fmt = f"+{row['net_pnl']:.2f}R" if row["net_pnl"] >= 0 else f"{row['net_pnl']:.2f}R"
            with col:
                st.markdown(f"""
                    <div class='kpi'>
                      <div class='label'>{row['account']}</div>
                      <div class='value' style='color:#4800ff'>{row['trades']}</div>
                      <div class='muted'>Trades</div>
                      <div style='margin-top:8px'></div>
                      <div class='muted'>Win % &nbsp;<b>{row['win_rate']:.1f}%</b></div>
                      <div class='muted'>BE % &nbsp;<b>{row['be_rate']:.1f}%</b></div>
                      <div class='muted'>Loss % &nbsp;<b>{row['loss_rate']:.1f}%</b></div>
                      <div style='margin-top:8px'></div>
                      <div class='muted'>Net PnL &nbsp;<b style='color:#4800ff'>{net_fmt}</b></div>
                      <div class='muted'>Avg RR &nbsp;<b>{row['avg_rr']:.2f}R</b></div>
                    </div>""", unsafe_allow_html=True)

    if rows:
        best_acct = max(rows, key=lambda r: r["win_rate"])
        worst_acct = min(rows, key=lambda r: r["win_rate"])
        net_total = sum(r["net_pnl"] for r in rows)
        if len(rows) > 1 and best_acct["account"] != worst_acct["account"]:
            _insight_box(
                f"<b>{best_acct['account']}</b> leads with <b>{best_acct['win_rate']:.1f}%</b> win rate "
                f"and <b>{best_acct['net_pnl']:+.1f}R</b> net. "
                f"<b>{worst_acct['account']}</b> trails at <b>{worst_acct['win_rate']:.1f}%</b>. "
                f"Combined net across all accounts: <b>{net_total:+.1f}R</b>.")
        elif rows:
            _insight_box(
                f"<b>{rows[0]['account']}</b> — <b>{rows[0]['win_rate']:.1f}%</b> win rate, "
                f"<b>{rows[0]['net_pnl']:+.1f}R</b> net PnL across {rows[0]['trades']} trades.")

    st.markdown("</div>", unsafe_allow_html=True)


# ── Early Close Analysis ──────────────────────────────────────────────────────
def _early_close_tab(df: pd.DataFrame, styler):
    st.markdown('<div class="section">', unsafe_allow_html=True)

    EC_BE  = "Early Close (Ended up being a BE)"
    EC_WIN = "Early Close (Ended up being a win)"

    if df is None or df.empty or "Result" not in df.columns:
        pass
        st.markdown("</div>", unsafe_allow_html=True)
        return

    ec = df[df["Result"].isin([EC_BE, EC_WIN])].copy()

    if ec.empty:
        pass
        st.markdown("</div>", unsafe_allow_html=True)
        return

    ec["__closed_mid"]   = ec["Closed RR"].apply(_parse_closed_rr_mid)
    ec["__targeted_mid"] = ec["Targeted RR"].apply(_parse_targeted_rr_mid)

    be_group  = ec[ec["Result"] == EC_BE].copy()
    win_group = ec[ec["Result"] == EC_WIN].copy()

    be_group["__rr_diff"] = be_group["__closed_mid"]
    win_group["__rr_diff"] = win_group["__closed_mid"] - win_group["__targeted_mid"]

    be_n          = len(be_group)
    win_n         = len(win_group)
    be_captured   = float(be_group["__closed_mid"].sum())
    be_net        = float(be_group["__rr_diff"].sum())
    be_avg        = float(be_group["__rr_diff"].mean()) if be_n > 0 else 0.0
    win_captured  = float(win_group["__closed_mid"].sum())
    win_target    = float(win_group["__targeted_mid"].sum())
    win_left      = float(win_group["__rr_diff"].sum())
    win_avg       = float(win_group["__rr_diff"].mean()) if win_n > 0 else 0.0
    net_impact    = be_net + win_left
    efficiency    = (win_captured / win_target * 100) if win_target > 0 else 0.0

    st.markdown("### Early Close Profitability")
    st.caption(
        "How much R your early close decisions saved vs. BE trades, "
        "and how much you left on the table vs. win trades."
    )

    m1, m2, m3, m4, m5 = st.columns(5)
    with m1:
        st.markdown(f"<div class='kpi'><div class='label'>Early Close Trades</div>"
                    f"<div class='value' style='color:#4800ff'>{be_n + win_n}</div>"
                    f"<div class='muted'>{be_n} BE · {win_n} win</div></div>", unsafe_allow_html=True)
    with m2:
        st.markdown(f"<div class='kpi'><div class='label'>Saved vs BE</div>"
                    f"<div class='value' style='color:#4800ff'>+{be_net:.1f}R</div>"
                    f"<div class='muted'>avg +{be_avg:.1f}R per trade</div></div>", unsafe_allow_html=True)
    with m3:
        st.markdown(f"<div class='kpi'><div class='label'>Left on Table</div>"
                    f"<div class='value' style='color:#4800ff'>{win_left:.1f}R</div>"
                    f"<div class='muted'>of {win_target:.1f}R targeted</div></div>", unsafe_allow_html=True)
    with m4:
        net_color = "#4800ff"
        st.markdown(f"<div class='kpi'><div class='label'>Net EC Impact</div>"
                    f"<div class='value' style='color:{net_color}'>{net_impact:+.1f}R</div>"
                    f"<div class='muted'>saved minus left on table</div></div>", unsafe_allow_html=True)
    with m5:
        st.markdown(f"<div class='kpi'><div class='label'>Win-Group Efficiency</div>"
                    f"<div class='value' style='color:#4800ff'>{efficiency:.0f}%</div>"
                    f"<div class='muted'>{win_captured:.1f}R of {win_target:.1f}R captured</div></div>", unsafe_allow_html=True)

    st.divider()

    # ── Cumulative R chart: your system vs held to full TP/BE ─────────────────
    ec_chart = (
        ec[["__closed_mid", "__targeted_mid", "Result", "Closed RR", "Targeted RR"]]
        .dropna(subset=["__closed_mid", "__targeted_mid"])
        .reset_index(drop=True)
        .reset_index()
        .rename(columns={"index": "i"})
    )
    ec_chart["Trade"] = ec_chart["i"] + 1

    # Actual = what was captured
    ec_chart["actual"] = ec_chart["__closed_mid"]

    # Hypothetical = 0R if BE group, full targeted if win group
    ec_chart["hypo"] = ec_chart.apply(
        lambda r: 0.0 if EC_BE in str(r["Result"]) else r["__targeted_mid"], axis=1
    )

    ec_chart["actual_cum"] = ec_chart["actual"].cumsum()
    ec_chart["hypo_cum"]   = ec_chart["hypo"].cumsum()

    actual_vals = _to_alt_values(
        ec_chart[["Trade", "actual_cum", "Closed RR", "Targeted RR", "Result"]]
        .rename(columns={"actual_cum": "Cumulative R"})
        .assign(Series="Your early close system")
    )
    hypo_vals = _to_alt_values(
        ec_chart[["Trade", "hypo_cum", "Closed RR", "Targeted RR", "Result"]]
        .rename(columns={"hypo_cum": "Cumulative R"})
        .assign(Series="Held to full TP / BE")
    )

    if actual_vals and hypo_vals:
        color_scale = alt.Scale(
            domain=["Your early close system", "Held to full TP / BE"],
            range=["#4800ff", "#e07b00"],
        )
        base_actual = alt.Chart(alt.Data(values=actual_vals))
        base_hypo   = alt.Chart(alt.Data(values=hypo_vals))

        line_actual = (
            base_actual.mark_line(strokeWidth=2.5, point=alt.OverlayMarkDef(size=30))
            .encode(
                x=alt.X("Trade:Q", axis=alt.Axis(title="Early close trade #", tickMinStep=1)),
                y=alt.Y("Cumulative R:Q", axis=alt.Axis(title="Cumulative R")),
                color=alt.Color("Series:N", scale=color_scale, legend=alt.Legend(title=None, orient="top-left")),
                tooltip=[
                    alt.Tooltip("Trade:Q", title="Trade #"),
                    alt.Tooltip("Series:N"),
                    alt.Tooltip("Cumulative R:Q", title="Cumulative R", format=".1f"),
                    alt.Tooltip("Closed RR:N", title="Closed RR"),
                    alt.Tooltip("Targeted RR:N", title="Targeted RR"),
                    alt.Tooltip("Result:N"),
                ],
            )
        )
        line_hypo = (
            base_hypo.mark_line(strokeWidth=2.5, strokeDash=[6, 3], point=alt.OverlayMarkDef(size=30))
            .encode(
                x=alt.X("Trade:Q"),
                y=alt.Y("Cumulative R:Q"),
                color=alt.Color("Series:N", scale=color_scale, legend=alt.Legend(title=None, orient="top-left")),
                tooltip=[
                    alt.Tooltip("Trade:Q", title="Trade #"),
                    alt.Tooltip("Series:N"),
                    alt.Tooltip("Cumulative R:Q", title="Cumulative R", format=".1f"),
                    alt.Tooltip("Closed RR:N", title="Closed RR"),
                    alt.Tooltip("Targeted RR:N", title="Targeted RR"),
                    alt.Tooltip("Result:N"),
                ],
            )
        )

        st.altair_chart(
            styler((line_actual + line_hypo).properties(height=300).resolve_scale(color="shared")),
            use_container_width=True,
        )

        final_actual = float(ec_chart["actual_cum"].iloc[-1])
        final_hypo   = float(ec_chart["hypo_cum"].iloc[-1])
        diff         = final_actual - final_hypo
        diff_str     = f"+{diff:.1f}R" if diff >= 0 else f"{diff:.1f}R"
        st.caption(
            f"Solid = what you captured. Dashed = what holding to full TP/BE would have returned. "
            f"Net difference: **{diff_str}** across {len(ec_chart)} early close trades."
        )

    st.divider()

    if net_impact > 0:
        verdict_bg     = "#f0ebff"
        verdict_border = "#4800ff"
        verdict_icon   = "✓"
        verdict_body   = (
            f"Your early close system is <b>net positive</b> at <b>+{net_impact:.1f}R</b>. "
            f"Saving {be_net:.1f}R from BE trades outweighs the {abs(win_left):.1f}R left on "
            f"the table from win trades. Win-group efficiency: <b>{efficiency:.0f}%</b> of "
            f"targeted R captured."
        )
    else:
        verdict_bg     = "#fff4e6"
        verdict_border = "#e07b00"
        verdict_icon   = "!"
        verdict_body   = (
            f"Your early close system is <b>net negative</b> at <b>{net_impact:.1f}R</b>. "
            f"The {abs(win_left):.1f}R left on the table from win trades outweighs the "
            f"{be_net:.1f}R saved from BE trades. "
            f"Win-group efficiency: <b>{efficiency:.0f}%</b> of targeted R captured."
        )

    st.markdown(
        f"""<div style="
            background:{verdict_bg};
            border-left:4px solid {verdict_border};
            border-radius:6px;
            padding:14px 18px;
            font-size:14px;
            line-height:1.7;
        "><b>{verdict_icon}&nbsp;</b>{verdict_body}</div>""",
        unsafe_allow_html=True,
    )

    if win_n > 0 and efficiency < 70:
        _insight_box(
            f"You're capturing only <b>{efficiency:.0f}%</b> of targeted R on winning early closes. "
            f"Consider letting more winners run to weak structure before managing.", "warn")
    elif be_n > 0 and be_avg > 1.5:
        _insight_box(
            f"Early close saves averaging <b>+{be_avg:.1f}R</b> per BE trade — "
            f"meaningful edge. Keep logging so the pattern stays measurable.", "good")

    st.markdown("</div>", unsafe_allow_html=True)


# ── Psychology helpers ───────────────────────────────────────────────────────

def _psych_session_alert(df: pd.DataFrame, styler) -> None:
    st.markdown("### Session Redistribution")
    sess_col = next((c for c in ["Session Norm", "Session"] if c in df.columns), None)
    if sess_col is None:
        _unavailable("Sessions")
        return
    g = df.copy()
    g["__sess"] = g[sess_col].apply(_clean_session_value)
    g = g[g["__sess"].notna()]
    if g.empty:
        _unavailable("Sessions")
        return
    total = len(g)
    counts = g["__sess"].value_counts()
    asia_n, london_n, ny_n = int(counts.get("Asia",0)), int(counts.get("London",0)), int(counts.get("New York",0))
    asia_pct = round(asia_n/max(1,total)*100,1)
    lon_pct  = round(london_n/max(1,total)*100,1)
    ny_pct   = round(ny_n/max(1,total)*100,1)

    def _swr(name):
        sub = g[(g["__sess"]==name) & g["Outcome"].isin(["Win","BE","Loss"])]
        return round(sub["Outcome"].eq("Win").sum()/max(1,len(sub))*100,1) if not sub.empty else None

    asia_wr, london_wr, ny_wr = _swr("Asia"), _swr("London"), _swr("New York")

    k1, k2, k3 = st.columns(3)
    with k1:
        col = "#ef4444" if asia_pct > ASIA_WARN_THRESHOLD else "#4800ff"
        wr_s = f" · {asia_wr}% WR" if asia_wr is not None else ""
        st.markdown(f"<div class='kpi'><div class='label'>Asia</div>"
                    f"<div class='value' style='color:{col}'>{asia_pct}%</div>"
                    f"<div class='muted'>{asia_n} trades{wr_s}</div></div>", unsafe_allow_html=True)
    with k2:
        wr_s = f" · {london_wr}% WR" if london_wr is not None else ""
        st.markdown(f"<div class='kpi'><div class='label'>London</div>"
                    f"<div class='value' style='color:#4800ff'>{lon_pct}%</div>"
                    f"<div class='muted'>{london_n} trades{wr_s}</div></div>", unsafe_allow_html=True)
    with k3:
        wr_s = f" · {ny_wr}% WR" if ny_wr is not None else ""
        st.markdown(f"<div class='kpi'><div class='label'>New York</div>"
                    f"<div class='value' style='color:#4800ff'>{ny_pct}%</div>"
                    f"<div class='muted'>{ny_n} trades{wr_s}</div></div>", unsafe_allow_html=True)

    if asia_pct > ASIA_WARN_THRESHOLD and london_wr and asia_wr:
        extra = round(asia_n*((london_wr-asia_wr)/100),1)
        _insight_box(f"<b>Asia overweight</b> — {asia_pct}% of trades (threshold {ASIA_WARN_THRESHOLD}%). "
                     f"London win rate <b>{london_wr}%</b> vs Asia <b>{asia_wr}%</b>. "
                     f"Redistributing Asia trades to London = approx <b>+{extra} wins</b> this period.", "bad")
    elif asia_pct > ASIA_WARN_THRESHOLD:
        _insight_box(f"<b>Asia overweight</b> — {asia_pct}% of trades. Shift toward London open.", "warn")
    else:
        _insight_box(f"Session balance healthy — Asia at {asia_pct}%, within {ASIA_WARN_THRESHOLD}% threshold.", "good")

    # The three chips above already carry these percentages; a bar chart of the
    # same numbers is the same stat twice. The threshold lives in the caption.
    st.markdown(f"<div class='muted'>Asia stays under {ASIA_WARN_THRESHOLD}% of trades \u2014 "
                "red means over.</div>", unsafe_allow_html=True)


def _psych_mental_state_gate(df: pd.DataFrame, styler) -> None:
    ms_col   = next((c for c in ["Mental State","Mental state","mental_state"] if c in df.columns), None)
    bias_col = next((c for c in ["Execution/Bias","Execution / Bias","Bias"] if c in df.columns), None)
    if ms_col is None:
        return  # column missing — the template panel carries that message
    g = df.copy()
    g["__ms"] = g[ms_col].astype(str).str.strip()
    g = g[~g["__ms"].isin(["","nan","NaN","None"])]
    if len(g) < 3:
        return  # present but unlogged — powered-on panel shows the half-moon
    states, rows = ["Good","Okay","Bad"], []
    for state in states:
        sub = g[g["__ms"]==state]
        if len(sub) < 3: continue
        cnt = sub[sub["Outcome"].isin(["Win","BE","Loss"])]
        wr  = round(cnt["Outcome"].eq("Win").sum()/max(1,len(cnt))*100,1)
        wb  = round(sub[bias_col].fillna("").str.contains("Wrong Bias").sum()/max(1,len(sub))*100,1) if bias_col else 0.0
        rows.append({"State":state,"Trades":len(sub),"Win Rate":wr,"Wrong Bias %":wb})
    if not rows:
        return  # states logged but none with 3+ trades yet — stay silent
    st.divider()
    st.markdown("### Mental State Gate")
    for col, row in zip(st.columns(len(rows)), rows):
        c = "#f59e0b" if row["State"]=="Okay" else "#16a34a" if row["State"]=="Good" else "#6b7280"
        badge = " ⚠" if row["State"]=="Okay" else ""
        wb_html = f'<div class="muted">Wrong bias: <b>{row["Wrong Bias %"]}%</b></div>' if bias_col else ""
        with col:
            st.markdown(f"<div class='kpi'><div class='label'>{row['State']}{badge}</div>"
                        f"<div class='value' style='color:{c}'>{row['Win Rate']}%</div>"
                        f"<div class='muted'>Win rate · {row['Trades']} trades</div>"
                        f"{wb_html}</div>", unsafe_allow_html=True)
    if bias_col and len(rows) >= 2:
        ok = next((r for r in rows if r["State"]=="Okay"), None)
        gd = next((r for r in rows if r["State"]=="Good"), None)
        if ok and gd and ok["Wrong Bias %"] > gd["Wrong Bias %"]:
            gap = round(ok["Wrong Bias %"]-gd["Wrong Bias %"],1)
            _insight_box(f"<b>Okay is your hidden danger state.</b> Wrong bias is <b>{gap}% higher</b> "
                         f"when feeling Okay vs Good ({ok['Wrong Bias %']}% vs {gd['Wrong Bias %']}%). "
                         f"Sub-optimal mental state corrupts bias more than feeling bad. "
                         f"Treat Okay days like Bad days — step back if you're not sharp.", "warn")
    if rows and bias_col:
        melted = pd.DataFrame(rows).melt(id_vars=["State","Trades"],
                                         value_vars=["Win Rate","Wrong Bias %"],
                                         var_name="Metric", value_name="Value")
        cv = _to_alt_values(melted)
        cs = alt.Scale(domain=["Win Rate","Wrong Bias %"],range=["#4800ff","#f59e0b"])
        bar = (alt.Chart(alt.Data(values=cv)).mark_bar(opacity=0.85)
               .encode(x=alt.X("State:N",sort=states,axis=alt.Axis(title=None)),
                       y=alt.Y("Value:Q",axis=alt.Axis(title="%")),
                       color=alt.Color("Metric:N",scale=cs,legend=alt.Legend(title=None,orient="top")),
                       xOffset="Metric:N",
                       tooltip=[alt.Tooltip("State:N"),alt.Tooltip("Metric:N"),
                                alt.Tooltip("Value:Q",format=".1f"),alt.Tooltip("Trades:Q")])
               .properties(height=200))
        st.altair_chart(styler(bar),use_container_width=True)


def _psych_bad_beat_tracker(df: pd.DataFrame) -> None:
    result_col = next((c for c in ["Result","result"] if c in df.columns), None)
    if result_col is None:
        return
    g = df.copy()
    bbs = g[g[result_col].astype(str).str.strip()=="Bad Beat"]
    n_bb, total = len(bbs), len(g)
    if n_bb == 0:
        return  # nothing to track — stay silent instead of a zero wall
    st.divider()
    st.markdown("### Bad Beat Tracker")
    bb_pct = round(n_bb/max(1,total)*100,1)
    recent = "—"
    dcol = next((c for c in ["Date & Time","Day/Time/Date of Trade","Date","Datetime"] if c in g.columns), None)
    if dcol and not bbs.empty:
        try:
            bd = pd.to_datetime(bbs[dcol].astype(str).str.replace(r"\s*\(GMT.*\)$","",regex=True),errors="coerce").dropna()
            if not bd.empty: recent = bd.max().strftime("%d %b %Y")
        except Exception: pass
    scol = next((c for c in ["Session Norm","Session"] if c in g.columns), None)
    by_sess: dict = {}
    if scol and not bbs.empty:
        for s, grp in bbs.groupby(bbs[scol].apply(_clean_session_value)):
            if s: by_sess[s] = len(grp)
    top_s = max(by_sess, key=by_sess.get) if by_sess else "—"
    top_n = by_sess.get(top_s, 0)
    k1, k2, k3 = st.columns(3)
    with k1:
        c = "#ef4444" if n_bb>=5 else "#f59e0b" if n_bb>=3 else "#4800ff"
        st.markdown(f"<div class='kpi'><div class='label'>Total Bad Beats</div>"
                    f"<div class='value' style='color:{c}'>{n_bb}</div>"
                    f"<div class='muted'>{bb_pct}% of all trades</div></div>",unsafe_allow_html=True)
    with k2:
        st.markdown(f"<div class='kpi'><div class='label'>Most Recent</div>"
                    f"<div class='value' style='color:#4800ff;font-size:18px'>{recent}</div>"
                    f"<div class='muted'>last bad beat date</div></div>",unsafe_allow_html=True)
    with k3:
        st.markdown(f"<div class='kpi'><div class='label'>Worst Session</div>"
                    f"<div class='value' style='color:#4800ff;font-size:18px'>{top_s}</div>"
                    f"<div class='muted'>{top_n} bad beats</div></div>",unsafe_allow_html=True)
    _insight_box(
        "<b>Step-away protocol after a bad beat</b><br>"
        "A bad beat = A+ setup stopped out then price runs to your TP. "
        "The chemicals that fire at this point will destroy your next trade.<br>"
        "<b>1.</b> Close the platform immediately. "
        "<b>2.</b> Walk, gym, or meditate. "
        "<b>3.</b> Do not return until the next 3SL window.<br>"
        "<span style='color:#6b7280;font-size:12px'>Breakevens are not bad beats. "
        "A bad beat is specifically: stopped out → price runs to TP.</span>", "info")


def _psych_3sl_compliance(df: pd.DataFrame, styler) -> None:
    st.markdown("### 3SL Compliance")
    st.caption("Two rules: trades must be inside the 2h session window, and only one trade per session per day.")

    wcol     = next((c for c in ["2h session window","2h Session Window","Session Window"] if c in df.columns), None)
    sess_col = next((c for c in ["Session Norm","Session"] if c in df.columns), None)
    dcol     = next((c for c in ["Date & Time","Day/Time/Date of Trade","Date","Datetime"] if c in df.columns), None)

    if wcol is None and (sess_col is None or dcol is None):
        st.info("Add a '2h session window' Yes/No field to Notion to track 3SL window compliance.")
        return

    g = df.copy()

    if dcol:
        try:
            g["__dp"] = pd.to_datetime(
                g[dcol].astype(str).str.replace(r"\s*\(GMT.*\)$", "", regex=True),
                errors="coerce")
            g["__date"] = g["__dp"].dt.date
        except Exception:
            g["__dp"] = pd.NaT
            g["__date"] = None

    has_window = wcol is not None
    ins_n = out_n = total_w = 0
    comp_pct = ins_wr = out_wr = None

    if has_window:
        g["__w"] = g[wcol].astype(str).str.strip().str.lower().map(
            lambda v: "yes" if v in ("yes","y","true","1") else ("no" if v in ("no","n","false","0") else None))
        gw = g[g["__w"].notna()].copy()
        total_w  = len(gw)
        ins_n    = int((gw["__w"] == "yes").sum())
        out_n    = int((gw["__w"] == "no").sum())
        comp_pct = round(ins_n / max(1, total_w) * 100, 1)

        def _wr(sub):
            c = sub[sub["Outcome"].isin(["Win", "BE", "Loss"])]
            return round(c["Outcome"].eq("Win").sum() / max(1, len(c)) * 100, 1) if not c.empty else None

        ins_wr = _wr(gw[gw["__w"] == "yes"])
        out_wr = _wr(gw[gw["__w"] == "no"])

    gs = pd.DataFrame()
    multi_session_days   = 0
    multi_session_breaks = 0
    session_counts       = pd.DataFrame()
    has_session_rule     = sess_col is not None and dcol is not None

    if has_session_rule:
        try:
            g["__sess_clean"] = g[sess_col].apply(_clean_session_value)
            gs = g.dropna(subset=["__dp", "__sess_clean"]).copy()
            if not gs.empty:
                session_counts = gs.groupby(["__date", "__sess_clean"]).size().reset_index(name="n")
                breaks = session_counts[session_counts["n"] > 1]
                multi_session_days   = int(breaks["__date"].nunique())
                multi_session_breaks = int((breaks["n"] - 1).sum())
        except Exception:
            pass

    _show_window = has_window and total_w > 0
    _cols = st.columns(4 if _show_window else 1)
    if _show_window:
        with _cols[0]:
            col_c = "#4800ff" if comp_pct >= 70 else "#f59e0b" if comp_pct >= 50 else "#ef4444"
            st.markdown(f"<div class='kpi'><div class='label'>Window Compliance</div>"
                        f"<div class='value' style='color:{col_c}'>{comp_pct}%</div>"
                        f"<div class='muted'>{ins_n} inside · {out_n} outside</div></div>",
                        unsafe_allow_html=True)
        with _cols[1]:
            v = f"{ins_wr}%" if ins_wr is not None else "—"
            st.markdown(f"<div class='kpi'><div class='label'>Win Rate (Inside)</div>"
                        f"<div class='value' style='color:#4800ff'>{v}</div>"
                        f"<div class='muted'>{ins_n} trades in window</div></div>",
                        unsafe_allow_html=True)
        with _cols[2]:
            v = f"{out_wr}%" if out_wr is not None else "—"
            st.markdown(f"<div class='kpi'><div class='label'>Win Rate (Outside)</div>"
                        f"<div class='value' style='color:#4800ff'>{v}</div>"
                        f"<div class='muted'>{out_n} trades outside window</div></div>",
                        unsafe_allow_html=True)
    with _cols[-1]:
        msb_color = "#ef4444" if multi_session_breaks > 0 else "#4800ff"
        st.markdown(f"<div class='kpi'><div class='label'>One-Trade Rule Breaks</div>"
                    f"<div class='value' style='color:{msb_color}'>{multi_session_breaks}</div>"
                    f"<div class='muted'>{multi_session_days} sessions with 2+ trades</div></div>",
                    unsafe_allow_html=True)

    if has_window and total_w == 0:
        _insight_box("The '2h session window' field exists but has no Yes/No values recorded yet. "
                     "Tick it on each trade to start tracking window compliance.", "warn")
    elif has_window and ins_wr is not None and out_wr is not None:
        if ins_wr >= out_wr:
            _insight_box(f"Window compliance is working — inside win rate <b>{ins_wr}%</b> "
                         f"vs <b>{out_wr}%</b> outside. "
                         f"{out_n} of {total_w} trades were outside the 2h window.")
        else:
            _insight_box(f"Outside-window win rate ({out_wr}%) currently exceeds inside ({ins_wr}%). "
                         f"Sample may be small — keep logging. "
                         f"The window rule protects drawdown control regardless of short-term rates.", "warn")
    elif has_window and comp_pct is not None and comp_pct < 70:
        _insight_box(f"Only <b>{comp_pct}%</b> of trades inside the 2h window ({ins_n} of {total_w}). "
                     f"The 3SL system only protects you when you follow it.", "warn")

    if multi_session_breaks > 0:
        _insight_box(
            f"<b>{multi_session_breaks} extra trades</b> were taken in sessions where you already had an entry "
            f"({multi_session_days} sessions affected). "
            f"The 3SL rule is one trade per session — a second trade removes the protection entirely. "
            f"After a loss the session is finished, even if another setup forms.", "warn")
    elif has_session_rule and not gs.empty:
        _insight_box("One-trade-per-session rule is clean — no sessions with multiple entries detected.")

    if has_window and dcol and total_w > 0:
        try:
            gw_dated = gw.dropna(subset=["__dp"]).copy()
            if not gw_dated.empty:
                gw_dated["__wk"] = gw_dated["__dp"].dt.to_period("W").apply(lambda p: p.start_time)
                wk = (gw_dated.groupby("__wk")
                       .agg(total=("__w", "count"), inside=("__w", lambda s: (s == "yes").sum()))
                       .reset_index())
                wk["Compliance %"] = (wk["inside"] / wk["total"] * 100).round(1)
                wk = wk.rename(columns={"__wk": "Week"})
                cv = _to_alt_values(wk[["Week", "Compliance %"]])
                if cv:
                    st.markdown("#### Window compliance by week")
                    bar = (alt.Chart(alt.Data(values=cv))
                           .mark_bar(color="#4800ff", opacity=0.7,
                                     cornerRadiusTopLeft=3, cornerRadiusTopRight=3)
                           .encode(
                               x=alt.X("Week:T", axis=alt.Axis(format="%b %d", labelAngle=-45,
                                                                tickCount=8, labelOverlap=False, title=None)),
                               y=alt.Y("Compliance %:Q", scale=alt.Scale(domain=[0, 100]),
                                       axis=alt.Axis(title="% inside 2h window")),
                               tooltip=[alt.Tooltip("Week:T", format="%d %b %Y"),
                                        alt.Tooltip("Compliance %:Q", format=".1f")])
                           .properties(height=200))
                    rule = (alt.Chart(alt.Data(values=[{"y": 70}]))
                            .mark_rule(color="#4800ff", strokeDash=[4, 4], strokeWidth=1.5)
                            .encode(y="y:Q"))
                    st.altair_chart(styler(alt.layer(bar, rule)), use_container_width=True)
                    st.markdown("<div class='muted'>Dashed line = 70% target</div>",
                                unsafe_allow_html=True)
        except Exception:
            pass

    if has_session_rule and multi_session_breaks > 0 and not session_counts.empty:
        try:
            # Which SESSIONS repeat — the pattern is actionable; the dates aren't.
            brk = session_counts[session_counts["n"] > 1].copy()
            per_sess = (brk.groupby("__sess_clean")["n"].agg(
                lambda v: int((v - 1).sum())).sort_values(ascending=False))
            bits = [f"{name} \u00d7{int(x)}" for name, x in per_sess.items() if int(x) > 0]
            if bits:
                st.caption("Where it happens: " + " \u00b7 ".join(bits[:4]))
        except Exception:
            pass


def _journal_completeness_strip(df: pd.DataFrame) -> None:
    """Amber banner when manual tag columns exist but are mostly unlogged."""
    if df is None or df.empty:
        return
    tag_cols = [c for c in ["A+ Setup?", "Conviction (1-5)", "Mental State",
                            "Mistake", "Rules Followed?"] if c in df.columns]
    if len(tag_cols) < 2:
        return
    def _filled(row):
        for c in tag_cols:
            _v = row.get(c)
            if isinstance(_v, bool):
                continue  # checkbox state counts as logged either way
            if str(_v if _v is not None else "").strip().lower() in ("", "nan", "none", "na", "[]"):
                return False
        return True
    full = int(df.apply(_filled, axis=1).sum())
    total = len(df)
    pct = full / max(1, total)
    if pct >= 0.9:
        return
    fill_w = max(3, int(round(pct * 100)))
    nice = ", ".join(c.replace("?", "") for c in tag_cols)
    st.markdown(
        f"<div style='display:flex;align-items:center;gap:16px;background:#fdf6e8;"
        f"border:1px solid #ecd4a2;border-radius:12px;padding:14px 18px;margin:2px 0 10px;'>"
        f"<div style='font-size:19px;color:#7c4a03;font-weight:800;'>\u26a0</div>"
        f"<div style='flex:1;'><div style='font-size:15.5px;font-weight:800;color:#7c4a03;'>"
        f"Journal completeness: {full} of {total} trades fully tagged</div>"
        f"<div style='font-size:12.5px;color:#9a6b1f;margin-top:1px;'>This page reads only tagged trades "
        f"\u2014 backfill {_html.escape(nice)} in Notion and it sharpens fast.</div></div>"
        f"<div style='flex:0 0 180px;background:#f3e3c0;border-radius:8px;height:12px;overflow:hidden;'>"
        f"<div style='width:{fill_w}%;height:12px;background:#b45309;'></div></div>"
        f"</div>", unsafe_allow_html=True)


def _psychology_tab(f: pd.DataFrame, df_raw: pd.DataFrame, styler):
    st.markdown('<div class="section">', unsafe_allow_html=True)

    if f is None or f.empty:
        st.info("No trades for current filters.")
        st.markdown("</div>", unsafe_allow_html=True)
        return

    g = f.copy()

    s_dt = _coerce_datetime_series(g, tz_name=os.getenv("EDGE_LOCAL_TZ", "Australia/Sydney"))
    if s_dt is None:
        date_col = next((c for c in ["Date", "Trade Date", "Entry Date"] if c in g.columns), None)
        if date_col:
            s_dt = pd.to_datetime(
                g[date_col].astype(str).str.replace(r"\s*\(GMT.*\)$", "", regex=True),
                errors="coerce")
            if s_dt.dt.tz is None:
                s_dt = s_dt.dt.tz_localize("UTC")
        else:
            st.info("No datetime column found — psychology metrics require a date/time per trade.")
            st.markdown("</div>", unsafe_allow_html=True)
            return

    g["__ts"] = s_dt
    g = g[g["__ts"].notna()].sort_values("__ts").reset_index(drop=True)
    if g.empty:
        st.info("No dated trades in current filters.")
        st.markdown("</div>", unsafe_allow_html=True)
        return

    try:
        local_tz = ZoneInfo(os.getenv("EDGE_LOCAL_TZ", "Australia/Sydney"))
        g["__local_ts"] = g["__ts"].dt.tz_convert(local_tz)
    except Exception:
        g["__local_ts"] = g["__ts"]

    g["__date"] = g["__local_ts"].dt.date

    trades_per_day = g.groupby("__date")["__ts"].transform("count")
    g["__overtrade"] = trades_per_day > OVERTRADE_LIMIT

    g["__revenge"] = False
    revenge_window = timedelta(minutes=REVENGE_WINDOW_MINS)
    outcome_col = "Outcome" if "Outcome" in g.columns else None

    if outcome_col:
        loss_times = g.loc[g[outcome_col] == "Loss", "__ts"].tolist()
        for idx, row in g.iterrows():
            entry_ts = row["__ts"]
            for lt in loss_times:
                if lt < entry_ts and (entry_ts - lt) <= revenge_window:
                    g.at[idx, "__revenge"] = True
                    break

    day_flags = g.groupby("__date").agg(
        overtrade=("__overtrade", "any"),
        revenge=("__revenge", "any"),
    ).reset_index()
    day_flags["__violation"] = day_flags["overtrade"] | day_flags["revenge"]
    total_days = len(day_flags)
    clean_days = int((~day_flags["__violation"]).sum())
    discipline_score = round((clean_days / max(1, total_days)) * 100)

    if outcome_col:
        day_outcome = g.groupby("__date").agg(
            trade_count=("__ts", "count"),
            net_wins=("Outcome", lambda s: int((s == "Win").sum()) - int((s == "Loss").sum())),
        ).reset_index()
        day_outcome["day_result"] = day_outcome["net_wins"].apply(
            lambda x: "Winning Day" if x > 0 else ("Losing Day" if x < 0 else "Neutral Day"))
        avg_by_result = day_outcome.groupby("day_result")["trade_count"].mean().round(2)
        avg_win_day = float(avg_by_result.get("Winning Day", 0.0))
        avg_loss_day = float(avg_by_result.get("Losing Day", 0.0))
    else:
        avg_win_day = avg_loss_day = 0.0

    n_revenge = int(g["__revenge"].sum())
    n_overtrade_days = int(day_flags["overtrade"].sum())
    n_total = len(g)
    n_flagged = int((g["__overtrade"] | g["__revenge"]).sum())

    score_color = (
        "#16a34a" if discipline_score >= 80
        else "#f59e0b" if discipline_score >= 60
        else "#ef4444"
    )

    rules_kept = rules_known = None
    if "Rules Followed?" in g.columns:
        _rv = g["Rules Followed?"].astype(str).str.strip().str.lower()
        _kn = _rv.isin(["yes", "no", "true", "false", "__yes__", "__no__", "1", "0"])
        if int(_kn.sum()) >= 3:
            rules_known = int(_kn.sum())
            rules_kept = int((_rv.isin(["yes", "true", "__yes__", "1"]) & _kn).sum())
    _cap = int(st.session_state.get("ea_m_cap", 12))
    _month_n = int((g["__local_ts"].dt.to_period("M") == pd.Timestamp.now().to_period("M")).sum())

    st.markdown("### Discipline")
    k1, k2, k3, k4 = st.columns(4)
    with k1:
        st.markdown(f"""
            <div class='kpi'>
              <div class='label'>Discipline Score</div>
              <div class='value' style='color:{score_color}'>{discipline_score}%</div>
              <div class='muted'>{clean_days} / {total_days} clean days</div>
            </div>""", unsafe_allow_html=True)
    with k2:
        if rules_known:
            _rc = "#16a34a" if rules_kept == rules_known else ("#b45309" if rules_kept / rules_known < 0.7 else "#4800ff")
            st.markdown(f"""
            <div class='kpi'>
              <div class='label'>Rules Followed</div>
              <div class='value' style='color:{_rc}'>{rules_kept} of {rules_known}</div>
              <div class='muted'>by your own tag</div>
            </div>""", unsafe_allow_html=True)
        else:
            st.markdown(f"""
            <div class='kpi'>
              <div class='label'>Avg Trades — Win Day</div>
              <div class='value' style='color:#4800ff'>{avg_win_day:.1f}</div>
              <div class='muted'>trades per winning day</div>
            </div>""", unsafe_allow_html=True)
    with k3:
        _cc = "#ef4444" if _month_n > _cap else "#4800ff"
        st.markdown(f"""
            <div class='kpi'>
              <div class='label'>Cap Discipline</div>
              <div class='value' style='color:{_cc}'>{_month_n} of {_cap}</div>
              <div class='muted'>trades this month vs cap</div>
            </div>""", unsafe_allow_html=True)
    with k4:
        st.markdown(f"""
            <div class='kpi'>
              <div class='label'>Flagged Trades</div>
              <div class='value' style='color:#4800ff'>{n_flagged}</div>
              <div class='muted'>{round(n_flagged / max(1, n_total) * 100, 1)}% of all trades</div>
            </div>""", unsafe_allow_html=True)

    st.divider()

    _all_clear = (int(n_overtrade_days) == 0 and int(n_revenge) == 0
                  and float(discipline_score) >= 100)
    if _all_clear:
        st.markdown(
            "<div style='display:flex;align-items:center;gap:16px;background:#e9f7ef;"
            "border:1px solid #bfe6cd;border-radius:12px;padding:16px 20px;margin:8px 0;'>"
            "<div style='min-width:36px;height:36px;border-radius:50%;background:#16a34a;"
            "color:#fff;font-size:19px;font-weight:800;display:flex;align-items:center;"
            "justify-content:center;'>\u2713</div>"
            "<div><div style='font-size:17px;font-weight:800;color:#14532d;'>Discipline: all clear</div>"
            f"<div style='font-size:13.5px;color:#2f6b45;margin-top:2px;'>Score 100% \u00b7 "
            f"0 overtrading days \u00b7 0 revenge trades \u00b7 {clean_days} of {total_days} clean days"
            "</div></div></div>", unsafe_allow_html=True)
    else:
        st.markdown("### Discipline Score Over Time")

        day_flags["__date"] = pd.to_datetime(day_flags["__date"])
        day_flags_indexed = day_flags.set_index("__date").sort_index()

        if len(day_flags_indexed) >= 2:
            rolling = (
                (~day_flags_indexed["__violation"]).astype(int)
                .rolling("28D", min_periods=1).mean().mul(100).round(1)
                .reset_index()
            )
            rolling.columns = ["Date", "Score"]
            rolling_vals = _to_alt_values(rolling)

            area = (alt.Chart(alt.Data(values=rolling_vals))
                    .mark_area(opacity=0.10, color="#4800ff")
                    .encode(x="Date:T", y="Score:Q"))
            line = (alt.Chart(alt.Data(values=rolling_vals))
                    .mark_line(strokeWidth=2, color="#4800ff", interpolate="monotone")
                    .encode(
                        x=alt.X("Date:T", title=None,
                                 axis=alt.Axis(format="%b %d", labelAngle=-45, labelOverlap=True)),
                        y=alt.Y("Score:Q", title="Score (%)", scale=alt.Scale(domain=[0, 105])))
                    .properties(height=240))
            st.altair_chart(styler(alt.layer(area, line)), use_container_width=True)
            st.markdown(
                "<div class='muted'>Rolling 4-week average — higher is better</div>",
                unsafe_allow_html=True)
            if discipline_score >= 80:
                _insight_box(f"Discipline score is <b>{discipline_score}%</b> — strong. "
                             f"{clean_days} of {total_days} trading days had no overtrading or revenge trades.", "good")
            elif discipline_score >= 60:
                _insight_box(f"Discipline score is <b>{discipline_score}%</b>. "
                             f"{total_days - clean_days} days had violations — "
                             f"overtrading ({n_overtrade_days} days) or revenge entries ({n_revenge} trades). "
                             f"Each violation day is a compounding leak in your edge.", "warn")
            else:
                _insight_box(f"Discipline score is <b>{discipline_score}%</b> — needs attention. "
                             f"{total_days - clean_days} of {total_days} days had rule violations. "
                             f"The 3SL system exists specifically to eliminate these mechanically — "
                             f"review the compliance section below.", "bad")
        else:
            st.info("Not enough data for rolling chart yet.")

    st.divider()

    raw = df_raw if df_raw is not None and not df_raw.empty else g
    _psych_mental_state_gate(raw, styler)
    _psych_bad_beat_tracker(raw)

    st.divider()

    _psych_3sl_compliance(raw, styler)

    st.markdown("</div>", unsafe_allow_html=True)


# ── Section renderers ─────────────────────────────────────────────────────────
def _entry_models_tab(f: pd.DataFrame, show_table):
    st.markdown('<div class="section">', unsafe_allow_html=True)
    if f is None or f.empty:
        st.info("No trades for current filters.")
        st.markdown("</div>", unsafe_allow_html=True)
        return
    f_norm = _ensure_entry_models_list(f)
    if "Entry Models List" not in f_norm.columns:
        st.info("No entry model data.")
        st.markdown("</div>", unsafe_allow_html=True)
        return
    em = f_norm.copy()
    em = em[em["Entry Models List"].apply(lambda x: isinstance(x, (list, tuple)) and len(x) > 0)]
    if em.empty:
        st.info("No entry model data.")
        st.markdown("</div>", unsafe_allow_html=True)
        return
    em = em.explode("Entry Models List", ignore_index=True)
    em = em[em["Entry Models List"].astype(str).str.strip() != ""]
    if em.empty:
        st.info("No entry model data.")
        st.markdown("</div>", unsafe_allow_html=True)
        return
    counted = em[em["Outcome"].isin(["Win", "BE", "Loss"])]
    if counted.empty:
        st.info("No counted outcomes yet.")
        st.markdown("</div>", unsafe_allow_html=True)
        return
    rates = []
    for model, group in counted.groupby("Entry Models List"):
        r = outcome_rates_from(group)
        net_rr, ex_rr = _rr_stats(group)
        rates.append(dict(Entry_Model=str(model), Trades=len(group),
                          **{"Win %": r["win_rate"], "BE %": r["be_rate"], "Loss %": r["loss_rate"],
                             "Net PnL (R)": net_rr, "Expectancy (R)": ex_rr}))
    if rates:
        df_em = pd.DataFrame(rates).sort_values("Win %", ascending=False)
        st.markdown("### Entry Model Expectancy")
        st.caption("Average R per trade by entry model — ranked best → worst.")
        _flip("em_flip",
              lambda: _edge_tiles(df_em, "Entry_Model", "Expectancy (R)"),
              lambda: render_entry_model_table(df_em, title="Entry Model Performance"))
        df_em3 = df_em[pd.to_numeric(df_em["Trades"], errors="coerce") >= 3]
        if len(df_em3) >= 2 and int(pd.to_numeric(df_em3["Trades"], errors="coerce").max() or 0) >= 8:
            best_em = df_em3.iloc[0]
            worst_em = df_em3.iloc[-1]
            if best_em["Entry_Model"] != worst_em["Entry_Model"]:
                _insight_box(
                    f"<b>{best_em['Entry_Model']}</b> leads with <b>{best_em['Win %']:.1f}%</b> win rate "
                    f"across {int(best_em['Trades'])} trades. "
                    f"<b>{worst_em['Entry_Model']}</b> is your weakest model at "
                    f"<b>{worst_em['Win %']:.1f}%</b> — consider filtering it out or reviewing entry criteria.", "info")
    else:
        st.info("No counted outcomes yet.")
    st.markdown("</div>", unsafe_allow_html=True)


def _confluences_tab(f: pd.DataFrame, show_table):
    st.markdown('<div class="section">', unsafe_allow_html=True)
    if f is None or f.empty:
        st.info("No trades for current filters.")
        st.markdown("</div>", unsafe_allow_html=True)
        return
    g = f.copy()
    lower_map = {str(c).strip().lower(): c for c in g.columns}

    def _norm_name(name):
        return re.sub(r"[^a-z]", "", name.lower())

    div_col_name = None
    sweep_col_name = None
    for key, col in lower_map.items():
        norm = _norm_name(key)
        if norm == "div" and div_col_name is None:
            div_col_name = col
        if norm == "sweep" and sweep_col_name is None:
            sweep_col_name = col

    def _from_yes_no(val):
        if val is None:
            return False
        if isinstance(val, float) and pd.isna(val):
            return False
        return str(val).strip().lower() in {"yes", "y", "true", "1"}

    def _classify_row(row):
        if div_col_name is not None or sweep_col_name is not None:
            div_flag = _from_yes_no(row.get(div_col_name)) if div_col_name else False
            sweep_flag = _from_yes_no(row.get(sweep_col_name)) if sweep_col_name else False
            if div_flag and sweep_flag:
                return "DIV & Sweep"
            if div_flag:
                return "DIV"
            if sweep_flag:
                return "Sweep"
            return None
        for col_name in ["Entry Confluence", "Confluence"]:
            if col_name in row.index:
                v = row[col_name]
                items = ([str(x).strip().lower() for x in v] if isinstance(v, (list, tuple, set))
                         else [p.strip().lower() for p in re.split(r"[;,/|+]", str(v)) if p.strip()])
                has_div = any("div" in it for it in items)
                has_sweep = any("sweep" in it for it in items)
                if has_div and has_sweep:
                    return "DIV & Sweep"
                if has_div:
                    return "DIV"
                if has_sweep:
                    return "Sweep"
                return None
        return None

    g["Confluence"] = g.apply(_classify_row, axis=1)
    g = g[g["Confluence"].notna()]
    if g.empty:
        st.info("No DIV / Sweep confluence data in current slice.")
        st.markdown("</div>", unsafe_allow_html=True)
        return
    counted = g[g["Outcome"].isin(["Win", "BE", "Loss"])]
    if counted.empty:
        st.info("No counted outcomes yet for any confluence.")
        st.markdown("</div>", unsafe_allow_html=True)
        return
    rows = []
    for conf in CONFLUENCE_OPTIONS:
        sub = counted[counted["Confluence"] == conf]
        if sub.empty:
            continue
        r = outcome_rates_from(sub)
        net_rr, ex_rr = _rr_stats(sub)
        rows.append(dict(Confluence=conf, Trades=len(sub),
                         **{"Win %": r["win_rate"], "BE %": r["be_rate"], "Loss %": r["loss_rate"],
                            "Net PnL (R)": net_rr, "Expectancy (R)": ex_rr}))
    if rows:
        conf_df = pd.DataFrame(rows).sort_values("Win %", ascending=False).reset_index(drop=True)
        _covered = conf_df["Confluence"].astype(str).str.lower().str.strip().isin(
            ["sweep", "div", "divergence", "div?", "sweep?"])
        conf_df = conf_df[~_covered].reset_index(drop=True)
        if conf_df.empty:
            st.markdown("</div>", unsafe_allow_html=True)
            return
        render_entry_model_table(conf_df.rename(columns={"Confluence": "Entry_Model"}),
                                 title="Confluence Performance")
        if not conf_df.empty and "Win %" in conf_df.columns:
            best_conf = conf_df.iloc[0]
            _insight_box(
                f"<b>{best_conf['Confluence']}</b> is your highest-probability confluence at "
                f"<b>{best_conf['Win %']:.1f}%</b> win rate across {int(best_conf['Trades'])} trades. "
                f"Prioritise setups where this confluence is present.")
    else:
        st.info("No confluence stats available.")
    st.markdown("</div>", unsafe_allow_html=True)


def _hourly_expectancy_clock(df_raw: pd.DataFrame) -> None:
    """
    24-hour radial clock showing expectancy by entry hour.
    Reads from the raw (pre-pipeline) df so early-close rows are included
    and Closed RR values are used directly.
    Renders via st.components.v1.html so the interactive JS hover works.
    """
    import json
    import streamlit.components.v1 as components

    WIN_RESULTS  = {"Full TP", "Early Close (Ended up being a win)", "TP2 (SL2TP1)", "Win"}
    LOSS_RESULTS = {"Loss", "Bad Beat", "Breakeven, Loss"}

    def _parse_hour(dt_str):
        if pd.isna(dt_str):
            return None
        s = str(dt_str).strip()
        m = re.search(r'(\d{1,2}):(\d{2})\s*(AM|PM)', s, re.IGNORECASE)
        if m:
            h, ampm = int(m.group(1)), m.group(3).upper()
            if ampm == "PM" and h != 12:
                h += 12
            if ampm == "AM" and h == 12:
                h = 0
            return h
        m = re.search(r'(\d{1,2}):(\d{2})(?!\s*[AP]M)', s, re.IGNORECASE)
        if m:
            return int(m.group(1)) % 24
        return None

    if df_raw is None or df_raw.empty:
        st.info("No trade data available for the hourly clock.")
        return

    df = df_raw.copy()

    dt_col  = next((c for c in ["Day/Time/Date of Trade", "Date & Time", "Datetime"] if c in df.columns), None)
    time_col = "Time of Trade" if "Time of Trade" in df.columns else None

    if dt_col:
        df["_hour"] = df[dt_col].apply(_parse_hour)
    elif time_col:
        df["_hour"] = df[time_col].apply(_parse_hour)
    elif "Hour (Melb)" in df.columns:
        df["_hour"] = pd.to_numeric(df["Hour (Melb)"], errors="coerce")
    elif "Open Time" in df.columns:
        df["_hour"] = pd.to_datetime(df["Open Time"], errors="coerce").dt.hour
    elif "Date" in df.columns and pd.to_datetime(df["Date"], errors="coerce").dt.hour.fillna(0).nunique() > 1:
        df["_hour"] = pd.to_datetime(df["Date"], errors="coerce").dt.hour
    else:
        st.caption("Hourly clock: no entry-time data in this journal yet.")
        return

    if "Result" in df.columns:
        df["_outcome"] = df["Result"].apply(
            lambda r: "win" if str(r).strip() in WIN_RESULTS
            else ("loss" if str(r).strip() in LOSS_RESULTS else "be"))
    elif "Outcome" in df.columns:
        df["_outcome"] = df["Outcome"].astype(str).str.lower().map(
            lambda v: v if v in ("win", "loss", "be") else "be")
    else:
        df["_outcome"] = "be"

    df["_rr"] = pd.to_numeric(df["Closed RR"], errors="coerce") if "Closed RR" in df.columns else float("nan")

    hourly = df.dropna(subset=["_hour", "_rr"]).copy()
    hourly["_hour"] = hourly["_hour"].astype(int)

    hour_data = {}
    for h, grp in hourly.groupby("_hour"):
        wins   = grp[grp["_outcome"] == "win"]["_rr"]
        losses = grp[grp["_outcome"] == "loss"]["_rr"]
        n      = len(grp)
        wr     = len(wins)   / n if n else 0
        lr     = len(losses) / n if n else 0
        avg_w  = float(wins.mean())   if len(wins)   else 0.0
        avg_l  = float(losses.mean()) if len(losses) else 0.0
        exp    = round(wr * avg_w + lr * avg_l, 3)
        hour_data[int(h)] = {"e": exp, "n": int(n)}

    if not hour_data:
        st.info("Not enough data to build the hourly expectancy clock.")
        return

    all_exp     = [v["e"] for v in hour_data.values()]
    overall_avg = round(sum(all_exp) / len(all_exp), 2)
    data_js     = json.dumps(hour_data)

    html = f"""
<div style="font-family:-apple-system,sans-serif;display:flex;flex-direction:column;align-items:center;padding:0.5rem 0 0;background:#f6f7fb;border-radius:12px;">
  <p style="margin:0 0 4px;font-size:14px;font-weight:500;color:#0f172a;">Expectancy by entry hour</p>
  <p style="margin:0 0 14px;font-size:12px;color:#64748b;">hover a segment to inspect</p>
  <svg id="eclock" width="360" height="360"
       viewBox="-180 -180 360 360"
       xmlns="http://www.w3.org/2000/svg" role="img">
    <title>24-hour expectancy clock</title>
    <desc>Radial clock showing trading expectancy per entry hour. Purple = positive, red = negative, opacity encodes magnitude.</desc>
    <g id="cg"></g>
    <circle cx="0" cy="0" r="100" fill="none" stroke="rgba(72,0,255,0.06)" stroke-width="0.5"/>
    <circle cx="0" cy="0" r="130" fill="none" stroke="rgba(72,0,255,0.06)" stroke-width="0.5"/>
    <circle cx="0" cy="0" r="68" fill="#ffffff" stroke="rgba(72,0,255,0.12)" stroke-width="0.5"/>
    <text id="ch" x="0" y="-22" text-anchor="middle" dominant-baseline="central"
          style="font-size:11px;fill:#64748b;"></text>
    <text id="cv" x="0" y="-2" text-anchor="middle" dominant-baseline="central"
          style="font-size:20px;font-weight:500;fill:#4800ff;"></text>
    <text id="cs" x="0" y="20" text-anchor="middle" dominant-baseline="central"
          style="font-size:11px;fill:#64748b;"></text>
  </svg>
  <div style="display:flex;gap:14px;margin-top:8px;font-size:12px;color:#64748b;align-items:center;">
    <span style="display:flex;align-items:center;gap:4px;">
      <span style="width:9px;height:9px;background:#4800ff;border-radius:2px;opacity:0.75;display:inline-block;"></span>positive
    </span>
    <span style="display:flex;align-items:center;gap:4px;">
      <span style="width:9px;height:9px;background:#ef4444;border-radius:2px;opacity:0.75;display:inline-block;"></span>negative
    </span>
    <span style="display:flex;align-items:center;gap:4px;">
      <span style="width:9px;height:9px;background:#e2e8f0;border-radius:2px;display:inline-block;"></span>no data
    </span>
  </div>
</div>
<script>
(function(){{
  const DATA    = {data_js};
  const OVERALL = {overall_avg};
  const NS      = "http://www.w3.org/2000/svg";
  const g       = document.getElementById("cg");
  const cv      = document.getElementById("cv");
  const cs      = document.getElementById("cs");
  const ch      = document.getElementById("ch");
  const INNER   = 74, OUTER = 152, MAX_ABS = 3.0;

  function polar(deg, r) {{
    const rad = (deg - 90) * Math.PI / 180;
    return [r * Math.cos(rad), r * Math.sin(rad)];
  }}

  function arc(h, ir, or_) {{
    const sd = 360/24, sa = h*sd, ea = sa+sd-1.2;
    const [x1,y1]=polar(sa,or_),[x2,y2]=polar(ea,or_);
    const [x3,y3]=polar(ea,ir),[x4,y4]=polar(sa,ir);
    return `M${{x1.toFixed(2)}},${{y1.toFixed(2)}} A${{or_}},${{or_}} 0 0,1 ${{x2.toFixed(2)}},${{y2.toFixed(2)}} L${{x3.toFixed(2)}},${{y3.toFixed(2)}} A${{ir}},${{ir}} 0 0,0 ${{x4.toFixed(2)}},${{y4.toFixed(2)}} Z`;
  }}

  function color(e, alpha) {{
    if (e >= 0) {{
      const t = Math.min(e / MAX_ABS, 1);
      return `rgba(72,0,255,${{Math.min(alpha * (0.3 + t * 0.7), 1).toFixed(2)}})`;
    }} else {{
      const t = Math.min(Math.abs(e) / MAX_ABS, 1);
      return `rgba(239,68,68,${{Math.min(alpha * (0.3 + t * 0.7), 1).toFixed(2)}})`;
    }}
  }}

  function setCenter(h) {{
    if (h === null) {{
      ch.textContent = "";
      cs.textContent = "avg expectancy";
      cv.textContent = (OVERALL>=0?"+":"")+OVERALL.toFixed(2)+"R";
      cv.style.fill = OVERALL>=0 ? "#4800ff" : "#dc2626";
    }} else {{
      const d = DATA[h];
      ch.textContent = String(h).padStart(2,"0")+"h";
      if (d) {{
        cs.textContent = d.n+" trade"+(d.n===1?"":"s");
        cv.textContent = (d.e>=0?"+":"")+d.e.toFixed(2)+"R";
        cv.style.fill = d.e>=0 ? "#4800ff" : "#dc2626";
      }} else {{
        cs.textContent = "no data";
        cv.textContent = "—";
        cv.style.fill = "#64748b";
      }}
    }}
  }}

  const segs = [];
  for (let h=0; h<24; h++) {{
    const d = DATA[h];
    const seg = document.createElementNS(NS,"path");
    seg.setAttribute("d", arc(h, INNER, OUTER));
    seg.setAttribute("fill", d ? color(d.e, 0.7) : "#e2e8f0");
    seg.setAttribute("stroke","#f6f7fb");
    seg.setAttribute("stroke-width","1");
    seg.style.cursor = d ? "pointer" : "default";
    seg.style.transition = "fill 0.12s";
    segs.push({{seg, h, d}});

    seg.addEventListener("mouseenter", () => {{
      segs.forEach(s => s.seg.setAttribute("fill",
        s.h===h
          ? (s.d ? color(s.d.e, 1) : "#cbd5e1")
          : (s.d ? color(s.d.e, 0.25) : "#eaecf0")
      ));
      setCenter(h);
    }});
    seg.addEventListener("mouseleave", () => {{
      segs.forEach(s => s.seg.setAttribute("fill", s.d ? color(s.d.e, 0.7) : "#e2e8f0"));
      setCenter(null);
    }});
    g.appendChild(seg);

    const mid = h*(360/24)+(360/48);
    const [lx,ly] = polar(mid, OUTER+14);
    const lbl = document.createElementNS(NS,"text");
    lbl.setAttribute("x", lx.toFixed(1));
    lbl.setAttribute("y", ly.toFixed(1));
    lbl.setAttribute("text-anchor","middle");
    lbl.setAttribute("dominant-baseline","central");
    lbl.style.cssText = "font-size:9px;fill:#64748b;font-family:-apple-system,sans-serif;";
    lbl.textContent = String(h).padStart(2,"0")+"h";
    g.appendChild(lbl);
  }}

  setCenter(null);
}})();
</script>
"""
    if st.session_state.get("ea_theme_pref") == "dark":
        html = "<style>html,body{background:#161b27 !important;margin:0;}</style>" + html
        for _a, _b in [("#f6f7fb", "#161b27"), ("background: white", "background: #161b27"),
                       ("#eaecf0", "#1d2331"), ("#cbd5e1", "#3a4256"),
                       ("background:white", "background:#161b27"),
                       ("#ffffff", "#161b27"), ("#fff", "#161b27"),
                       ("#64748b", "#9aa4b4"), ("#e2e8f0", "#262c3b"),
                       ("#0f172a", "#e8ebf1"), ("#334155", "#c9d0dc"),
                       ("rgba(72,0,255,0.06)", "rgba(139,124,255,0.16)"),
                       ("rgba(72,0,255,0.12)", "rgba(139,124,255,0.28)")]:
            html = html.replace(_a, _b)
    components.html(html, height=460, scrolling=False)


def _sessions_tab(f: pd.DataFrame, show_table):
    st.markdown('<div class="section">', unsafe_allow_html=True)
    if f.empty or "Session Norm" not in f.columns or f["Session Norm"].isna().all():
        st.info("No session data.")
    else:
        counted = f[f["Outcome"].isin(["Win", "BE", "Loss"])]
        rates = []
        for sess, g in counted.groupby("Session Norm"):
            r = outcome_rates_from(g)
            net_rr, ex_rr = _rr_stats(g)
            rates.append(dict(Session=sess, Trades=len(g),
                              **{"Win %": r["win_rate"], "BE %": r["be_rate"], "Loss %": r["loss_rate"],
                                 "Net PnL (R)": net_rr, "Expectancy (R)": ex_rr}))
        df_rates = pd.DataFrame(rates).sort_values("Win %", ascending=False)
        st.markdown("### Session Expectancy")
        st.caption("Average R per trade by session.")
        if not df_rates.empty:
            best = df_rates.iloc[0]
            worst = df_rates.iloc[-1]
            if best["Session"] != worst["Session"] and best["Win %"] - worst["Win %"] > 10:
                _insight_box(
                    f"<b>{best['Session']}</b> is your best session at <b>{best['Win %']:.1f}%</b> win rate. "
                    f"<b>{worst['Session']}</b> trails at <b>{worst['Win %']:.1f}%</b>. "
                    f"Concentrate trade frequency in {best['Session']} and reduce exposure in {worst['Session']}.", "info")
        _flip("sess_flip",
              lambda: _rank_dots(df_rates, "Session", "Expectancy (R)"),
              lambda: render_session_performance_table(df_rates, title="Session Performance"))
    st.markdown("</div>", unsafe_allow_html=True)


def _instruments_tab(f: pd.DataFrame, show_table):
    st.markdown('<div class="section">', unsafe_allow_html=True)
    if f is None or f.empty:
        st.info("No trades for current filters.")
        st.markdown("</div>", unsafe_allow_html=True)
        return
    g = _ensure_instrument_column(f)
    if "Instrument" not in g.columns:
        st.info("No instrument/pair column detected.")
        st.markdown("</div>", unsafe_allow_html=True)
        return
    g = g.copy()
    g["Instrument"] = g["Instrument"].astype(str).str.strip()
    g = g[g["Instrument"] != ""]
    if g["Instrument"].nunique() <= 1:
        # one asset = nothing to compare — stay silent, like account comparison
        st.markdown("</div>", unsafe_allow_html=True)
        return
    if g.empty:
        st.info("No instrument values present.")
        st.markdown("</div>", unsafe_allow_html=True)
        return
    counted = g[g["Outcome"].isin(["Win", "BE", "Loss"])]
    if counted.empty:
        st.info("No counted outcomes yet for any instrument.")
        st.markdown("</div>", unsafe_allow_html=True)
        return
    rows = []
    for inst, g_inst in counted.groupby("Instrument"):
        r = outcome_rates_from(g_inst)
        net_rr, ex_rr = _rr_stats(g_inst)
        rows.append(dict(Instrument=_asset_label(inst), Trades=len(g_inst),
                         **{"Win %": r["win_rate"], "BE %": r["be_rate"], "Loss %": r["loss_rate"],
                            "Net PnL (R)": net_rr, "Expectancy (R)": ex_rr}))
    if rows:
        inst_df = pd.DataFrame(rows).sort_values("Win %", ascending=False).reset_index(drop=True)
        render_entry_model_table(inst_df, title="Asset Performance")
        if not inst_df.empty:
            best_inst = inst_df.iloc[0]
            worst_inst = inst_df.iloc[-1]
            if len(inst_df) > 1 and best_inst["Instrument"] != worst_inst["Instrument"]:
                _insight_box(
                    f"<b>{best_inst['Instrument']}</b> is your best-performing asset at "
                    f"<b>{best_inst['Win %']:.1f}%</b> win rate. "
                    f"<b>{worst_inst['Instrument']}</b> trails at <b>{worst_inst['Win %']:.1f}%</b>. "
                    f"Focus on assets where your system has trending HTF conditions — "
                    f"the playbook principle of switching pairs when conditions don't suit your edge.")
    else:
        st.info("No instrument stats available.")
    st.markdown("</div>", unsafe_allow_html=True)


def _time_days_tab(f: pd.DataFrame, show_table):
    st.markdown('<div class="section">', unsafe_allow_html=True)
    counted = f[f["Outcome"].isin(["Win", "BE", "Loss"])]
    day_col = "DayName" if "DayName" in counted.columns else ("Day" if "Day" in counted.columns else None)
    if not day_col or counted.empty:
        st.info("No day-of-week signal in current slice.")
        st.markdown("</div>", unsafe_allow_html=True)
        return
    order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
    df_days = counted[counted[day_col].isin(order)].copy()
    if df_days.empty:
        st.info("No Mon–Fri data in current slice.")
        st.markdown("</div>", unsafe_allow_html=True)
        return
    df_days["__Day"] = pd.Categorical(df_days[day_col], categories=order, ordered=True)

    def _agg_day(g):
        r = outcome_rates_from(g)
        net_rr, ex_rr = _rr_stats(g)
        return pd.Series({"Trades": len(g), "Win %": r["win_rate"], "BE %": r["be_rate"],
                           "Loss %": r["loss_rate"], "Net PnL (R)": net_rr, "Expectancy (R)": ex_rr})

    perf = (df_days.groupby("__Day").apply(_agg_day).reset_index()
            .rename(columns={"__Day": "Day"}))
    st.markdown("### Day-of-Week Expectancy")
    from edge_analysis.ui.mt5_tabs import _line_metric
    from edge_analysis.ui.theme import get_chart_styler
    _line_rows = perf.copy()
    _line_rows["Avg R"] = pd.to_numeric(_line_rows.get("Expectancy (R)"), errors="coerce")
    _line_rows["Category"] = _line_rows["Day"].astype(str).str[:3]
    _flip("days_flip",
          lambda: _line_metric(_line_rows, "", get_chart_styler(), value="Avg R",
                               x_order=["Mon", "Tue", "Wed", "Thu", "Fri"], x_title=""),
          lambda: render_day_performance_table(perf.sort_values("Day"),
                                               title="Day Performance (Mon\u2013Fri)"))
    if not perf.empty and "Win %" in perf.columns:
        best_day = perf.loc[perf["Win %"].idxmax()]
        worst_day = perf.loc[perf["Win %"].idxmin()]
        if best_day["Day"] != worst_day["Day"]:
            _insight_box(
                f"<b>{best_day['Day']}</b> is your strongest day at <b>{best_day['Win %']:.1f}%</b> "
                f"win rate ({int(best_day['Trades'])} trades). "
                f"<b>{worst_day['Day']}</b> is your weakest at <b>{worst_day['Win %']:.1f}%</b>. "
                f"Consider reducing trade frequency on {worst_day['Day']}.")
    st.markdown("</div>", unsafe_allow_html=True)


def _gap_alignment_tab(f: pd.DataFrame, show_table):
    st.markdown('<div class="section">', unsafe_allow_html=True)
    if f is None or f.empty or "Gap Alignment" not in f.columns:
        st.info("No GAP Alignment data in current slice.")
        st.markdown("</div>", unsafe_allow_html=True)
        return
    g = f.copy()
    counted = g[g["Outcome"].isin(["Win", "BE", "Loss"])]
    counted["Gap Alignment"] = counted["Gap Alignment"].astype(str).str.strip()
    counted = counted[~counted["Gap Alignment"].isin(["", "nan", "NaN", "None"])]
    if counted.empty:
        st.info("No counted outcomes with GAP Alignment set.")
        st.markdown("</div>", unsafe_allow_html=True)
        return
    rows = []
    for ga, group in counted.groupby("Gap Alignment"):
        r = outcome_rates_from(group)
        net_rr, ex_rr = _rr_stats(group)
        rows.append(dict(Entry_Model=ga, Trades=len(group),
                         **{"Win %": r["win_rate"], "BE %": r["be_rate"], "Loss %": r["loss_rate"],
                            "Net PnL (R)": net_rr, "Expectancy (R)": ex_rr}))
    if rows:
        render_entry_model_table(pd.DataFrame(rows).sort_values("Entry_Model").reset_index(drop=True),
                                 title="GAP Alignment")
    else:
        st.info("No GAP Alignment stats available.")
    st.markdown("</div>", unsafe_allow_html=True)


def _parse_target_rr_label(label: str):
    if label is None:
        return None
    s = str(label).lower().replace("rr", "").strip().replace(" ", "")
    if not s:
        return None
    m = re.match(r"^([+-]?\d+(?:\.\d+)?)[-–]([+-]?\d+(?:\.\d+)?)$", s)
    if m:
        return (float(m.group(1)) + float(m.group(2))) / 2.0
    m = re.match(r"^([+-]?\d+(?:\.\d+)?)\+$", s)
    if m:
        return float(m.group(1))
    try:
        return float(s)
    except Exception:
        return None


def _target_rr_tab(f: pd.DataFrame, show_table):
    st.markdown('<div class="section">', unsafe_allow_html=True)
    if f is None or f.empty or "Targeted RR" not in f.columns:
        st.info("No Target RR data in current slice.")
        st.markdown("</div>", unsafe_allow_html=True)
        return
    g = f.copy()
    counted = g[g["Outcome"].isin(["Win", "BE", "Loss"])]
    counted["Targeted RR"] = counted["Targeted RR"].astype(str).str.strip()
    counted = counted[counted["Targeted RR"] != ""]
    if counted.empty:
        st.info("No counted outcomes with Target RR set.")
        st.markdown("</div>", unsafe_allow_html=True)
        return
    rows = []
    for target, group in counted.groupby("Targeted RR"):
        r = outcome_rates_from(group)
        net_rr, ex_rr = _rr_stats(group)
        rows.append(dict(Target_RR=target, Trades=len(group),
                         **{"Win %": r["win_rate"], "BE %": r["be_rate"], "Loss %": r["loss_rate"],
                            "Net PnL (R)": net_rr, "Expectancy (R)": ex_rr}))
    if rows:
        df_rr = pd.DataFrame(rows)
        df_rr["_sort_num"] = df_rr["Target_RR"].apply(_parse_target_rr_label)
        df_rr = (df_rr.sort_values(["_sort_num", "Target_RR"], na_position="last")
                 .drop(columns=["_sort_num"]).reset_index(drop=True)
                 .rename(columns={"Target_RR": "Entry_Model"}))
        render_entry_model_table(df_rr, title="Risk to Reward")
    else:
        st.info("No Target RR stats available.")
    st.markdown("</div>", unsafe_allow_html=True)


def _parse_rr_value(v):
    """Parse RR strings like '+2-3', '1-2', '10+', or plain floats into a midpoint float."""
    s = str(v).strip().replace("RR", "").strip()
    try:
        return float(s)
    except ValueError:
        pass
    m = re.match(r"^([+-]?\d+(?:\.\d+)?)[^\d]+(\d+(?:\.\d+)?)$", s)
    if m:
        return (float(m.group(1)) + float(m.group(2))) / 2
    m2 = re.match(r"^(\d+)\+$", s)
    if m2:
        return float(m2.group(1))
    return None


def _slider_row(label: str, fmt, make_widget):
    """One clean settings row: label left, bare slider middle, bold value right.
    On phones: stacked single-column so nothing overlaps."""
    if st.session_state.get("layout_mode") == "mobile":
        st.markdown(f"<div style='font-size:13px;color:#64748b;'>{label}</div>",
                    unsafe_allow_html=True)
        val = make_widget()
        st.markdown(f"<div style='text-align:right;font-size:13px;font-weight:700;"
                    f"color:#4800ff;margin-top:-8px;'>{fmt(val)}</div>",
                    unsafe_allow_html=True)
        return val
    c1, c2, c3 = st.columns([2.6, 5.4, 1.6], vertical_alignment="center")
    with c1:
        st.markdown(f"<div style='font-size:13px;color:#64748b;'>{label}</div>",
                    unsafe_allow_html=True)
    with c2:
        val = make_widget()
    with c3:
        st.markdown(f"<div style='font-size:14px;font-weight:700;color:#4800ff;"
                    f"text-align:right;white-space:nowrap;'>{fmt(val)}</div>",
                    unsafe_allow_html=True)
    return val


def _div_vs_sweep(f: pd.DataFrame) -> None:
    """Head-to-head: Divergence vs Sweep, the two entry criteria."""
    if f is None or f.empty:
        return
    g = f.copy()
    rr_col = next((c for c in ["Closed RR", "RR", "Closed R"] if c in g.columns), None)
    if rr_col is None or "DIV?" not in g.columns or "Sweep?" not in g.columns:
        return
    g["__rr"] = pd.to_numeric(g[rr_col], errors="coerce")
    g = g[g["__rr"].notna()]
    if len(g) < 8:
        return

    def _yes(col):
        return g[col].astype(str).str.strip().str.lower().isin(["yes", "true", "__yes__", "1"])

    div, swp = _yes("DIV?"), _yes("Sweep?")

    def _stats(mask):
        sub = g.loc[mask, "__rr"]
        if len(sub) < 3:
            return None
        return dict(n=int(len(sub)), avg=float(sub.mean()),
                    win=100.0 * float((sub > 0.15).sum()) / len(sub))

    d_s, s_s = _stats(div), _stats(swp)
    if d_s is None and s_s is None:
        return
    st.markdown("### DIV vs Sweep")
    st.caption("Your two entry criteria head to head \u2014 average R per trade when each is present.")
    head = []
    if d_s:
        head.append({"Category": "Divergence \u00b7 yes", "Avg R": round(d_s["avg"], 2),
                     "Trades": d_s["n"], "Win %": d_s["win"]})
    if s_s:
        head.append({"Category": "Sweep \u00b7 yes", "Avg R": round(s_s["avg"], 2),
                     "Trades": s_s["n"], "Win %": s_s["win"]})

    def _dvs_table():
        trows = []
        for lab, mask in (("Sweep", swp), ("DIV", div)):
            sub = g.loc[mask, "__rr"]
            if len(sub) < 3:
                continue
            n_ = len(sub)
            trows.append({"Entry_Model": lab, "Trades": n_,
                          "Win %": round(100.0 * float((sub > 0.15).sum()) / n_, 2),
                          "BE %": round(100.0 * float(((sub >= -0.15) & (sub <= 0.15)).sum()) / n_, 2),
                          "Loss %": round(100.0 * float((sub < -0.15).sum()) / n_, 2),
                          "Net PnL (R)": round(float(sub.sum()), 2),
                          "Expectancy (R)": round(float(sub.mean()), 2)})
        if trows:
            render_entry_model_table(pd.DataFrame(trows), title="DIV vs Sweep — full numbers")

    _flip("dvs_flip",
          lambda: _edge_tiles(head, "Category", "Avg R"),
          _dvs_table)
    combos = []
    for lab, m in (("Both DIV + Sweep", div & swp), ("DIV only", div & ~swp),
                   ("Sweep only", swp & ~div), ("Neither", ~div & ~swp)):
        s_ = _stats(m)
        if s_:
            combos.append({"Category": lab, "Avg R": round(s_["avg"], 2),
                           "Trades": s_["n"], "Win %": s_["win"]})
    if d_s and s_s and (d_s["n"] + s_s["n"]) >= 8:
        better = "Divergence" if d_s["avg"] > s_s["avg"] else "Sweep"
        worse = "Sweep" if better == "Divergence" else "Divergence"
        bv = max(d_s["avg"], s_s["avg"]); wv = min(d_s["avg"], s_s["avg"])
        _insight_box(
            f"<b>{better}</b> is the stronger criterion right now ({bv:+.2f}R vs {wv:+.2f}R for {worse}). "
            + (f"Best combination: <b>{max(combos, key=lambda r: r['Avg R'])['Category']}</b> "
               f"({max(combos, key=lambda r: r['Avg R'])['Avg R']:+.2f}R)." if combos else ""))


def _flag_verdicts(f: pd.DataFrame, scope: str = "entry"):
    """Collect per-flag average-R verdicts. scope='entry' = entry criteria;
    scope='external' = market externals (volatility, news, gap)."""
    if f is None or f.empty:
        return []
    g = f.copy()
    rr_col = next((c for c in ["Closed RR", "RR", "Closed R"] if c in g.columns), None)
    if rr_col is None:
        return []
    g["__rr"] = pd.to_numeric(g[rr_col], errors="coerce")
    g = g[g["__rr"].notna()]
    if len(g) < 8:
        return []

    def _yes(col):
        return g[col].astype(str).str.strip().str.lower().isin(["yes", "true", "__yes__", "1"])

    rows = []
    if scope == "entry":
        checkbox = [("Clear Bias/Prepared", "Prepared / clear bias"),
                    ("Opposing Weak Structure?", "Opposing weak structure"),
                    ("Oversold or Overbought?", "OB/OS extreme"),
                    ("Sweep?", "Sweep"), ("DIV?", "Divergence"),
                    ("True Break?", "True break"),
                    ("Multi Entry Model Setup", "Multi-entry")]
    else:
        checkbox = []
    for col, label in checkbox:
        if col not in g.columns:
            continue
        m = _yes(col)
        known = g[col].astype(str).str.strip().str.lower().isin(
            ["yes", "no", "true", "false", "__yes__", "__no__", "1", "0"])
        for lab, mask in ((f"{label} · yes", m & known), (f"{label} · no", ~m & known)):
            n = int(mask.sum())
            if n >= 3:
                rows.append({"Category": lab, "Avg R": round(float(g.loc[mask, "__rr"].mean()), 2),
                             "Trades": n})
    if scope == "entry":
        cats = ["Entry Timeframe", "Tiers in pricing HTF", "Tiers in pricing MTF",
                "Stop Loss + Covering", "Breakeven Criteria"]
    else:
        cats = ["Volatility", "News Aspect", "GAP Alignment"]
    for col in cats:
        if col not in g.columns:
            continue
        vals = (g[col].astype(str).str.replace(r'[\[\]"]', "", regex=True).str.strip())
        for val, sub in g.groupby(vals):
            if not val or val.lower() in ("nan", "none", "na", ""):
                continue
            if len(sub) >= 3:
                short = col.replace("Tiers in pricing ", "Tiers ").replace("?", "")
                if scope != "entry" and any(ch.isalpha() for ch in val):
                    lab = val[:34]  # value reads on its own — column prefix is noise
                else:
                    lab = f"{short} · {val[:24]}"
                rows.append({"Category": lab,
                             "Avg R": round(float(sub["__rr"].mean()), 2), "Trades": len(sub)})
    return rows


def _double_confirmation_section(f: pd.DataFrame) -> None:
    """Expectancy with vs without a double-confirmation (multi-entry) setup."""
    if f is None or f.empty:
        return
    col = next((c for c in ["Multi Entry Model Setup", "Double Confirmation"]
                if c in f.columns), None)
    if col is None:
        return
    g = f.copy()
    rr_col = next((c for c in ["Closed RR", "RR", "Closed R"] if c in g.columns), None)
    if rr_col is None:
        return
    g["__rr"] = pd.to_numeric(g[rr_col], errors="coerce")
    g = g[g["__rr"].notna()]
    if len(g) < 8:
        return
    raw = g[col].astype(str).str.strip()
    if col == "Multi Entry Model Setup":
        yes = raw.str.lower().isin(["yes", "true", "__yes__", "1"])
        known = raw.str.lower().isin(["yes", "no", "true", "false", "__yes__", "__no__", "1", "0"])
    else:
        yes = raw.str.contains("Double Confirmation", case=False, na=False)
        known = ~raw.str.lower().isin(["", "nan", "none", "na", "[]", '["n/a"]'])

    def _stats(mask):
        sub = g.loc[mask, "__rr"]
        if len(sub) < 3:
            return None
        return dict(n=int(len(sub)), avg=float(sub.mean()),
                    win=100.0 * float((sub > 0.15).sum()) / len(sub))

    y, n_ = _stats(yes & known), _stats(~yes & known)
    if y is None and n_ is None:
        return
    st.markdown("### Double confirmation")
    st.caption("Setups with a second confirmation stacked on the entry versus single-confirmation entries.")
    rows = []
    if y:
        rows.append({"Category": "Double confirmation", "Avg R": round(y["avg"], 2),
                     "Trades": y["n"], "Win %": y["win"]})
    if n_:
        rows.append({"Category": "Single confirmation", "Avg R": round(n_["avg"], 2),
                     "Trades": n_["n"], "Win %": n_["win"]})
    def _dc_table():
        trows = []
        for lab, mask in (("Double confirmation", yes & known),
                          ("Single confirmation", ~yes & known)):
            sub = g.loc[mask, "__rr"]
            if len(sub) < 3:
                continue
            n2 = len(sub)
            trows.append({"Entry_Model": lab, "Trades": n2,
                          "Win %": round(100.0 * float((sub > 0.15).sum()) / n2, 2),
                          "BE %": round(100.0 * float(((sub >= -0.15) & (sub <= 0.15)).sum()) / n2, 2),
                          "Loss %": round(100.0 * float((sub < -0.15).sum()) / n2, 2),
                          "Net PnL (R)": round(float(sub.sum()), 2),
                          "Expectancy (R)": round(float(sub.mean()), 2)})
        if trows:
            render_entry_model_table(pd.DataFrame(trows), title="Double confirmation \u2014 full numbers")

    _flip("dc_flip",
          lambda: _edge_tiles(rows, "Category", "Avg R"),
          _dc_table)
    if y and n_ and (y["n"] + n_["n"]) >= 8:
        diff = y["avg"] - n_["avg"]
        lead = ("Double confirmation is earning its wait" if diff > 0
                else "Double confirmation isn't paying yet")
        _insight_box(f"{lead}: <b>{diff:+.2f}R per trade</b> versus single-confirmation entries "
                     f"({y['avg']:+.2f}R over {y['n']} vs {n_['avg']:+.2f}R over {n_['n']}).")


def _entry_criteria(f: pd.DataFrame) -> None:
    """All logged entry criteria head to head: DIV, Sweep, double confirmation."""
    if f is None or f.empty:
        return
    g = f.copy()
    rr_col = next((c for c in ["Closed RR", "RR", "Closed R"] if c in g.columns), None)
    if rr_col is None:
        return
    g["__rr"] = pd.to_numeric(g[rr_col], errors="coerce")
    g = g[g["__rr"].notna()]
    if len(g) < 8:
        return

    def _yes(col):
        return g[col].astype(str).str.strip().str.lower().isin(["yes", "true", "__yes__", "1"])

    masks = []
    if "Sweep?" in g.columns:
        masks.append(("Sweep", _yes("Sweep?")))
    if "DIV?" in g.columns:
        masks.append(("Divergence", _yes("DIV?")))
    dc_col = next((c for c in ["Multi Entry Model Setup", "Double Confirmation"]
                   if c in g.columns), None)
    if dc_col:
        if dc_col == "Multi Entry Model Setup":
            m = _yes(dc_col)
        else:
            m = g[dc_col].astype(str).str.contains("Double Confirmation", case=False, na=False)
        masks.append(("Double confirmation", m))
    rows, trows = [], []
    for lab, m in masks:
        sub = g.loc[m, "__rr"]
        if len(sub) < 3:
            continue
        n_ = len(sub)
        rows.append({"Category": lab, "Avg R": round(float(sub.mean()), 2),
                     "Trades": n_, "Win %": 100.0 * float((sub > 0.15).sum()) / n_})
        trows.append({"Entry_Model": lab, "Trades": n_,
                      "Win %": round(100.0 * float((sub > 0.15).sum()) / n_, 2),
                      "BE %": round(100.0 * float(((sub >= -0.15) & (sub <= 0.15)).sum()) / n_, 2),
                      "Loss %": round(100.0 * float((sub < -0.15).sum()) / n_, 2),
                      "Net PnL (R)": round(float(sub.sum()), 2),
                      "Expectancy (R)": round(float(sub.mean()), 2)})
    if not rows:
        return
    st.markdown("### Entry criteria")
    st.caption("Each criterion you log, measured when it was present \u00b7 min 3 trades.")
    if len(rows) >= 2:
        best = max(rows, key=lambda r: r["Avg R"])
        worst = min(rows, key=lambda r: r["Avg R"])
        if (best["Trades"] + worst["Trades"]) >= 8 and best["Category"] != worst["Category"]:
            _insight_box(
                f"<b>{best['Category']}</b> is the strongest criterion right now "
                f"({best['Avg R']:+.2f}R over {best['Trades']}). "
                f"<b>{worst['Category']}</b> trails at {worst['Avg R']:+.2f}R.")
    _flip("crit_flip",
          lambda: _edge_tiles(rows, "Category", "Avg R"),
          lambda: render_entry_model_table(pd.DataFrame(trows),
                                           title="Entry criteria \u2014 full numbers"))


def _breaker_strip(df_raw: pd.DataFrame) -> None:
    """Circuit-breaker status: month MTD vs the max-loss line, week volume vs 3."""
    if df_raw is None or df_raw.empty or "Date" not in df_raw.columns:
        return
    g = df_raw.copy()
    g["__dt"] = pd.to_datetime(g["Date"], errors="coerce")
    try:
        from edge_analysis.ui.plan_tabs import get_tz_offset
        if getattr(g["__dt"].dt, "tz", None) is not None:
            g["__dt"] = g["__dt"].dt.tz_localize(None)
        g["__dt"] = g["__dt"] + pd.Timedelta(hours=get_tz_offset(g))
    except Exception:
        pass
    g = g[g["__dt"].notna()]
    rr_col = next((c for c in ["Closed RR Num", "Closed RR", "RR", "Closed R"] if c in g.columns), None)
    if rr_col is None or g.empty:
        return
    g["__rr"] = pd.to_numeric(g[rr_col], errors="coerce")
    g = g[g["__rr"].notna()]
    if g.empty:
        return
    stop_r = float(st.session_state.get("ea_m_stop", -6.0))
    _rp_b = _risk_pct(g.rename(columns={"__rr": "PnL_from_RR"}))
    wk_cap = max(1, round(int(st.session_state.get("ea_m_cap", 12)) / 4))
    now = pd.Timestamp.now()
    cur = g[g["__dt"].dt.to_period("M") == now.to_period("M")]
    mtd = float(cur["__rr"].sum()) if not cur.empty else 0.0
    mon = (now - pd.Timedelta(days=int(now.dayofweek))).normalize()
    wk_n = int((g["__dt"] >= mon).sum())
    closed = mtd <= stop_r
    if closed:
        bg, bc, ic, icon = "#fde8e8", "#f3b8b8", "#7f1d1d", "\u25a0"
        head = "Month closed \u2014 circuit breaker hit"
        sub = (f"{_as_pct(mtd, _rp_b):+.2f}% ({mtd:+.1f}R) this month is at your "
               f"{_as_pct(stop_r, _rp_b):+.1f}% max loss. "
               "Flat until the 1st \u2014 that's the rule that keeps the account.")
    else:
        room = mtd - stop_r
        warn = room < 2 or wk_n > wk_cap
        bg, bc = ("#fdf6e8", "#ecd4a2") if warn else ("#e9f7ef", "#bfe6cd")
        ic = "#7c4a03" if warn else "#14532d"
        icon = "\u26a0" if warn else "\u2713"
        head = "Circuit breaker \u2014 month open"
        bits = [f"{_as_pct(mtd, _rp_b):+.2f}% this month ({mtd:+.1f}R)",
                f"{_as_pct(room, _rp_b):.2f}% above the {_as_pct(stop_r, _rp_b):+.1f}% stop",
                f"{wk_n} of {wk_cap} trades this week"]
        sub = " \u00b7 ".join(bits)
    st.markdown(
        f"<div style='display:flex;align-items:center;gap:14px;background:{bg};"
        f"border:1px solid {bc};border-radius:12px;padding:13px 18px;margin:2px 0 10px;'>"
        f"<div style='font-size:19px;color:{ic};font-weight:800;'>{icon}</div>"
        f"<div><div style='font-size:15.5px;font-weight:800;color:{ic};'>{head}</div>"
        f"<div style='font-size:13px;color:{ic};opacity:0.85;margin-top:1px;'>{sub}</div>"
        f"</div></div>", unsafe_allow_html=True)


def _more_detail_has_content(f: pd.DataFrame, df_all: pd.DataFrame) -> bool:
    """True when the More-detail card would actually show a comparison."""
    try:
        if f is not None and not f.empty:
            g = _ensure_instrument_column(f)
            if "Instrument" in g.columns:
                vals = g["Instrument"].astype(str).str.strip()
                vals = vals[~vals.isin(["", "nan", "NaN", "None"])]
                if vals.nunique() > 1:
                    return True
            lm = {str(c).strip().lower(): c for c in f.columns}
            ac = lm.get("account") or lm.get("accounts") or lm.get("account name")
            if ac is not None:
                av = f[ac].astype(str).str.strip()
                av = av[~av.isin(["", "nan", "NaN", "None"])]
                if av.nunique() > 1:
                    return True
        # early closes now live on the Entry tab (Manual close vs set TP)
    except Exception:
        return True  # never hide data because the probe broke
    return False


def _powered_on_panel(df: pd.DataFrame) -> None:
    """Which app features this journal's columns unlock — and which are present
    but unlogged (column exists, too few values to power anything)."""
    if df is None or df.empty:
        return
    colmap = {str(c).strip(): c for c in df.columns}

    def state(*names):
        present = [colmap[n] for n in names if n in colmap]
        if not present:
            return "off"
        for c in present:
            v = df[c]
            if v.dtype == object:
                nn = v.astype(str).str.strip()
                nn = nn[~nn.isin(["", "nan", "NaN", "None", "[]"])]
                cnt = int(nn.notna().sum())
            else:
                cnt = int(v.notna().sum())
            if cnt >= 3:
                return "on"
        return "unlogged"

    feats = [
        ("Entry models", state("Entry Model", "Entry Models List"), "Entry Model"),
        ("Entry criteria", state("Sweep?", "DIV?", "Multi Entry Model Setup", "Double Confirmation"),
         "Sweep? / DIV? / Multi Entry Model Setup"),
        ("Market conditions", state("Conditions ETF", "Conditions MTF", "Conditions HTF"),
         "Conditions ETF/MTF/HTF"),
        ("Overbought / Oversold", state("Oversold or Overbought?"), "Oversold or Overbought?"),
        ("External factors board", state("Volatility", "News Aspect", "GAP Alignment"),
         "Volatility / News Aspect / GAP Alignment"),
        ("Loss post-mortem", state("Reason of loss"), "Reason of loss"),
        ("Mental state gate", state("Mental State"), "Mental State"),
        ("Timing (sessions & hours)", state("Session", "Session Norm", "Hour (Melb)", "Date"),
         "Session or a datetime column"),
        ("Dollar P&L", state("PnL (USD)", "PnL"), "PnL (USD)"),
        ("Trade efficiency (MAE/MFE)", state("MFE (R)", "MAE (R)"), "MAE (R) / MFE (R)"),
        ("Discipline scorecard", state("Rules Followed?"), "Rules Followed?"),
        ("Mistake leaks", state("Mistake"), "Mistake"),
    ]
    on = sum(1 for _, st_, _ in feats if st_ == "on")
    unlogged = sum(1 for _, st_, _ in feats if st_ == "unlogged")
    st.markdown(f"### What your template powers on")
    cap = f"{on} of {len(feats)} features active"
    if unlogged:
        cap += f" \u00b7 {unlogged} waiting on logged values"
    cap += " \u00b7 add the missing column in Notion to unlock a feature."
    st.caption(cap)
    import html as _h
    parts = []
    for name, st_, need in feats:
        if st_ == "on":
            mark, mc, tc, fw, hint = "\u2713", "#16a34a", "#0f172a", 700, ""
        elif st_ == "unlogged":
            mark, mc, tc, fw = "\u25d0", "#b45309", "#7c4a03", 600
            hint = ("<span style='font-size:11.5px;color:#c9a36a;'>column there \u2014 "
                    "log it on a few trades</span>")
        else:
            mark, mc, tc, fw = "\u2014", "#c3c9d4", "#94a3b8", 500
            hint = ("<span style='font-size:11.5px;color:#c3c9d4;'>needs "
                    + _h.escape(need) + "</span>")
        parts.append(
            "<div style='display:flex;align-items:center;gap:10px;padding:7px 4px;"
            "flex:1 1 46%;min-width:280px;'>"
            f"<span style='color:{mc};font-weight:800;font-size:15px;'>{mark}</span>"
            f"<span style='font-size:13.5px;font-weight:{fw};color:{tc};'>{_h.escape(name)}</span>"
            + hint + "</div>")
    rows = "".join(parts)
    st.markdown("<div style='display:flex;flex-wrap:wrap;gap:0 18px;'>" + rows + "</div>",
                unsafe_allow_html=True)


def _obos_section(f: pd.DataFrame) -> None:
    """Overbought/Oversold extreme vs not — expectancy head to head."""
    if f is None or f.empty or "Oversold or Overbought?" not in f.columns:
        return
    g = f.copy()
    rr_col = next((c for c in ["Closed RR", "RR", "Closed R"] if c in g.columns), None)
    if rr_col is None:
        return
    g["__rr"] = pd.to_numeric(g[rr_col], errors="coerce")
    g = g[g["__rr"].notna()]
    if len(g) < 8:
        return
    raw = g["Oversold or Overbought?"].astype(str).str.strip().str.lower()
    yes = raw.isin(["yes", "true", "__yes__", "1"])
    known = raw.isin(["yes", "no", "true", "false", "__yes__", "__no__", "1", "0"])

    def _stats(mask):
        sub = g.loc[mask, "__rr"]
        if len(sub) < 3:
            return None
        return dict(n=int(len(sub)), avg=float(sub.mean()),
                    win=100.0 * float((sub > 0.15).sum()) / len(sub))

    y, n_ = _stats(yes & known), _stats(~yes & known)
    if y is None and n_ is None:
        return
    st.markdown("### Overbought / Oversold")
    st.caption("Entering at an OB/OS extreme vs not \u2014 what each is worth per trade.")
    rows = []
    if y:
        rows.append({"Category": "At OB/OS extreme", "Avg R": round(y["avg"], 2),
                     "Trades": y["n"], "Win %": y["win"]})
    if n_:
        rows.append({"Category": "Not at extreme", "Avg R": round(n_["avg"], 2),
                     "Trades": n_["n"], "Win %": n_["win"]})
    _edge_tiles(rows, "Category", "Avg R")
    if y and n_ and (y["n"] + n_["n"]) >= 8:
        diff = y["avg"] - n_["avg"]
        lead = "OB/OS extremes are paying you" if diff > 0 else "OB/OS extremes are costing you"
        _insight_box(f"{lead}: <b>{diff:+.2f}R per trade</b> versus entries away from an extreme "
                     f"({y['avg']:+.2f}R over {y['n']} vs {n_['avg']:+.2f}R over {n_['n']}).")


def _confluence_board(f: pd.DataFrame, scope: str = "entry") -> None:
    """Ranked board of flag verdicts (used for the Externals factors board)."""
    rows = _flag_verdicts(f, scope)
    if not rows:
        return
    if scope == "entry":
        st.markdown("### Confluence Board")
        st.caption("Your entry criteria, ranked by what each is actually worth per trade "
                   "(min 3 trades). Green = stack these. Red = these cost you.")
    else:
        st.markdown("### External Factors Board")
        st.caption("Market conditions around your trades — volatility, news and gaps — "
                   "ranked by average R (min 3 trades).")
    d = pd.DataFrame(rows).sort_values("Avg R", ascending=False)
    if len(d) > 18:
        d = pd.concat([d.head(9), d.tail(9)])
    _rank_dots(d, "Category", "Avg R")
    d8 = d[pd.to_numeric(d["Trades"], errors="coerce") >= 8]
    if len(d8) < 2:
        return
    best, worst = d8.iloc[0], d8.iloc[-1]
    kind = "confluence" if scope == "entry" else "condition"
    _insight_box(
        f"Strongest {kind}: <b>{best['Category']}</b> ({best['Avg R']:+.2f}R over {int(best['Trades'])}). "
        f"Costliest: <b>{worst['Category']}</b> ({worst['Avg R']:+.2f}R over {int(worst['Trades'])}).")


_LOSS_THEMES = [
    ("Wrong bias", ("wrong bias", "opposing", "against the bias", "htf bias", "mtf bias")),
    ("Structure misread", ("structure", "protected high", "protected low", "fbos", "bos",
                           "internal", "external", "liquidity")),
    ("Management / BE", ("be ", "breakeven", "break even", "moved stop", "aggressive",
                         "didnt cover", "didn't cover", "management", "trail")),
    ("Entry timing", ("early", "chased", "late entry", "pullback", "entry was", "timing")),
    ("News / volatility", ("news", "spike", "volatile", "nfp", "cpi")),
    ("Execution error", ("execution", "mistake", "poor exec", "fat finger", "wrong size")),
]


def _loss_theme(text: str) -> str:
    t = " " + str(text).lower() + " "
    for name, keys in _LOSS_THEMES:
        if any(k in t for k in keys):
            return name
    return "Other"


def _loss_postmortem(f: pd.DataFrame) -> None:
    """Where the losses come from, grouped into themes from your own tags."""
    if f is None or f.empty or "Reason of loss" not in f.columns:
        return
    g = f.copy()
    rr_col = next((c for c in ["Closed RR Num", "Closed RR", "RR", "Closed R"]
                   if c in g.columns), None)
    if rr_col is None:
        return
    g["__rr"] = pd.to_numeric(g[rr_col], errors="coerce")
    losses = g[g["__rr"] < -0.15].copy()
    losses["__why"] = (losses["Reason of loss"].astype(str)
                       .str.replace(r'[\[\]"]', "", regex=True).str.strip())
    losses = losses[~losses["__why"].str.lower().isin(["", "nan", "none", "na"])]
    if losses.empty:
        return
    st.markdown("### Loss Post-Mortem")
    prose = bool(losses["__why"].str.len().median() > 24)
    if prose:
        st.caption("Your written loss notes, grouped into themes \u2014 ranked by the R they cost. "
                   "The notes themselves stay on each trade in the Weekly debrief.")
        losses["__theme"] = losses["__why"].map(_loss_theme)
        key = "__theme"
    else:
        st.caption("Your own Reason-of-loss tags \u2014 where the red actually comes from.")
        key = "__why"
    rows = []
    for why, sub in losses.groupby(key):
        rows.append({"Category": str(why), "Avg R": round(float(sub["__rr"].mean()), 2),
                     "Trades": len(sub), "Net R": round(float(sub["__rr"].sum()), 1)})
    d = pd.DataFrame(rows).sort_values("Net R")
    _rank_dots(d, "Category", "Net R", fmt="+.1f")
    worst = d.iloc[0]
    _wn = int(worst["Trades"])
    if prose:
        _example = (losses[losses["__theme"] == worst["Category"]]
                    .sort_values("__rr")["__why"].iloc[0])
        _example = _html.escape(str(_example)[:150]).strip()
        _insight_box(f"<b>{_html.escape(str(worst['Category']))}</b> is your most expensive "
                     f"failure mode: <b>{worst['Net R']:+.1f}R</b> across {_wn} "
                     f"loss{'es' if _wn != 1 else ''}. Your own words on the worst one: "
                     f"\u201c{_example}\u2026\u201d One rule that eliminates this theme is worth "
                     f"more than a new setup.", "bad")
    else:
        _insight_box(f"\u201c{_html.escape(str(worst['Category']))}\u201d is your most expensive "
                     f"failure mode: <b>{worst['Net R']:+.1f}R</b> across {_wn} "
                     f"loss{'es' if _wn != 1 else ''}. One rule that eliminates it is worth more "
                     f"than a new setup.", "bad")


_EA_GREEN, _EA_RED, _EA_GREY = "#16a34a", "#ef4444", "#9ca3af"

_EA_VIZ_CSS = """<style>
.ea-pb{display:flex;flex-direction:column;gap:7px;margin:6px 0 10px;}
.ea-pb-row{display:flex;align-items:center;gap:10px;}
.ea-pb-lab{flex:0 0 34%;max-width:230px;min-width:0;text-align:right;font-size:13px;font-weight:600;
  color:#0f172a;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.ea-pb-n{color:#94a3b8;font-weight:500;font-size:11px;margin-left:6px;}
.ea-pb-track{flex:1;position:relative;background:#f8fafc;border-radius:7px;height:14px;}
.ea-pb-bar{height:14px;}
.ea-pb-zero{position:absolute;left:50%;top:-3px;bottom:-3px;border-left:1.5px dashed #cbd5e1;}
.ea-pb-val{flex:0 0 62px;font-size:12.5px;font-weight:700;}
@media (max-width:640px){.ea-pb-lab{flex-basis:40%;font-size:12px;}}
.ea-et-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin:6px 0 10px;}
.ea-et{background:#ffffff;border:1px solid #eef0f4;border-left:4px solid #9ca3af;
  border-radius:0 10px 10px 0;padding:10px 12px;}
.ea-et-lab{font-size:11.5px;color:#64748b;min-height:30px;line-height:1.3;}
.ea-et-val{font-size:19px;font-weight:700;margin:2px 0 7px;}
.ea-et-meter{height:4px;background:#f1f5f9;border-radius:2px;overflow:hidden;}
.ea-et-meter div{height:4px;border-radius:2px;}
.ea-et-meta{font-size:11px;color:#94a3b8;margin-top:7px;}
.ea-ew-wrap{max-width:660px;margin:0 auto;}
.ea-ew-wrap svg{width:100%;height:auto;display:block;}
.ea-ew-val{font-size:10.5px;font-weight:700;}
.ea-ew-name{font-size:9px;fill:#64748b;}
.ea-ew-hub{fill:#f8fafc;}
.ea-ew-hublab{font-size:11px;fill:#64748b;}
.ea-ew-hubval{font-size:15px;font-weight:700;}
</style>"""


def _edge_color(v: float) -> str:
    if v > 0.005:
        return _EA_GREEN
    if v < -0.005:
        return _EA_RED
    return _EA_GREY


def _rank_frame(rows, cat_col, val_col):
    d = pd.DataFrame(rows).copy()
    d["__v"] = pd.to_numeric(d[val_col], errors="coerce")
    return d[d["__v"].notna()].sort_values("__v", ascending=False).reset_index(drop=True)


def _rank_dots(rows, cat_col, val_col, fmt="+.2f", suffix="R") -> None:
    """House power bars: diverging from a dashed zero line, green right / red left."""
    import html as _h
    d = _rank_frame(rows, cat_col, val_col)
    if d.empty:
        return
    mx = max(abs(float(d["__v"].max())), abs(float(d["__v"].min())), 1e-9)
    out = [_EA_VIZ_CSS, '<div class="ea-pb">']
    for _, r in d.iterrows():
        v = float(r["__v"]); c = _edge_color(v)
        w = max(3.0, abs(v) / mx * 50.0)
        chip = ""
        if "Trades" in d.columns and pd.notna(r.get("Trades")):
            chip = f'<span class="ea-pb-n">{int(r["Trades"])}</span>'
        name = _h.escape(str(r[cat_col]))
        if v >= 0:
            bar = (f'<div class="ea-pb-bar" style="margin-left:50%;width:{w:.1f}%;'
                   f'background:{c};border-radius:0 7px 7px 0;"></div>')
        else:
            bar = (f'<div class="ea-pb-bar" style="margin-left:{50 - w:.1f}%;width:{w:.1f}%;'
                   f'background:{c};border-radius:7px 0 0 7px;"></div>')
        out.append(
            f'<div class="ea-pb-row"><div class="ea-pb-lab" title="{name}">{name}{chip}</div>'
            f'<div class="ea-pb-track">{bar}<div class="ea-pb-zero"></div></div>'
            f'<div class="ea-pb-val" style="color:{c};">{v:{fmt}}{suffix}</div></div>')
    out.append("</div>")
    st.markdown("".join(out), unsafe_allow_html=True)


def _edge_tiles(rows, cat_col, val_col, fmt="+.2f", suffix="R") -> None:
    """Card grid: one striped tile per category with the value and a magnitude meter."""
    import html as _h
    d = _rank_frame(rows, cat_col, val_col)
    if d.empty:
        return
    mx = max(abs(float(d["__v"].max())), abs(float(d["__v"].min())), 1e-9)
    out = [_EA_VIZ_CSS, '<div class="ea-et-grid">']
    for _, r in d.iterrows():
        v = float(r["__v"]); c = _edge_color(v)
        w = max(4, int(round(abs(v) / mx * 100)))
        name = _h.escape(str(r[cat_col]))
        meta = []
        if "Win %" in d.columns and pd.notna(r.get("Win %")):
            meta.append(f'{float(r["Win %"]):.0f}% win')
        if "Trades" in d.columns and pd.notna(r.get("Trades")):
            _tn = int(r["Trades"])
            meta.append(f'{_tn} trade' + ("s" if _tn != 1 else ""))
        meta_html = f'<div class="ea-et-meta">{" &middot; ".join(meta)}</div>' if meta else ""
        out.append(
            f'<div class="ea-et" style="border-left-color:{c};">'
            f'<div class="ea-et-lab" title="{name}">{name}</div>'
            f'<div class="ea-et-val" style="color:{c};">{v:{fmt}}{suffix}</div>'
            f'<div class="ea-et-meter"><div style="width:{w}%;background:{c};"></div></div>'
            f'{meta_html}</div>')
    out.append("</div>")
    st.markdown("".join(out), unsafe_allow_html=True)


def _edge_wheel(rows, cat_col, val_col, fmt="+.2f") -> None:
    """Radial edge wheel (hourly-clock style): one wedge per flag, length = magnitude."""
    import html as _h
    import math
    d = _rank_frame(rows, cat_col, val_col)
    if len(d) < 5:
        _rank_dots(rows, cat_col, val_col, fmt=fmt)
        return
    if len(d) > 16:
        d = pd.concat([d.head(8), d.tail(8)]).reset_index(drop=True)
    mx = max(abs(float(d["__v"].max())), abs(float(d["__v"].min())), 1e-9)
    n = len(d); cx = 330.0; cy = 235.0; r0 = 56.0; rmax = 156.0

    def _p(rad, a):
        return (cx + rad * math.cos(a), cy + rad * math.sin(a))

    parts = []
    for i, (_, r) in enumerate(d.iterrows()):
        v = float(r["__v"]); c = _edge_color(v)
        a0 = (i / n) * 2 * math.pi - math.pi / 2 + 0.025
        a1 = ((i + 1) / n) * 2 * math.pi - math.pi / 2 - 0.025
        rr = r0 + max(abs(v) / mx, 0.10) * (rmax - r0)
        x0, y0 = _p(r0, a0); x1, y1 = _p(r0, a1)
        x2, y2 = _p(rr, a1); x3, y3 = _p(rr, a0)
        name = _h.escape(str(r[cat_col]))
        tip = f"{name}: {v:{fmt}}R"
        if "Trades" in d.columns and pd.notna(r.get("Trades")):
            tip += f" &middot; {int(r['Trades'])} trades"
        parts.append(
            f'<path d="M{x0:.1f},{y0:.1f} A{r0:.0f},{r0:.0f} 0 0 1 {x1:.1f},{y1:.1f} '
            f'L{x2:.1f},{y2:.1f} A{rr:.1f},{rr:.1f} 0 0 0 {x3:.1f},{y3:.1f} Z" '
            f'fill="{c}" opacity="0.92"><title>{tip}</title></path>')
        am = (a0 + a1) / 2
        vx, vy = _p(rr + 15, am)
        parts.append(f'<text x="{vx:.1f}" y="{vy:.1f}" class="ea-ew-val" fill="{c}" '
                     f'text-anchor="middle" dominant-baseline="middle">{v:{fmt}}</text>')
        lx, ly = _p(206, am)
        cs = math.cos(am)
        anch = "start" if cs > 0.02 else ("end" if cs < -0.02 else "middle")
        short = str(r[cat_col])
        short = short[:24] + "\u2026" if len(short) > 25 else short
        parts.append(f'<text x="{lx:.1f}" y="{ly:.1f}" class="ea-ew-name" '
                     f'text-anchor="{anch}" dominant-baseline="middle">{_h.escape(short)}'
                     f'<title>{tip}</title></text>')
    best = d.iloc[0]
    bc = _edge_color(float(best["__v"]))
    parts.append(f'<circle cx="{cx:.0f}" cy="{cy:.0f}" r="{r0 - 9:.0f}" class="ea-ew-hub"/>')
    parts.append(f'<text x="{cx:.0f}" y="{cy - 8:.0f}" text-anchor="middle" '
                 f'class="ea-ew-hublab">best flag</text>')
    parts.append(f'<text x="{cx:.0f}" y="{cy + 13:.0f}" text-anchor="middle" '
                 f'class="ea-ew-hubval" fill="{bc}">{float(best["__v"]):{fmt}}R</text>')
    st.markdown(_EA_VIZ_CSS + '<div class="ea-ew-wrap"><svg viewBox="0 0 660 470" '
                'role="img">' + "".join(parts) + "</svg></div>", unsafe_allow_html=True)


def _liquidity_windows(f: pd.DataFrame) -> None:
    """Your edge by market-volume tier (approximate, local time)."""
    if f is None or f.empty:
        return
    rr_col = next((c for c in ["Closed RR Num", "Closed RR", "RR", "Closed R"] if c in f.columns), None)
    if rr_col is None:
        return
    g = f.copy()
    g["__rr"] = pd.to_numeric(g[rr_col], errors="coerce")
    g = g[g["__rr"].notna()]
    if len(g) < 8:
        return
    hr = pd.to_numeric(g.get("Hour (Melb)"), errors="coerce") if "Hour (Melb)" in g.columns else None
    if hr is None or not hr.notna().any():
        _dt = pd.to_datetime(g.get("Date", pd.Series(dtype=object)).astype(str)
                             .str.replace(r"\s*\(GMT.*\)$", "", regex=True), errors="coerce")
        try:
            if getattr(_dt.dt, "tz", None) is not None:
                _dt = _dt.dt.tz_localize(None)
            from edge_analysis.ui.plan_tabs import get_tz_offset
            _dt = _dt + pd.Timedelta(hours=get_tz_offset(g))
        except Exception:
            pass
        hr = _dt.dt.hour
    g["__hr"] = hr
    g = g[pd.notna(g["__hr"])]
    if len(g) < 8:
        return

    def _tier(h):
        h = int(h)
        if h >= 22 or h < 3:
            return "Peak volume \u00b7 NY + overlap"
        if 17 <= h < 22:
            return "Rising \u00b7 London"
        if 3 <= h < 7:
            return "Fading \u00b7 late NY"
        return "Dead \u00b7 Asia / pre-session"

    g["__tier"] = g["__hr"].map(_tier)
    rows = []
    for name, sub in g.groupby("__tier"):
        if len(sub) < 3:
            continue
        rows.append({"Window": name, "Avg R": round(float(sub["__rr"].mean()), 2),
                     "Trades": len(sub)})
    if len(rows) < 2:
        return
    st.markdown("### Liquidity Windows")
    st.caption("Your average R by market-volume tier (approximate gold/FX volume in your local "
               "time) \u00b7 min 3 trades per window.")
    _rank_dots(pd.DataFrame(rows), "Window", "Avg R")
    d_ = {r["Window"]: r for r in rows}
    pk = next((v for k, v in d_.items() if k.startswith("Peak")), None)
    dd = next((v for k, v in d_.items() if k.startswith("Dead")), None)
    if pk and dd and pk["Trades"] >= 5 and dd["Trades"] >= 5:
        gap = pk["Avg R"] - dd["Avg R"]
        if gap > 0.3:
            _insight_box(
                f"Volume is paying you: peak-volume windows average <b>{pk['Avg R']:+.2f}R</b> "
                f"({pk['Trades']} trades) vs <b>{dd['Avg R']:+.2f}R</b> in dead hours "
                f"({dd['Trades']}). That's <b>{gap:+.2f}R per trade</b> for trading when "
                "the market is actually moving \u2014 your session rule in one number.")

def _conditions_tab(f: pd.DataFrame, show_table):
    st.markdown('<div class="section">', unsafe_allow_html=True)
    st.markdown("### Conditions")

    if f is None or f.empty:
        st.info("No trades for current filters.")
        st.markdown("</div>", unsafe_allow_html=True)
        return

    c_etf = "Conditions ETF" if "Conditions ETF" in f.columns else None
    c_mtf = "Conditions MTF" if "Conditions MTF" in f.columns else None
    c_htf = "Conditions HTF" if "Conditions HTF" in f.columns else None
    present_cols = [c for c in [c_etf, c_mtf, c_htf] if c]
    tf_labels = {"Conditions ETF": "ETF", "Conditions MTF": "MTF", "Conditions HTF": "HTF"}

    if not present_cols:
        st.info("No Conditions ETF/MTF/HTF columns in current data.")
        st.markdown("</div>", unsafe_allow_html=True)
        return

    g = f.copy()
    rr_col = next((c for c in ["Closed RR", "RR", "Closed R"] if c in g.columns), None)
    g["__rr"] = g[rr_col].map(_parse_rr_value) if rr_col else float("nan")

    for col in present_cols:
        g[col] = g[col].astype(str).str.strip().replace(
            {"": None, "nan": None, "NaN": None, "None": None}
        )

    counted = g[g["Outcome"].isin(["Win", "BE", "Loss"])]
    mask = pd.Series(False, index=counted.index)
    for col in present_cols:
        mask = mask | counted[col].notna()
    counted = counted[mask]

    if counted.empty:
        st.info("No Conditions values in current slice.")
        st.markdown("</div>", unsafe_allow_html=True)
        return

    def _expectancy(grp):
        rr = grp["__rr"].dropna()
        return float(rr.mean()) if len(rr) > 0 else float("nan")

    tf_titles = {"Conditions ETF": "Entry TF", "Conditions MTF": "Middle TF",
                 "Conditions HTF": "Higher TF"}
    st.caption("Average R per trade in each market state \u00b7 cells need 3+ trades.")
    all_rows = []
    grid = []
    for col in present_cols:
        col_data = counted[counted[col].notna()].copy()
        cells = {}
        for state in ("Trending", "Ranging"):
            grp = col_data[col_data[col].astype(str).str.contains(state, case=False, na=False)]
            rr = grp["__rr"].dropna()
            if len(grp) >= 3 and len(rr) > 0:
                avg = float(rr.mean())
                cells[state] = (f"{avg:+.2f}R \u00b7 {len(grp)}t",
                                "#16a34a" if avg >= 0 else "#ef4444")
                all_rows.append({"Condition": f"{tf_titles.get(col, col)} \u00b7 {state}",
                                 "Expectancy": avg, "N": len(grp)})
            elif len(grp) > 0:
                cells[state] = (f"\u2014  ({len(grp)}t)", "#c3c9d4")
            else:
                cells[state] = ("\u2014", "#c3c9d4")
        grid.append((tf_titles.get(col, col), cells))
    bar_rows = []
    hidden = 0
    for col in present_cols:
        col_data = counted[counted[col].notna()].copy()
        for state in ("Trending", "Ranging"):
            grp = col_data[col_data[col].astype(str).str.contains(state, case=False, na=False)]
            rr = grp["__rr"].dropna()
            if len(grp) >= 3 and len(rr) > 0:
                avg = float(rr.mean())
                bar_rows.append({"Category": f"{tf_titles.get(col, col)} \u00b7 {state}",
                                 "Avg R": round(avg, 2), "Trades": len(grp)})
                all_rows.append({"Condition": f"{tf_titles.get(col, col)} \u00b7 {state}",
                                 "Expectancy": avg, "N": len(grp)})
            elif len(grp) > 0:
                hidden += 1
    if not bar_rows:
        st.caption("Not enough logged conditions yet \u2014 rows appear at 3+ trades per state.")
    else:
        _rank_dots(bar_rows, "Category", "Avg R")
        if hidden:
            st.caption(f"+{hidden} more state{'s' if hidden != 1 else ''} with under 3 trades "
                       "\u2014 shown once they have a sample.")

    all_rows = [r for r in all_rows if r.get("N", 0) >= 8]
    if all_rows:
        best_ind = max(all_rows, key=lambda x: x["Expectancy"])
        worst_ind = min(all_rows, key=lambda x: x["Expectancy"])
        _insight_box(
            f"Best condition: <b>{best_ind['Condition']}</b> "
            f"(<b>{best_ind['Expectancy']:+.2f}R</b> per trade). "
            f"Worst: <b>{worst_ind['Condition']}</b> "
            f"(<b>{worst_ind['Expectancy']:+.2f}R</b>)."
        )

    st.markdown("</div>", unsafe_allow_html=True)


def _timeframes_tab(f: pd.DataFrame, show_table):
    st.markdown('<div class="section">', unsafe_allow_html=True)
    if f is None or f.empty:
        st.info("No trades for current filters.")
        st.markdown("</div>", unsafe_allow_html=True)
        return
    lower_map = {str(c).strip().lower(): c for c in f.columns}
    tf_col = (lower_map.get("entry timeframe") or lower_map.get("timeframe")
              or lower_map.get("time frame") or lower_map.get("tf"))
    if tf_col is None:
        st.info("No 'Timeframe' column found in current data.")
        st.markdown("</div>", unsafe_allow_html=True)
        return
    g = f.copy()
    g["__TF"] = g[tf_col].astype(str).str.strip()
    g = g[~g["__TF"].isin(["", "nan", "NaN", "None"])]
    if g.empty:
        st.info("No timeframe values present.")
        st.markdown("</div>", unsafe_allow_html=True)
        return
    counted = g[g["Outcome"].isin(["Win", "BE", "Loss"])]
    if counted.empty:
        st.info("No counted outcomes yet for any timeframe.")
        st.markdown("</div>", unsafe_allow_html=True)
        return
    _TF_ORDER = {
        "1m": 1, "2m": 2, "3m": 3, "5m": 5, "10m": 10, "15m": 15, "30m": 30, "45m": 45,
        "1h": 60, "2h": 120, "3h": 180, "4h": 240, "6h": 360, "8h": 480, "12h": 720,
        "1d": 1440, "d": 1440, "daily": 1440,
        "1w": 10080, "w": 10080, "weekly": 10080,
        "1mo": 43200, "monthly": 43200,
    }

    def _tf_sort_key(label):
        return _TF_ORDER.get(str(label).strip().lower(), 9999)

    rows = []
    for tf, group in counted.groupby("__TF"):
        r = outcome_rates_from(group)
        rr_series = pd.to_numeric(group.get("Closed RR", pd.Series(dtype=float)),
                                   errors="coerce").dropna()
        avg_rr = round(float(rr_series.mean()), 2) if not rr_series.empty else None
        wins_rr = rr_series[rr_series > 0].sum()
        losses_rr = abs(rr_series[rr_series < 0].sum())
        profit_factor = round(wins_rr / losses_rr, 2) if losses_rr > 0 else None
        rows.append(dict(Timeframe=tf, Trades=len(group),
                         **{"Win %": r["win_rate"], "BE %": r["be_rate"], "Loss %": r["loss_rate"],
                            "Avg RR": avg_rr, "Profit Factor": profit_factor}))
    if not rows:
        st.info("No timeframe stats available.")
        st.markdown("</div>", unsafe_allow_html=True)
        return
    tf_df = (pd.DataFrame(rows)
             .assign(_sort=lambda d: d["Timeframe"].apply(_tf_sort_key))
             .sort_values(["_sort", "Timeframe"]).drop(columns=["_sort"])
             .reset_index(drop=True).rename(columns={"Timeframe": "Entry_Model"}))
    render_timeframe_table(tf_df, title="Timeframe Performance")
    if (not tf_df.empty and "Win %" in tf_df.columns
            and int(pd.to_numeric(tf_df["Trades"], errors="coerce").max() or 0) >= 8):
        best_tf = tf_df.loc[tf_df["Win %"].idxmax()]
        _insight_box(
            f"<b>{best_tf['Entry_Model']}</b> is your highest-performing timeframe at "
            f"<b>{best_tf['Win %']:.1f}%</b> win rate across {int(best_tf['Trades'])} trades. "
            f"Concentrating executions on your best timeframe reduces noise and "
            f"aligns with the 5M-only refinement from your playbook.")
    st.markdown("</div>", unsafe_allow_html=True)


def _coach_tab(f: pd.DataFrame):
    st.markdown('<div class="section">', unsafe_allow_html=True)
    st.markdown("## Edge Coach (disabled for now)")
    st.info("Coach is hidden for now.")
    st.markdown("</div>", unsafe_allow_html=True)


# ── Coverage tab ──────────────────────────────────────────────────────────────
def _render_data_completeness_by_instrument(f_all: pd.DataFrame):
    st.markdown("### Data Completeness by Instrument")
    if f_all is None or f_all.empty:
        st.info("No rows for the current filters.")
        return
    g = _ensure_instrument_column(f_all.copy())
    if "Instrument" not in g.columns:
        st.info("No instrument-like column found.")
        return
    g["Instrument"] = g["Instrument"].astype(str).str.strip()
    g = g[g["Instrument"] != ""]
    if g.empty:
        st.info("No instrument values present.")
        return
    closed_rr = (pd.to_numeric(g["Closed RR"], errors="coerce")
                 if "Closed RR" in g.columns else pd.Series(index=g.index, dtype=float))
    g["__complete"] = closed_rr.notna()
    agg = (g.groupby("Instrument", dropna=False)
           .agg(total=("Instrument", "size"), complete=("__complete", "sum"))
           .reset_index())
    agg["incomplete"] = agg["total"] - agg["complete"]
    agg = agg.sort_values("Instrument").reset_index(drop=True)
    per_row = 3
    for i in range(0, len(agg), per_row):
        chunk = agg.iloc[i: i + per_row]
        cols = st.columns(len(chunk))
        for col, (_, r) in zip(cols, chunk.iterrows()):
            with col:
                label = _asset_label(r["Instrument"])
                st.markdown(f"""
                    <div class='kpi'>
                      <div class='label'>{label}</div>
                      <div class='value' style='color:#4800ff'>{int(r['total'])}</div>
                      <div class='muted'>Complete: <b>{int(r['complete'])}</b></div>
                      <div class='muted'>Incomplete: <b>{int(r['incomplete'])}</b></div>
                    </div>""", unsafe_allow_html=True)


def _data_tab(f_all: pd.DataFrame, show_table):
    st.markdown('<div class="section">', unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)


# ── Notion templates UI ───────────────────────────────────────────────────────
def render_connect_notion_templates_ui():
    st.markdown('<div class="section">', unsafe_allow_html=True)
    st.markdown("## Connect Notion / Templates")
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("### My Template")
        p1 = Path("assets/templates/my_template.csv")
        if p1.exists():
            st.download_button("⬇️ Download My Template (CSV)", data=p1.read_bytes(),
                               file_name="my_template.csv", mime="text/csv", use_container_width=True)
        else:
            st.warning("Missing: assets/templates/my_template.csv")
    with c2:
        st.markdown("### TradingPools Template")
        p2 = Path("assets/templates/tradingpools_template.csv")
        if p2.exists():
            st.download_button("⬇️ Download TradingPools Template (CSV)", data=p2.read_bytes(),
                               file_name="tradingpools_template.csv", mime="text/csv",
                               use_container_width=True)
        else:
            st.warning("Missing: assets/templates/tradingpools_template.csv")
    st.divider()
    st.subheader("Upload your filled template")
    up = st.file_uploader("CSV/TSV/XLSX supported. Both templates work.",
                          type=["csv", "tsv", "xlsx", "xls"], key="upload_templates_dual")
    if up:
        uploads = Path("uploads")
        uploads.mkdir(parents=True, exist_ok=True)
        fpath = uploads / up.name
        with open(fpath, "wb") as f:
            f.write(up.getbuffer())
        df, mapping_name = adapt_auto(fpath, "config/templates")
        if mapping_name:
            st.success(f"Detected template: **{mapping_name}**")
        else:
            st.warning("No mapping detected. Add a JSON mapping under config/templates/ if needed.")
        issues = []
        for col in ["Date", "Pair", "Outcome", "Closed RR", "Is Complete"]:
            if col not in df.columns:
                issues.append(f"Missing required column: {col}")
        if "Outcome" in df.columns:
            bad = ~df["Outcome"].isin(["Win", "BE", "Loss"]) & df["Outcome"].notna()
            if bad.any():
                issues.append("Unexpected Outcome values: " +
                               str(list(df.loc[bad, "Outcome"].astype(str).unique()[:5])))
        if issues:
            st.info("Checks:\n\n- " + "\n- ".join(issues))
        st.dataframe(df.head(25), use_container_width=True)
    st.markdown("</div>", unsafe_allow_html=True)


# ── Projections Tab ───────────────────────────────────────────────────────────
@st.cache_data(show_spinner=False, max_entries=8)
def _mc_paths(n_paths: int, total_trades: int, wr: float, be: float,
              avg_win: float, loss_rr: float, risk_pct: float, start_bal: float):
    """Monte-Carlo equity paths. Cached so reruns (nav, filters, theme) don't
    recompute or re-serialise a chart payload the browser already has."""
    _rng = np.random.default_rng(42)
    draws = _rng.random((n_paths, total_trades))
    is_win = draws < wr
    is_be = (~is_win) & (draws < wr + be)
    rr_matrix = np.where(is_win, avg_win, np.where(is_be, 0.0, -loss_rr))
    equity = start_bal * np.cumprod(1 + rr_matrix * (risk_pct / 100.0), axis=1)
    return rr_matrix, equity


def _projections_tab(df_raw: pd.DataFrame, styler) -> None:
    from scipy import stats as scipy_stats

    st.markdown("""
    <style>
    .proj-stat-grid {
        display: grid;
        grid-template-columns: repeat(4, 1fr);
        gap: 12px;
        margin: 16px 0;
    }
    .proj-stat-cell {
        background: #f8f8ff;
        border: 1px solid #e8e0ff;
        border-radius: 10px;
        padding: 14px 16px;
        text-align: center;
    }
    .proj-stat-label {
        font-size: 11px;
        font-weight: 700;
        letter-spacing: 0.06em;
        text-transform: uppercase;
        color: #94a3b8;
        margin-bottom: 4px;
    }
    .proj-stat-value {
        font-size: 1.15rem;
        font-weight: 700;
        color: #4800ff;
    }
    .proj-table-header {
        background: #f4f2ff;
        color: #1a0066;
        padding: 10px 14px;
        border-radius: 8px 8px 0 0;
        font-weight: 700;
        font-size: 0.9rem;
        display: grid;
        grid-template-columns: 1fr 1fr 1fr;
        text-align: center;
    }
    .proj-table-row {
        display: grid;
        grid-template-columns: 1fr 1fr 1fr;
        padding: 7px 14px;
        font-size: 0.82rem;
        text-align: center;
        border-bottom: 1px solid #f0ecff;
    }
    .proj-table-row:nth-child(even) { background: #faf8ff; }
    .proj-table-total {
        display: grid;
        grid-template-columns: 1fr 1fr 1fr;
        padding: 10px 14px;
        font-weight: 700;
        font-size: 0.85rem;
        text-align: center;
        background: #f4f2ff;
        color: #1a0066;
        border-radius: 0 0 8px 8px;
    }
    .proj-positive { color: #00a86b; font-weight: 600; }
    .proj-negative { color: #e03131; font-weight: 600; }
    @media (max-width: 768px) {
        .proj-stat-grid { grid-template-columns: repeat(2, 1fr); }
    }
    </style>
    """, unsafe_allow_html=True)

    # ── Derive baseline stats ─────────────────────────────────────────────────
    df = df_raw.copy()

    result_col = next(
        (c for c in df.columns if c.lower() in ("result", "outcome", "trade result")),
        None
    )
    rr_col = next(
        (c for c in df.columns if "closed rr" in c.lower() or c.lower() == "closed rr"),
        None
    )

    # Prefer Outcome over Result for Win/Loss classification
    outcome_col = "Outcome" if "Outcome" in df.columns else result_col

    if rr_col is None or outcome_col is None:
        st.warning("Couldn't find required columns (Outcome / Closed RR).")
        return

    df[rr_col] = pd.to_numeric(df[rr_col], errors="coerce")
    df_counted = df[df[outcome_col].isin(["Win", "Loss"])].dropna(subset=[rr_col])

    wins   = df_counted[df_counted[outcome_col] == "Win"]
    losses = df_counted[df_counted[outcome_col] == "Loss"]
    total  = len(df_counted)

    if total == 0:
        st.warning("No Win/Loss trades with Closed RR found — add more complete trades to use this tab.")
        return

    n_be = int((df[outcome_col] == "BE").sum())
    total_incl_be = total + n_be
    base_wr          = round(len(wins) / max(1, total_incl_be), 4)
    base_be          = round(n_be / max(1, total_incl_be), 4)
    base_avg_win_rr  = round(wins[rr_col].mean(), 2)  if len(wins)   > 0 else 1.5
    base_avg_loss_rr = round(abs(losses[rr_col].mean()), 2) if len(losses) > 0 else 1.0

    # Derive avg trades/month from date column
    # Prefer the canonical, already-parsed "Date" column; fall back to any
    # date/time-like raw column only if it is missing.
    date_col = "Date" if "Date" in df_raw.columns else next(
        (c for c in df_raw.columns if any(k in c.lower() for k in ("date", "time"))),
        None
    )
    base_trades_per_month = 10
    if date_col:
        try:
            dates = pd.to_datetime(
                df_raw[date_col].astype(str).str.replace(r"\s*\(GMT.*\)$", "", regex=True),
                errors="coerce"
            ).dropna()
            if len(dates) > 1:
                months_span = max((dates.max() - dates.min()).days / 30.44, 1)
                base_trades_per_month = max(1, round(len(df_raw) / months_span))
        except Exception:
            pass

    # ── Header (card title comes from the card) ──────────────────────────────
    st.caption(
        f"Auto-filled from **{total_incl_be} completed trades** — "
        f"Win rate: **{base_wr:.1%}** · Break-even: **{base_be:.1%}** · "
        f"Avg win RR: **{base_avg_win_rr}** · Avg loss RR: **{base_avg_loss_rr}** · "
        f"Est. trades/month: **{base_trades_per_month}**"
    )

    # ── Inputs (applied when you press Run) ──────────────────────────────────
    with st.form("proj_settings", border=False):
        starting_balance = _slider_row(
            "Starting balance", lambda v: f"${v:,.0f}",
            lambda: st.slider("Starting balance", min_value=1_000, max_value=200_000,
                              value=int(min(200_000, max(1_000, round(
                                  float(st.session_state.get("ea_m_bal", 10_000)) / 100.0
                              ) * 100))),
                              step=1_000, key="proj_balance",
                              label_visibility="collapsed"))
        risk_pct = _slider_row(
            "Risk per trade", lambda v: f"{v:.2f}%",
            lambda: st.slider("Risk per trade", min_value=0.25, max_value=10.0,
                              value=float(min(10.0, max(0.25, round(
                                  float(st.session_state.get("ea_m_risk", 1.0)) * 4
                              ) / 4))),
                              step=0.25, key="proj_risk",
                              label_visibility="collapsed"))
        win_rate_input = _slider_row(
            "Winning trades", lambda v: f"{v}%",
            lambda: st.slider("Winning trades", min_value=10, max_value=90,
                              value=int(min(90, max(10, base_wr * 100))), step=1,
                              key="proj_wr", label_visibility="collapsed"))
        be_rate_input = _slider_row(
            "Break-even trades", lambda v: f"{v}%",
            lambda: st.slider("Break-even trades", min_value=0, max_value=60,
                              value=int(min(60, max(0, round(base_be * 100)))), step=1,
                              key="proj_be", label_visibility="collapsed"))
        avg_win_rr = _slider_row(
            "Average win", lambda v: f"{v:.1f}R",
            lambda: st.slider("Average win", min_value=0.1, max_value=15.0,
                              value=float(min(15.0, max(0.1, base_avg_win_rr))), step=0.1,
                              key="proj_win_rr", label_visibility="collapsed"))
        trades_per_month = _slider_row(
            "Trades per month", lambda v: f"{v}",
            lambda: st.slider("Trades per month", min_value=1, max_value=200,
                              value=int(min(200, max(1, base_trades_per_month))), step=1,
                              key="proj_tpm", label_visibility="collapsed"))
        total_months = _slider_row(
            "Months to project", lambda v: f"{v} mo",
            lambda: st.slider("Months to project", min_value=1, max_value=120,
                              value=24, step=1, key="proj_months",
                              label_visibility="collapsed"))
        if st.form_submit_button("Run projection", type="primary"):
            st.session_state["proj_ran"] = True

    # ── Run simulation ────────────────────────────────────────────────────────
    N_PATHS      = 500
    wr_frac      = win_rate_input / 100.0
    be_frac      = min(be_rate_input / 100.0, max(0.0, 1.0 - wr_frac))
    total_trades = int(trades_per_month) * int(total_months)
    loss_rr      = base_avg_loss_rr  # always from real data

    rng = np.random.default_rng(42)
    rr_matrix, equity_paths = _mc_paths(N_PATHS, total_trades, wr_frac, be_frac,
                                        float(avg_win_rr), float(loss_rr),
                                        float(risk_pct), float(starting_balance))

    final_balances = equity_paths[:, -1]
    median_idx = int(np.argsort(final_balances)[N_PATHS // 2])
    best_idx   = int(np.argmax(final_balances))
    worst_idx  = int(np.argmin(final_balances))

    scenario_indices = {
        "Most Possible": median_idx,
        "Worst":         worst_idx,
        "Best":          best_idx,
    }

    # ── Per-path stats ────────────────────────────────────────────────────────
    def path_stats(path_idx: int) -> dict:
        eq   = np.concatenate([[starting_balance], equity_paths[path_idx]])
        peak = np.maximum.accumulate(eq)
        dd   = (eq - peak) / peak
        max_dd = float(dd.min())

        outcomes = rr_matrix[path_idx]
        max_cl = max_cw = cur_l = cur_w = 0
        for o in outcomes:
            if o < 0:
                cur_l += 1; cur_w = 0
            else:
                cur_w += 1; cur_l = 0
            max_cl = max(max_cl, cur_l)
            max_cw = max(max_cw, cur_w)

        return {
            "result_balance":  float(eq[-1]),
            "total_return":    float((eq[-1] / starting_balance) - 1),
            "max_dd":          max_dd,
            "max_loss_streak": max_cl,
            "max_win_streak":  max_cw,
            "actual_wr":       float(np.mean(rr_matrix[path_idx] > 0)),
        }

    def monthly_breakdown(path_idx: int) -> list:
        rows = []
        balance  = starting_balance
        t_idx    = 0
        tpm      = int(trades_per_month)
        from datetime import date
        _t = date.today()
        for m in range(int(total_months)):
            _ym   = _t.year * 12 + _t.month + m   # first projected month = next month
            year  = _ym // 12
            month = _ym % 12 + 1
            month_rr = rr_matrix[path_idx, t_idx: t_idx + tpm]
            t_idx   += tpm
            start_bal = balance
            for rr in month_rr:
                balance *= (1 + rr * risk_pct / 100.0)
            rows.append({
                "year":   year,
                "month":  month,
                "pct":    (balance - start_bal) / start_bal,
                "dollar": balance - start_bal,
            })
        return rows

    stats = {k: path_stats(v) for k, v in scenario_indices.items()}
    MONTHS = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]

    # ── Scenario toggle ───────────────────────────────────────────────────────
    st.markdown("---")
    selected = st.radio(
        "Scenario", options=["Most Possible", "Worst", "Best"],
        horizontal=True, label_visibility="collapsed", key="proj_scenario"
    )

    active_idx   = scenario_indices[selected]
    active_stats = stats[selected]

    # ── Spaghetti chart ───────────────────────────────────────────────────────
    trade_axis  = np.arange(0, total_trades + 1)
    # keep the payload small: ~80 points per path, 30 background paths
    step        = max(1, total_trades // 80)
    sample_idxs = rng.choice(N_PATHS, size=min(30, N_PATHS), replace=False)

    bg_rows = []
    for i in sample_idxs:
        eq_path = np.concatenate([[starting_balance], equity_paths[i]])
        for t, b in zip(trade_axis[::step], eq_path[::step]):
            bg_rows.append({"trade": int(t), "balance": float(b), "path": str(i)})

    hl_rows = []
    for label, pidx in scenario_indices.items():
        eq_path = np.concatenate([[starting_balance], equity_paths[pidx]])
        for t, b in zip(trade_axis[::step], eq_path[::step]):
            hl_rows.append({"trade": int(t), "balance": float(b), "Scenario": label})

    bg_chart = (
        alt.Chart(alt.Data(values=bg_rows))
        .mark_line(opacity=0.06, strokeWidth=1, color="#4800ff")
        .encode(
            x=alt.X("trade:Q", title="Trade #"),
            y=alt.Y("balance:Q", title="Balance ($)", axis=alt.Axis(format="$,.0f")),
            detail="path:N"
        )
    )

    hl_chart = (
        alt.Chart(alt.Data(values=hl_rows))
        .mark_line(strokeWidth=2.5)
        .encode(
            x="trade:Q",
            y="balance:Q",
            color=alt.Color(
                "Scenario:N",
                scale=alt.Scale(
                    domain=["Most Possible", "Worst", "Best"],
                    range=["#4800ff", "#e03131", "#00a86b"]
                ),
                legend=alt.Legend(title=None, orient="top-left")
            ),
            tooltip=[
                alt.Tooltip("trade:Q", title="Trade"),
                alt.Tooltip("Scenario:N"),
                alt.Tooltip("balance:Q", title="Balance", format="$,.0f"),
            ]
        )
    )

    rule = (
        alt.Chart(alt.Data(values=[{"y": float(starting_balance)}]))
        .mark_rule(strokeDash=[4, 4], color="#aaa", strokeWidth=1)
        .encode(y="y:Q")
    )

    with st.spinner("Simulating…"):
        st.altair_chart(
            styler((bg_chart + hl_chart + rule).properties(height=360)),
            use_container_width=True
        )

    # ── Stats cards ───────────────────────────────────────────────────────────
    s = active_stats
    ret_sign = "+" if s["total_return"] >= 0 else ""
    prob_profit = float(np.mean(final_balances > starting_balance))

    st.markdown(f"""
    <div class="proj-stat-grid">
        <div class="proj-stat-cell">
            <div class="proj-stat-label">Initial Balance</div>
            <div class="proj-stat-value">${starting_balance:,.0f}</div>
        </div>
        <div class="proj-stat-cell">
            <div class="proj-stat-label">Result Balance</div>
            <div class="proj-stat-value">${s['result_balance']:,.0f}</div>
        </div>
        <div class="proj-stat-cell">
            <div class="proj-stat-label">Total Return</div>
            <div class="proj-stat-value">{ret_sign}{s['total_return']:.1%}</div>
        </div>
        <div class="proj-stat-cell">
            <div class="proj-stat-label">Max Drawdown</div>
            <div class="proj-stat-value">{s['max_dd']:.1%}</div>
        </div>
        <div class="proj-stat-cell">
            <div class="proj-stat-label">Max Consec. Losses</div>
            <div class="proj-stat-value">{s['max_loss_streak']}</div>
        </div>
        <div class="proj-stat-cell">
            <div class="proj-stat-label">Max Consec. Wins</div>
            <div class="proj-stat-value">{s['max_win_streak']}</div>
        </div>
        <div class="proj-stat-cell">
            <div class="proj-stat-label">Simulated Win Rate</div>
            <div class="proj-stat-value">{s['actual_wr']:.1%}</div>
        </div>
        <div class="proj-stat-cell">
            <div class="proj-stat-label">Prob. of Profit</div>
            <div class="proj-stat-value">{prob_profit:.1%}</div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # ── Monthly breakdown ─────────────────────────────────────────────────────
    st.markdown("#### Monthly Breakdown")
    monthly = monthly_breakdown(active_idx)

    years_dict: dict = {}
    for row in monthly:
        years_dict.setdefault(row["year"], []).append(row)

    year_list = sorted(years_dict.keys())

    for row_start in range(0, len(year_list), 3):
        chunk = year_list[row_start: row_start + 3]
        cols  = st.columns(len(chunk))
        for col, yr in zip(cols, chunk):
            yr_rows        = years_dict[yr]
            yr_total_pct   = sum(r["pct"]    for r in yr_rows)
            yr_total_dollar = sum(r["dollar"] for r in yr_rows)

            header = f'<div class="proj-table-header"><span>{yr}</span><span>Results %</span><span>Results $</span></div>'
            body   = ""
            for r in yr_rows:
                pct_cls = "proj-positive" if r["pct"] >= 0 else "proj-negative"
                dol_cls = "proj-positive" if r["dollar"] >= 0 else "proj-negative"
                pct_str = f"{'+' if r['pct'] >= 0 else ''}{r['pct']:.1%}"
                dol_str = f"{'$' if r['dollar'] >= 0 else '-$'}{abs(r['dollar']):,.0f}"
                body += (
                    f'<div class="proj-table-row">'
                    f'<span>{MONTHS[r["month"]-1]}</span>'
                    f'<span class="{pct_cls}">{pct_str}</span>'
                    f'<span class="{dol_cls}">{dol_str}</span>'
                    f'</div>'
                )

            tot_pct_str = f"{'+' if yr_total_pct >= 0 else ''}{yr_total_pct:.1%}"
            tot_dol_str = f"{'$' if yr_total_dollar >= 0 else '-$'}{abs(yr_total_dollar):,.0f}"
            footer = (
                f'<div class="proj-table-total">'
                f'<span>Total</span>'
                f'<span>{tot_pct_str}</span>'
                f'<span>{tot_dol_str}</span>'
                f'</div>'
            )

            with col:
                st.markdown(header + body + footer, unsafe_allow_html=True)

        st.markdown("<br>", unsafe_allow_html=True)

    # ── Win rate CI ───────────────────────────────────────────────────────────
    st.markdown("---")
    st.markdown("#### Win Rate — Confidence vs Sample Size")

    _z = scipy_stats.norm.ppf(0.95)  # 90% two-sided Wilson CI
    sample_sizes = np.arange(10, max(total + 100, 300), 5)
    ci_rows = []
    for n in sample_sizes:
        p = wr_frac
        denom  = 1 + _z ** 2 / n
        centre = (p + _z ** 2 / (2 * n)) / denom
        spread = _z * np.sqrt(p * (1 - p) / n + _z ** 2 / (4 * n ** 2)) / denom
        ci_rows.append({
            "n":    int(n),
            "low":  float(max(0.0, centre - spread)),
            "mid":  float(wr_frac),
            "high": float(min(1.0, centre + spread)),
        })

    ci_df = pd.DataFrame(ci_rows)
    ci_vals = _to_alt_values(ci_df)

    band = (
        alt.Chart(alt.Data(values=ci_vals))
        .mark_area(opacity=0.15, color="#4800ff")
        .encode(x="n:Q", y="low:Q", y2="high:Q")
    )
    line = (
        alt.Chart(alt.Data(values=ci_vals))
        .mark_line(color="#4800ff", strokeWidth=2)
        .encode(
            x=alt.X("n:Q", title="Sample Size (trades)"),
            y=alt.Y("mid:Q", title="Win Rate",
                    axis=alt.Axis(format=".0%"), scale=alt.Scale(zero=False)),
        )
    )
    sample_rule = (
        alt.Chart(alt.Data(values=[{"x": total}]))
        .mark_rule(strokeDash=[4, 4], color="#4800ff", strokeWidth=1.5)
        .encode(x="x:Q")
    )

    st.altair_chart(
        styler((band + line + sample_rule).properties(height=220)),
        use_container_width=True
    )
    st.caption(
        f"Dashed line = your current sample ({total} win/loss trades \u2014 break-evens sit outside the win rate). "
        "Shaded band = 90% confidence interval — narrows as sample grows."
    )



# ─────────────────────────── Refinements Tab ─────────────────────────────────

def _build_refinements_stats(f_perf: pd.DataFrame, df_all_safe: pd.DataFrame) -> dict:
    # collected at the top so the flag verdicts always ride along
    _flags = _flag_verdicts(f_perf, "entry") + _flag_verdicts(f_perf, "external")
    """Compile a stats dict from the current dataframes for the AI prompt."""
    stats: dict = {}

    # ── Overall ───────────────────────────────────────────────────────────────
    if f_perf is not None and not f_perf.empty:
        counted = f_perf[f_perf["Outcome"].isin(["Win", "BE", "Loss"])]
        total = len(counted)
        if total > 0:
            wr = round(counted["Outcome"].eq("Win").sum() / total * 100, 1)
            stats["overall_trades"] = total
            stats["overall_win_rate"] = wr
            net_rr, _ = _rr_stats(counted)
            stats["overall_net_rr"] = round(net_rr, 2) if net_rr is not None else 0.0

    # ── By session ────────────────────────────────────────────────────────────
    sess_col = next((c for c in ["Session Norm", "Session"] if c in (f_perf.columns if f_perf is not None else [])), None)
    if sess_col and f_perf is not None and not f_perf.empty:
        counted = f_perf[f_perf["Outcome"].isin(["Win", "BE", "Loss"])].copy()
        counted["__sess"] = counted[sess_col].apply(_clean_session_value)
        sess_rows = []
        for s, g in counted.groupby("__sess"):
            if s is None:
                continue
            r = outcome_rates_from(g)
            net_rr, _ = _rr_stats(g)
            sess_rows.append({"session": s, "trades": len(g), "win_rate": r["win_rate"],
                               "net_rr": round(net_rr, 2) if net_rr is not None else 0.0})
        stats["by_session"] = sess_rows

    # ── By instrument ─────────────────────────────────────────────────────────
    if f_perf is not None and not f_perf.empty:
        g = _ensure_instrument_column(f_perf.copy())
        if "Instrument" in g.columns:
            counted = g[g["Outcome"].isin(["Win", "BE", "Loss"])].copy()
            counted["Instrument"] = counted["Instrument"].astype(str).str.strip()
            counted = counted[counted["Instrument"].str.len() > 0]
            inst_rows = []
            for inst, sub in counted.groupby("Instrument"):
                r = outcome_rates_from(sub)
                net_rr, _ = _rr_stats(sub)
                inst_rows.append({"instrument": _asset_label(inst), "trades": len(sub),
                                   "win_rate": r["win_rate"],
                                   "net_rr": round(net_rr, 2) if net_rr is not None else 0.0})
            stats["by_instrument"] = inst_rows

    # ── By entry model ────────────────────────────────────────────────────────
    if f_perf is not None and not f_perf.empty:
        f_em = _ensure_entry_models_list(f_perf.copy())
        if "Entry Models List" in f_em.columns:
            em = f_em[f_em["Entry Models List"].apply(lambda x: isinstance(x, (list, tuple)) and len(x) > 0)]
            if not em.empty:
                em = em.explode("Entry Models List", ignore_index=True)
                em = em[em["Entry Models List"].astype(str).str.strip() != ""]
                counted = em[em["Outcome"].isin(["Win", "BE", "Loss"])]
                em_rows = []
                for model, sub in counted.groupby("Entry Models List"):
                    r = outcome_rates_from(sub)
                    net_rr, _ = _rr_stats(sub)
                    em_rows.append({"model": str(model), "trades": len(sub),
                                    "win_rate": r["win_rate"],
                                    "net_rr": round(net_rr, 2) if net_rr is not None else 0.0})
                stats["by_entry_model"] = em_rows

    # ── Psychology / discipline ───────────────────────────────────────────────
    if df_all_safe is not None and not df_all_safe.empty:
        result_col = next((c for c in ["Result", "result"] if c in df_all_safe.columns), None)
        if result_col:
            bbs = df_all_safe[df_all_safe[result_col].astype(str).str.strip() == "Bad Beat"]
            stats["bad_beat_count"] = len(bbs)
            stats["bad_beat_pct"] = round(len(bbs) / max(1, len(df_all_safe)) * 100, 1)

        # early close impact
        if "Result" in df_all_safe.columns:
            ec = df_all_safe[df_all_safe["Result"].isin([
                "Early Close (Ended up being a BE)", "Early Close (Ended up being a win)"])].copy()
            if not ec.empty:
                ec["__closed_mid"] = ec["Closed RR"].apply(_parse_closed_rr_mid)
                ec["__targeted_mid"] = ec["Targeted RR"].apply(_parse_targeted_rr_mid)
                be_g = ec[ec["Result"] == "Early Close (Ended up being a BE)"]
                win_g = ec[ec["Result"] == "Early Close (Ended up being a win)"]
                be_saved = float(be_g["__closed_mid"].sum()) if not be_g.empty else 0.0
                win_left = float((win_g["__closed_mid"] - win_g["__targeted_mid"]).sum()) if not win_g.empty else 0.0
                stats["early_close_net"] = round(be_saved + win_left, 2)
                stats["early_close_be_saved"] = round(be_saved, 2)
                stats["early_close_win_left"] = round(win_left, 2)

        ms_col = next((c for c in ["Mental State", "Mental state", "mental_state"] if c in df_all_safe.columns), None)
        if ms_col:
            ms_stats = {}
            for state in ["Good", "Okay", "Bad"]:
                sub = df_all_safe[df_all_safe[ms_col].astype(str).str.strip() == state]
                if not sub.empty:
                    cnt = sub[sub["Outcome"].isin(["Win", "BE", "Loss"])]
                    ms_stats[state] = {
                        "trades": len(sub),
                        "win_rate": round(cnt["Outcome"].eq("Win").sum() / max(1, len(cnt)) * 100, 1)
                    }
            stats["mental_state"] = ms_stats

    # ── Asia overweight ───────────────────────────────────────────────────────
    if "by_session" in stats:
        total_sess = sum(s["trades"] for s in stats["by_session"])
        for s in stats["by_session"]:
            if s["session"] == "Asia":
                stats["asia_pct"] = round(s["trades"] / max(1, total_sess) * 100, 1)

    stats["flags"] = _flags
    return stats


def _build_ai_prompt(stats: dict) -> str:
    lines = [
        "You are analysing a trader's performance journal called Edge Analysis.",
        "Based solely on the stats below, identify what is generating profit, what is draining profit, and actionable refinements.",
        "",
        "STATS:",
    ]

    if "overall_trades" in stats:
        lines.append(f"- Overall: {stats['overall_trades']} trades, {stats['overall_win_rate']}% win rate, {stats['overall_net_rr']:+.2f}R net")

    if "by_session" in stats and stats["by_session"]:
        lines.append("\nSession breakdown:")
        for s in sorted(stats["by_session"], key=lambda x: -x["win_rate"]):
            lines.append(f"  • {s['session']}: {s['trades']} trades, {s['win_rate']}% WR, {s['net_rr']:+.2f}R net")

    if "by_instrument" in stats and stats["by_instrument"]:
        lines.append("\nInstrument breakdown:")
        for i in sorted(stats["by_instrument"], key=lambda x: -x["win_rate"]):
            lines.append(f"  • {i['instrument']}: {i['trades']} trades, {i['win_rate']}% WR, {i['net_rr']:+.2f}R net")

    if "by_entry_model" in stats and stats["by_entry_model"]:
        lines.append("\nEntry model breakdown:")
        for m in sorted(stats["by_entry_model"], key=lambda x: -x["win_rate"]):
            lines.append(f"  • {m['model']}: {m['trades']} trades, {m['win_rate']}% WR, {m['net_rr']:+.2f}R net")

    if "mental_state" in stats:
        lines.append("\nMental state win rates:")
        for state, d in stats["mental_state"].items():
            lines.append(f"  • {state}: {d['win_rate']}% WR ({d['trades']} trades)")

    if "bad_beat_count" in stats:
        lines.append(f"\nBad beats: {stats['bad_beat_count']} ({stats['bad_beat_pct']}% of trades)")

    if "early_close_net" in stats:
        lines.append(
            f"\nEarly close net impact: {stats['early_close_net']:+.2f}R "
            f"(saved {stats['early_close_be_saved']:+.2f}R on BE trades, "
            f"left {stats['early_close_win_left']:+.2f}R on win trades)"
        )

    if "asia_pct" in stats:
        lines.append(f"\nAsia session share: {stats['asia_pct']}% of all trades (alert threshold: 45%)")

    lines += [
        "",
        "INSTRUCTIONS:",
        "Respond with a JSON object with exactly three keys:",
        "  'working': array of 3–5 objects with keys 'title' (string, ≤8 words) and 'detail' (string, 1–2 sentences, specific to the numbers above)",
        "  'holding_back': array of 3–5 objects with keys 'title' and 'detail' (same format)",
        "  'refinements': array of 3–5 objects with keys 'title' and 'action' (concrete, specific, 1–2 sentences)",
        "Be data-specific. Reference actual numbers. No generic trading advice.",
        "Output valid JSON only — no markdown, no preamble.",
    ]
    return "\n".join(lines)


def _compute_refinements(stats: dict) -> dict:
    """Derive working / holding-back / refinement insights directly from the
    stats dict (no AI). Returns the same shape the renderer expects."""
    working, holding, refine = [], [], []
    MIN = 5

    wr  = stats.get("overall_win_rate")
    net = stats.get("overall_net_rr")
    n   = stats.get("overall_trades", 0)

    if net is not None and n:
        if net > 0:
            working.append({"title": f"System is net positive (+{net:.1f}R)",
                            "detail": f"Across {n} completed trades at a {wr:.0f}% win rate. The edge is real \u2014 protect it with consistent risk."})
        else:
            holding.append({"title": f"Net result is negative ({net:.1f}R)",
                            "detail": f"Over {n} trades at {wr:.0f}% win rate \u2014 the mix of win rate and average R isn't profitable yet."})

    def _bw(rows):
        elig = [r for r in (rows or []) if r.get("trades", 0) >= MIN]
        if not elig:
            return None, None
        return max(elig, key=lambda r: r["net_rr"]), min(elig, key=lambda r: r["net_rr"])

    b, w = _bw(stats.get("by_session"))
    if b and b["net_rr"] > 0:
        working.append({"title": f"{b['session']} is your strongest session",
                        "detail": f"{b['net_rr']:+.1f}R over {b['trades']} trades ({b['win_rate']:.0f}% win rate)."})
    if w and w is not b and w["net_rr"] < 0:
        holding.append({"title": f"{w['session']} session is bleeding R",
                        "detail": f"{w['net_rr']:+.1f}R over {w['trades']} trades ({w['win_rate']:.0f}% win rate)."})
        refine.append({"title": f"Tighten or cut {w['session']} trades",
                       "action": f"{w['session']} is net {w['net_rr']:+.1f}R. Either stop trading it or raise the bar there and re-measure."})

    b, w = _bw(stats.get("by_instrument"))
    if b and b["net_rr"] > 0:
        working.append({"title": f"{b['instrument']} is carrying the edge",
                        "detail": f"{b['net_rr']:+.1f}R over {b['trades']} trades ({b['win_rate']:.0f}% win rate)."})
    if w and w is not b and w["net_rr"] < 0:
        holding.append({"title": f"{w['instrument']} is a net drag",
                        "detail": f"{w['net_rr']:+.1f}R over {w['trades']} trades ({w['win_rate']:.0f}% win rate)."})
        refine.append({"title": f"Reconsider trading {w['instrument']}",
                       "action": f"{w['instrument']} costs you {w['net_rr']:+.1f}R. Drop it or trade only A+ setups there."})

    b, w = _bw(stats.get("by_entry_model"))
    if b and b["net_rr"] > 0:
        working.append({"title": f"'{b['model']}' is your best model",
                        "detail": f"{b['net_rr']:+.1f}R over {b['trades']} trades ({b['win_rate']:.0f}% win rate)."})
    if w and w is not b and w["net_rr"] < 0:
        holding.append({"title": f"'{w['model']}' underperforms",
                        "detail": f"{w['net_rr']:+.1f}R over {w['trades']} trades ({w['win_rate']:.0f}% win rate)."})
        refine.append({"title": "Lean into your best model",
                       "action": f"Shift size from '{w['model']}' ({w['net_rr']:+.1f}R) toward your higher-expectancy models."})

    asia = stats.get("asia_pct")
    if asia is not None and asia > ASIA_WARN_THRESHOLD:
        holding.append({"title": f"Asia is overweight ({asia:.0f}% of trades)",
                        "detail": f"Above the {ASIA_WARN_THRESHOLD:.0f}% threshold \u2014 typically a lower-quality session for this system."})
        refine.append({"title": "Rebalance toward London / NY",
                       "action": f"Asia is {asia:.0f}% of your trades. Cap it and redirect focus to your stronger sessions."})

    ms = stats.get("mental_state", {})
    if "Good" in ms:
        good_wr = ms["Good"]["win_rate"]
        for st_name in ("Okay", "Bad"):
            d = ms.get(st_name)
            if d and d["trades"] >= MIN and d["win_rate"] + 8 < good_wr:
                gap = good_wr - d["win_rate"]
                holding.append({"title": f"'{st_name}' mental state hurts you",
                                "detail": f"{d['win_rate']:.0f}% win rate vs {good_wr:.0f}% when Good \u2014 a {gap:.0f}-point drop."})
                refine.append({"title": f"Treat '{st_name}' as a no-trade signal",
                               "action": f"Win rate falls {gap:.0f} points in a '{st_name}' state. Step away when you're not sharp."})

    bbc = stats.get("bad_beat_count", 0); bbp = stats.get("bad_beat_pct")
    if bbc and bbp is not None and bbp >= 3:
        holding.append({"title": f"{bbc} bad beats ({bbp:.0f}% of trades)",
                        "detail": "Stopped out then price ran to TP \u2014 emotionally costly even when it's not your fault."})
        refine.append({"title": "Run the step-away protocol",
                       "action": "After a bad beat, close the platform until the next session to avoid revenge trades."})

    ecn = stats.get("early_close_net")
    if ecn is not None:
        if ecn >= 0:
            working.append({"title": f"Early-close management nets +{ecn:.1f}R",
                            "detail": "Your discretionary exits are adding R overall."})
        else:
            holding.append({"title": f"Early closing costs {ecn:.1f}R",
                            "detail": "You leave more on winners than you save on break-evens."})
            refine.append({"title": "Let winners run further",
                           "action": f"Early closes net {ecn:.1f}R. Hold toward structure before managing the trade."})

    if not working:
        working.append({"title": "Keep logging trades", "detail": "Not enough completed trades yet to surface a clear strength."})
    if not holding:
        holding.append({"title": "No major leaks detected", "detail": "Nothing stands out as dragging the system down right now."})
    if not refine:
        refine.append({"title": "Maintain consistency", "action": "Keep risk and process steady, and re-check as more data builds."})

    # Yes/no flags: one verdict per flag, phrased as the ACTION on the flag itself
    # ("don't trade with X" / "require X") — never via the mirror "· no" side.
    _NICE = {"Multi-entry": "double-confirmation (multi-entry) setups",
             "Opposing weak structure": "opposing weak structure",
             "Divergence": "divergence", "Sweep": "a sweep",
             "True break": "a confirmed true break",
             "OB/OS extreme": "an OB/OS extreme",
             "Prepared / clear bias": "a prepared, clear bias"}
    flags = stats.get("flags") or []
    pairs, cats = {}, []
    for r in flags:
        cat = str(r.get("Category", ""))
        if cat.endswith(" \u00b7 yes") or cat.endswith(" \u00b7 no"):
            label, side = cat.rsplit(" \u00b7 ", 1)
            pairs.setdefault(label, {})[side] = r
        else:
            cats.append(r)

    flag_sugs = []
    for label, sides in pairs.items():
        y, n_ = sides.get("yes"), sides.get("no")
        y_ok = y and y.get("Trades", 0) >= 8
        n_ok = n_ and n_.get("Trades", 0) >= 8
        if not (y_ok or n_ok):
            continue
        ya = y["Avg R"] if y else float("nan")
        na = n_["Avg R"] if n_ else float("nan")
        gap = (ya - na) if (y and n_) else float("nan")
        nice = _NICE.get(label, label.lower())
        if gap == gap and abs(gap) < 0.4:
            continue
        yes_better = (gap == gap and gap > 0) or (gap != gap and y_ok and ya >= 0.5)
        yes_worse = (gap == gap and gap < 0) or (gap != gap and y_ok and ya <= -0.35)
        if yes_worse and (y_ok or n_ok):
            evid = (f"{ya:+.2f}R over {y['Trades']} trades with it"
                    + (f" vs {na:+.2f}R over {n_['Trades']} without" if n_ else ""))
            flag_sugs.append((abs(gap) if gap == gap else abs(ya), "dont",
                              f"Don't trade with {nice}", evid))
        elif yes_better and (y_ok or n_ok):
            evid = (f"{ya:+.2f}R over {y['Trades']} trades when present"
                    + (f" vs {na:+.2f}R without" if n_ else ""))
            flag_sugs.append((abs(gap) if gap == gap else abs(ya), "do",
                              f"Trade {nice}", evid))
    flag_sugs.sort(key=lambda x: -x[0])
    for _, kind, title, evid in flag_sugs[:3]:
        if kind == "dont":
            holding.append({"title": title, "detail": evid})
            refine.append({"title": title,
                           "action": f"{evid}. Skip these for a month and re-measure."})
        else:
            working.append({"title": title, "detail": f"{evid}. Keep requiring it."})

    cats8 = [r for r in cats if r.get("Trades", 0) >= 8]
    for r in sorted([r for r in cats8 if r["Avg R"] >= 0.5], key=lambda r: -r["Avg R"])[:2]:
        working.append({"title": f"{r['Category']} is worth {r['Avg R']:+.2f}R per trade",
                        "detail": f"Across {r['Trades']} trades. Keep stacking this condition."})
    for r in sorted([r for r in cats8 if r["Avg R"] <= -0.35], key=lambda r: r["Avg R"])[:2]:
        holding.append({"title": f"{r['Category']} costs {r['Avg R']:+.2f}R per trade",
                        "detail": f"Across {r['Trades']} trades."})
        refine.append({"title": f"Filter out '{r['Category']}' trades",
                       "action": f"This condition runs {r['Avg R']:+.2f}R over {r['Trades']} trades. "
                                 "Skip these for a month and re-measure."})
    return {"working": working[:5], "holding_back": holding[:5], "refinements": refine[:5]}


def _refinements_tab(f_perf: pd.DataFrame, df_all_safe: pd.DataFrame, styler):
    st.markdown('<div class="section">', unsafe_allow_html=True)

    st.markdown("""
    <style>
    .ref-col-header {
        font-size: 13px;
        font-weight: 700;
        letter-spacing: 0.06em;
        text-transform: uppercase;
        margin-bottom: 14px;
        padding-bottom: 6px;
        border-bottom: 2px solid #4800ff;
        color: #4800ff;
    }
    .ref-card {
        background: #ffffff;
        border: 1px solid #e8e4f7;
        border-radius: 8px;
        padding: 14px 16px;
        margin-bottom: 10px;
    }
    .ref-card-title {
        font-size: 13px;
        font-weight: 700;
        color: #1a1a2e;
        margin-bottom: 4px;
    }
    .ref-card-body {
        font-size: 13px;
        color: #4b5563;
        line-height: 1.6;
    }
    .ref-working   { border-left: 4px solid #16a34a; }
    .ref-holding   { border-left: 4px solid #ef4444; }
    .ref-refine    { border-left: 4px solid #4800ff; }
    .ref-loading {
        background: #f0ebff;
        border-radius: 8px;
        padding: 20px;
        text-align: center;
        color: #4800ff;
        font-size: 14px;
    }
    </style>
    """, unsafe_allow_html=True)

    if f_perf is None or f_perf.empty:
        st.info("No trades for current filters.")
        st.markdown("</div>", unsafe_allow_html=True)
        return

    stats = _build_refinements_stats(f_perf, df_all_safe)
    result = _compute_refinements(stats)

    c_working, c_holding, c_refine = st.columns(3)

    with c_working:
        st.markdown('<div class="ref-col-header" style="color:#16a34a;border-color:#16a34a;">✓ What\'s Working</div>', unsafe_allow_html=True)
        for item in result.get("working", []):
            st.markdown(
                f'<div class="ref-card ref-working">'
                f'<div class="ref-card-title">{item.get("title","")}</div>'
                f'<div class="ref-card-body">{item.get("detail","")}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )

    with c_holding:
        st.markdown('<div class="ref-col-header" style="color:#ef4444;border-color:#ef4444;">⚠ Holding the System Back</div>', unsafe_allow_html=True)
        for item in result.get("holding_back", []):
            st.markdown(
                f'<div class="ref-card ref-holding">'
                f'<div class="ref-card-title">{item.get("title","")}</div>'
                f'<div class="ref-card-body">{item.get("detail","")}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )

    with c_refine:
        st.markdown('<div class="ref-col-header" style="color:#4800ff;border-color:#4800ff;">→ Potential Refinements</div>', unsafe_allow_html=True)
        for item in result.get("refinements", []):
            st.markdown(
                f'<div class="ref-card ref-refine">'
                f'<div class="ref-card-title">{item.get("title","")}</div>'
                f'<div class="ref-card-body">{item.get("action","")}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )

    st.markdown("<br>", unsafe_allow_html=True)
    if st.button("Re-run analysis", key="refinements_rerun"):
        st.rerun()

    st.markdown("</div>", unsafe_allow_html=True)




# ── Salty: Execution Quality tab (Deviation Score) ───────────────────────────
def _salty_execution_quality_tab(f: pd.DataFrame) -> None:
    """Show deviation score analysis — available in Salty schema only."""
    st.markdown('<div class="section">', unsafe_allow_html=True)
    st.markdown("### Execution Quality (Deviation Score)")
    st.caption("How far your actual entry deviated from your planned entry.")

    dev_col = "Deviation Score" if "Deviation Score" in f.columns else None
    if dev_col is None or f.empty:
        _unavailable("Deviation Score")
        st.markdown("</div>", unsafe_allow_html=True)
        return

    g = f.copy()
    g["__dev_str"] = g[dev_col].astype(str).str.strip()
    # Deviation scores: "1 = small deviation", "2 = moderate deviation", etc.
    g["__dev_num"] = g["__dev_str"].str.extract(r"^(\d)").astype(float)
    g = g[g["__dev_num"].notna()]

    if g.empty:
        st.info("No deviation score data recorded.")
        st.markdown("</div>", unsafe_allow_html=True)
        return

    rows = []
    labels = {1: "Small", 2: "Moderate", 3: "Large"}
    counted = g[g["Outcome"].isin(["Win", "BE", "Loss"])]
    for score in sorted(g["__dev_num"].unique()):
        sub = counted[counted["__dev_num"] == score]
        if sub.empty:
            continue
        r = outcome_rates_from(sub)
        net_rr, _ = _rr_stats(sub)
        rows.append(dict(
            Entry_Model=f"{int(score)} — {labels.get(int(score), str(int(score)))} deviation",
            Trades=len(sub),
            **{"Win %": r["win_rate"], "BE %": r["be_rate"], "Loss %": r["loss_rate"],
               "Net PnL (R)": net_rr}
        ))

    if rows:
        from edge_analysis.ui.components import render_entry_model_table as _ret
        _ret(pd.DataFrame(rows), title="Win Rate by Deviation Score")
        if rows[0]["Win %"] > rows[-1]["Win %"]:
            _insight_box(
                f"Lower deviation scores correlate with higher win rates — "
                f"<b>small deviation ({rows[0]['Win %']:.1f}% WR)</b> vs "
                f"<b>large deviation ({rows[-1]['Win %']:.1f}% WR)</b>. "
                f"Precise entries near your planned level give your system its best chance.", "good")
    else:
        st.info("Not enough data for deviation score analysis.")

    st.markdown("</div>", unsafe_allow_html=True)

# ── Salty early close (simplified — no Targeted RR) ──────────────────────────
def _early_close_tab_salty(df: pd.DataFrame, styler):
    """Simplified early close section for Salty schema (no Targeted RR column)."""
    st.markdown('<div class="section">', unsafe_allow_html=True)
    st.markdown("### Early Close Profitability")

    if df is None or df.empty:
        _unavailable("Early Close Analysis")
        st.markdown("</div>", unsafe_allow_html=True)
        return

    # Salty has "Hit Full TP" (mapped from "Did price hit full TP without you?")
    hit_col = next((c for c in ["Hit Full TP", "Did price hit full TP without you?"] if c in df.columns), None)
    rr_col = "Closed RR" if "Closed RR" in df.columns else None

    if hit_col is None or rr_col is None:
        _unavailable("Early Close Analysis (requires Hit Full TP + Closed RR)")
        st.markdown("</div>", unsafe_allow_html=True)
        return

    g = df.copy()
    g["__rr"] = pd.to_numeric(g[rr_col], errors="coerce")
    g = g[g["__rr"].notna()]

    if g.empty:
        st.info("No early close data with RR values.")
        st.markdown("</div>", unsafe_allow_html=True)
        return

    hit_yes = g[g[hit_col].astype(str).str.strip().str.upper().isin(["YES", "Y", "TRUE", "1"])]
    hit_no  = g[~g.index.isin(hit_yes.index)]

    n_hit   = len(hit_yes)
    n_nohit = len(hit_no)
    total   = len(g)

    m1, m2, m3 = st.columns(3)
    with m1:
        st.markdown(
            f"<div class='kpi'><div class='label'>Trades with Full TP Data</div>"
            f"<div class='value' style='color:#4800ff'>{total}</div></div>",
            unsafe_allow_html=True)
    with m2:
        pct = round(n_hit / max(1, total) * 100, 1)
        st.markdown(
            f"<div class='kpi'><div class='label'>Price Hit Full TP</div>"
            f"<div class='value' style='color:#4800ff'>{n_hit}</div>"
            f"<div class='muted'>{pct}% of trades</div></div>",
            unsafe_allow_html=True)
    with m3:
        avg_rr_hit = float(hit_yes["__rr"].mean()) if n_hit > 0 else 0.0
        avg_rr_no  = float(hit_no["__rr"].mean())  if n_nohit > 0 else 0.0
        st.markdown(
            f"<div class='kpi'><div class='label'>Avg RR — Hit TP vs Not</div>"
            f"<div class='value' style='color:#4800ff'>{avg_rr_hit:+.2f}R / {avg_rr_no:+.2f}R</div>"
            f"<div class='muted'>hit TP / did not hit TP</div></div>",
            unsafe_allow_html=True)

    if n_hit > 0:
        _insight_box(
            f"In <b>{n_hit}</b> of {total} trades, price continued to full TP after your exit. "
            f"Avg RR when TP was hit: <b>{avg_rr_hit:+.2f}R</b>. "
            f"Log 'Targeted RR' in your Notion template to unlock full early close analysis.", "warn")

    st.markdown("</div>", unsafe_allow_html=True)

def _targets_tab(df_raw: pd.DataFrame, styler) -> None:
    """Card 2 — Month by month: month cards or the stacked race, records, evidence strip."""
    if df_raw is None or df_raw.empty or "Date" not in df_raw.columns:
        return
    g = df_raw.copy()
    g["__dt"] = pd.to_datetime(g["Date"], errors="coerce")
    try:
        from edge_analysis.ui.plan_tabs import get_tz_offset
        if getattr(g["__dt"].dt, "tz", None) is not None:
            g["__dt"] = g["__dt"].dt.tz_localize(None)
        g["__dt"] = g["__dt"] + pd.Timedelta(hours=get_tz_offset(g))
    except Exception:
        pass
    g = g[g["__dt"].notna()]
    rr_col = next((c for c in ["Closed RR Num", "Closed RR", "RR", "Closed R"] if c in g.columns), None)
    if rr_col is None or g.empty:
        return
    g["__rr"] = pd.to_numeric(g[rr_col], errors="coerce")
    g = g[g["__rr"].notna()]
    if g.empty:
        return
    usd = pd.to_numeric(g.get("PnL"), errors="coerce") if "PnL" in g.columns else None
    has_usd = usd is not None and usd.notna().any()
    if has_usd:
        g["__usd"] = usd
        _cost = pd.Series(0.0, index=g.index)
        for _cc in ("Commission", "Swap"):
            if _cc in g.columns:
                _cost = _cost + pd.to_numeric(g[_cc], errors="coerce").fillna(0.0)
        g["__cost"] = _cost
    need_r = float(st.session_state.get("ea_m_tgt", 5.0))
    stop_r = float(st.session_state.get("ea_m_stop", -6.0))

    mg = g.set_index("__dt").sort_index()
    monthly = mg["__rr"].resample("MS").sum().to_frame("r")
    monthly["n"] = mg["__rr"].resample("MS").size()
    if has_usd:
        monthly["usd"] = mg["__usd"].resample("MS").sum()
        if "__cost" in mg.columns:
            monthly["cost"] = mg["__cost"].resample("MS").sum()
    monthly = monthly[monthly["n"] > 0].tail(12)
    if monthly.empty:
        return

    with st.container(border=True):
        st.markdown('<div class="ea-card-anchor"></div>', unsafe_allow_html=True)
        h1, h2 = st.columns([2.2, 1])
        with h1:
            st.markdown("<div style='font-size:21px;font-weight:800;color:#0f172a;"
                        "margin-top:4px;'>Month by month</div>", unsafe_allow_html=True)
        with h2:
            mview = st.radio("View", ["Months", "Stacked"], horizontal=True,
                             key="mbm_view", label_visibility="collapsed") or "Months"

        now_m = pd.Timestamp.now().to_period("M")
        _bal = float(st.session_state.get("ea_m_bal", 10000) or 0)
        # Renaming onto a name the frame already carries would leave TWO columns
        # of that name, and every lookup would then hand back a DataFrame.
        _gm = g.drop(columns=[c for c in ("PnL_from_RR", "__Date")
                              if c in g.columns and c not in ("__rr", "__dt")],
                     errors="ignore").rename(columns={"__rr": "PnL_from_RR",
                                                      "__dt": "__Date"})
        _rp_m = _risk_pct(_gm)
        _, _starts = _balance_track(_gm, _bal)

        def _mbm_head(r_val, row, per=None):
            """Monthly return, computed by the SAME helper the hero uses, so a
            card can never disagree with the headline above it."""
            if _bal > 0 and per is not None and "__Date" in _gm.columns:
                _p = _period_pct(_gm, _gm["__Date"].dt.to_period("M") == per, _bal)
                if _p is not None:
                    return f"{_p:+.2f}%"
            if _bal > 0:
                return f"{_as_pct(r_val, _rp_m):+.2f}%"
            return f"{r_val:+.1f}R"

        if mview == "Months":
            cards = []
            for dt_, row in monthly.tail(6).iterrows():
                r_ = float(row["r"]); c = "#16a34a" if r_ >= 0 else "#ef4444"
                live = dt_.to_period("M") == now_m
                badge = ("<span style='background:#e2f5e9;color:#14532d;font-size:11px;"
                         "font-weight:800;border-radius:999px;padding:3px 10px;margin-left:8px;'>"
                         "TARGET ✓</span>" if r_ >= need_r else "")
                usd_note = ""
                if has_usd and "usd" in monthly.columns and row.get("usd") == row.get("usd"):
                    u = float(row["usd"])
                    usd_note = f" · {'-' if u < 0 else ''}${abs(u):,.0f}"
                    _c = row.get("cost")
                    _net = u
                    if _pnl_is_net(g):
                        # P&L already net; show what the costs were, don't re-subtract
                        if _c == _c and abs(float(_c)) >= 0.5:
                            usd_note += f" net · ${abs(float(_c)):,.0f} of it costs"
                    elif _c == _c and abs(float(_c)) >= 0.5:
                        _net = u + float(_c)
                        usd_note += (f" gross · {'-' if _net < 0 else ''}${abs(_net):,.0f} "
                                     "after costs")
                    # the % headline above already states the return, on the
                    # month's opening balance — no second, differently-based copy
                cards.append(
                    f"<div style='flex:1;min-width:200px;max-width:290px;background:#fbfcfe;"
                    f"border:1px solid #eef0f4;border-left:5px solid {c};"
                    f"border-radius:0 12px 12px 0;padding:13px 16px;'>"
                    f"<div style='font-size:12px;font-weight:700;letter-spacing:0.08em;"
                    f"color:{'#4800ff' if live else '#94a3b8'};'>"
                    f"{dt_.strftime('%B').upper()}{badge}</div>"
                    f"<div style='font-size:28px;font-weight:800;color:{c};margin:2px 0;'>"
                    f"{_mbm_head(r_, row, dt_.to_period('M'))}</div>"
                    f"<div style='font-size:13px;color:#64748b;'>{r_:+.1f}R \u00b7 "
                    f"{int(row['n'])} trades{usd_note}{' · live' if live else ''}</div></div>")
            st.markdown("<div style='display:flex;gap:14px;flex-wrap:wrap;margin:8px 0 4px;'>"
                        + "".join(cards) + "</div>", unsafe_allow_html=True)
        else:
            daily = mg["__rr"].groupby(pd.Grouper(freq="D")).sum().dropna()
            periods = sorted(daily.index.to_period("M").unique())[-6:]
            lines, endpts = [], []
            for p_ in periods:
                m = daily[daily.index.to_period("M") == p_]
                if len(m) < 2:
                    continue
                cumv = m.cumsum()
                lab = p_.strftime("%B")
                cur_m = p_ == now_m
                for dtv, cv in cumv.items():
                    lines.append({"Day": int(dtv.day), "Cum": round(float(cv), 2),
                                  "Month": lab, "kind": "cur" if cur_m else "past"})
                fin = float(cumv.iloc[-1])
                endpts.append({"Day": int(cumv.index[-1].day), "Cum": round(fin, 2),
                               "Month": lab,
                               "col": "cur" if cur_m else ("up" if fin >= 0 else "down")})
            if lines:
                xsc = alt.Scale(domain=[1, 31])
                ally = [r["Cum"] for r in lines]
                ysc = alt.Scale(domain=[min(stop_r - 1.5, min(ally) - 1),
                                        max(need_r + 1.5, max(ally) + 1)])
                lays = []
                for yv, col in ((0.0, "#cbd5e1"), (need_r, "#16a34a"), (stop_r, "#ef4444")):
                    lays.append(alt.Chart(alt.Data(values=[{"y": yv}]))
                                .mark_rule(color=col, strokeDash=[5, 5] if yv else [2, 3],
                                           strokeWidth=2 if yv else 1.5)
                                .encode(y=alt.Y("y:Q", title=None)))
                base = alt.Chart(alt.Data(values=lines))
                past = base.transform_filter(alt.datum.kind == "past").mark_line(
                    color="#d5d9e2", strokeWidth=2).encode(
                    x=alt.X("Day:Q", title="Day of month", scale=xsc,
                            axis=alt.Axis(tickMinStep=1, grid=False, labelColor="#94a3b8",
                                          titleColor="#94a3b8")),
                    y=alt.Y("Cum:Q", title=None, scale=ysc), detail="Month:N",
                    tooltip=[alt.Tooltip("Month:N"), alt.Tooltip("Cum:Q", format="+.2f")])
                curl = base.transform_filter(alt.datum.kind == "cur").mark_line(
                    color="#4800ff", strokeWidth=3.5).encode(
                    x=alt.X("Day:Q", title=None, scale=xsc),
                    y=alt.Y("Cum:Q", title=None, scale=ysc), detail="Month:N",
                    tooltip=[alt.Tooltip("Month:N"), alt.Tooltip("Cum:Q", format="+.2f")])
                dots = (alt.Chart(alt.Data(values=endpts))
                        .mark_circle(size=90, stroke="#ffffff", strokeWidth=2)
                        .encode(x=alt.X("Day:Q", title=None, scale=xsc),
                                y=alt.Y("Cum:Q", title=None, scale=ysc),
                                color=alt.Color("col:N", legend=None,
                                                scale=alt.Scale(domain=["cur", "up", "down"],
                                                                range=["#4800ff", "#16a34a",
                                                                       "#ef4444"])),
                                tooltip=[alt.Tooltip("Month:N"),
                                         alt.Tooltip("Cum:Q", format="+.2f")]))
                labs = (alt.Chart(alt.Data(values=endpts))
                        .mark_text(align="left", dx=9, dy=-2, fontSize=11.5,
                                   fontWeight=700)
                        .encode(x=alt.X("Day:Q", title=None, scale=xsc),
                                y=alt.Y("Cum:Q", title=None, scale=ysc),
                                text="Month:N",
                                color=alt.Color("col:N", legend=None,
                                                scale=alt.Scale(domain=["cur", "up", "down"],
                                                                range=["#4800ff", "#16a34a",
                                                                       "#ef4444"]))))
                st.altair_chart(styler(alt.layer(*lays, past, curl, dots, labs)
                                       .properties(height=300)),
                                use_container_width=True)
            else:
                st.info("Not enough monthly history for the stacked view yet.")

        # records as one slim chip row
        weekly = mg["__rr"].resample("W-MON", label="left", closed="left").sum()
        wk_n = mg["__rr"].resample("W-MON", label="left", closed="left").size()
        weekly = weekly[wk_n > 0]
        rows = []
        if not weekly.empty:
            bw, ww = weekly.idxmax(), weekly.idxmin()
            rows.append(("BEST WEEK", f"{weekly.max():+.1f}R",
                         f"week of {bw.strftime('%d %b')}", "#16a34a"))
            rows.append(("WORST WEEK", f"{weekly.min():+.1f}R",
                         f"week of {ww.strftime('%d %b')}", "#ef4444"))
        bm, wm = monthly["r"].idxmax(), monthly["r"].idxmin()
        rows.append(("BEST MONTH", f"{monthly['r'].max():+.1f}R", bm.strftime("%b %Y"), "#16a34a"))
        rows.append(("WORST MONTH", f"{monthly['r'].min():+.1f}R", wm.strftime("%b %Y"), "#ef4444"))
        st.markdown(
            "<div style='font-size:11px;font-weight:700;letter-spacing:0.06em;color:#94a3b8;"
            "margin-top:14px;'>RECORDS</div>"
            "<div style='display:flex;gap:12px;flex-wrap:wrap;margin-top:8px;'>" + "".join(
                f"<div style='flex:1;min-width:150px;background:#f8f9fc;border-radius:12px;"
                f"padding:11px 14px;'>"
                f"<div style='font-size:10.5px;font-weight:600;letter-spacing:0.05em;"
                f"color:#94a3b8;'>{k}</div>"
                f"<div style='font-size:20px;font-weight:800;color:{c};'>{v}</div>"
                f"<div style='font-size:12px;color:#94a3b8;'>{sub}</div></div>"
                for k, v, sub, c in rows) + "</div>", unsafe_allow_html=True)

        # the ONE evidence strip on the tab
        exp_m = float(monthly["r"].mean())
        sd_m = float(monthly["r"].std()) if len(monthly) >= 3 else float(monthly["r"].abs().mean())
        rec_target = max(1.0, exp_m - 0.25 * (sd_m or 0.0))
        if need_r > rec_target + 0.5:
            st.markdown(
                "<div style='background:#fdf6e8;border-radius:10px;padding:12px 18px;"
                "border-left:5px solid #d97706;margin-top:14px;'>"
                f"<div style='font-size:14.5px;font-weight:800;color:#7c4a03;'>"
                f"Your data currently supports about {rec_target:+.1f}R a month — "
                f"the {need_r:.0f}R target is ambition, not evidence yet.</div>"
                "<div style='font-size:12.5px;color:#9a6b1f;margin-top:3px;'>"
                "The gap closes as your live expectancy grows.</div></div>",
                unsafe_allow_html=True)
        try:
            _pdf = _monthly_report_pdf(monthly, need_r, float(need_r), 1.0, rows)
            st.download_button("Download monthly report (PDF)", data=_pdf,
                               file_name="edge-analysis-monthly.pdf", mime="application/pdf")
        except Exception:
            pass


def _monthly_report_pdf(monthly, need_r, target_pct, risk_pct, records_rows) -> bytes:
    """One-page PDF: month-by-month track record + records. ASCII-safe."""
    from fpdf import FPDF
    pdf = FPDF()
    pdf.set_auto_page_break(True, margin=14)
    pdf.add_page()
    pdf.set_fill_color(72, 0, 255)
    pdf.rect(0, 0, 210, 22, "F")
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Helvetica", "B", 15)
    pdf.set_xy(10, 6)
    pdf.cell(0, 10, "EDGE ANALYSIS - Monthly Report", ln=1)
    pdf.set_text_color(20, 24, 38)
    pdf.set_xy(10, 28)
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 6, f"Generated {pd.Timestamp.now().strftime('%d %b %Y')} - "
                   f"target {target_pct:.0f}% at {risk_pct:.2f}% risk = {need_r:.0f}R per month", ln=1)
    pdf.ln(4)
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(0, 7, "Track record", ln=1)
    pdf.set_font("Helvetica", "B", 9)
    pdf.set_fill_color(238, 237, 254)
    for w, h_ in ((40, "Month"), (30, "Net R"), (35, "Net $"), (25, "Trades"), (35, "Target pace")):
        pdf.cell(w, 7, h_, border=1, fill=True)
    pdf.ln()
    pdf.set_font("Helvetica", "", 9)
    for ts, row in monthly.iterrows():
        hit = "YES" if row["r"] >= need_r else "-"
        usd = row.get("usd")
        usd_s = "-" if usd is None or usd != usd else f"${usd:,.0f}"
        pdf.cell(40, 7, ts.strftime("%b %Y"), border=1)
        pdf.cell(30, 7, f"{row['r']:+.1f}R", border=1)
        pdf.cell(35, 7, usd_s, border=1)
        pdf.cell(25, 7, str(int(row["n"])), border=1)
        pdf.cell(35, 7, hit, border=1)
        pdf.ln()
    pdf.ln(4)
    if records_rows:
        pdf.set_font("Helvetica", "B", 11)
        pdf.cell(0, 7, "Records", ln=1)
        pdf.set_font("Helvetica", "", 9)
        for lab, val, sub, _c in records_rows:
            pdf.cell(0, 6, f"{lab.title()}: {val}  ({sub})", ln=1)
    pdf.ln(3)
    pdf.set_font("Helvetica", "I", 8)
    pdf.set_text_color(120, 128, 145)
    pdf.cell(0, 5, "Generated by Edge Analysis from the connected MT5 journal. Not financial advice.", ln=1)
    out = pdf.output()
    return bytes(out)


# ─────────────────────────── 7-TAB LAYOUT ────────────────────────────────────
def _whoop_enabled() -> bool:
    """Recovery tab shows only when WHOOP creds are set AND, if a
    WHOOP_OWNER secret is configured, only for that owner (email or
    Notion user id). No owner secret => visible to any user (opt-in)."""
    try:
        import streamlit as _st
        if _st.session_state.get("ea_demo"):
            return False
        if not (_st.secrets.get("WHOOP_CLIENT_ID") and _st.secrets.get("WHOOP_CLIENT_SECRET")):
            return False
        owner = str(_st.secrets.get("WHOOP_OWNER") or "").strip().lower()
        if not owner:
            return True
        email = str(_st.session_state.get("ea_user_email") or "").strip().lower()
        uid = str(_st.session_state.get("ea_user_id") or "").strip().lower()
        return owner in (email, uid)
    except Exception:
        return False


def _gap(px: int = 26) -> None:
    """Light vertical spacing between related blocks (softer than st.divider)."""
    st.markdown(f"<div style='height:{px}px'></div>", unsafe_allow_html=True)


def _flip(key: str, chart_fn, table_fn) -> None:
    """One dataset, two lenses \u2014 tables lead unless the Settings default says charts."""
    default = 1 if st.session_state.get("ea_view_pref") == "Chart" else 0
    view = st.radio("View", ["Table", "Chart"], index=default, horizontal=True, key=key,
                    label_visibility="collapsed") or "Table"
    if view == "Table":
        table_fn()
    else:
        chart_fn()


def render_all_tabs(f: pd.DataFrame, df_all: pd.DataFrame, styler, show_table, hero_fn=None):
    from edge_analysis.ui.mt5_tabs import (
        _section_header, _mae_mfe_section, _close_style_section, _missed_runner_section,
        _direction_section, _conviction_section, _holdtime_section,
        _discipline_section, _mistake_section, _execution_section,
    )
    from edge_analysis.ui.pro_tabs import (
        _exit_optimizer, _mae_stop_optimizer, _tilt, _a_game,
        _heatmap_hour_day, _symbol_session_matrix, _cost_drag,
    )
    from edge_analysis.ui.plan_tabs import render_plan_tab, render_review_tab

    f_perf = _prep_perf_df(f)
    df_all_safe = df_all.copy() if df_all is not None else df_all

    _whoop_on = _whoop_enabled()
    _mt5 = _get_schema() == "mt5" or _df_is_mt5(df_all_safe)
    _salty = _is_salty()
    _data = f_perf if (f_perf is not None and not f_perf.empty) else df_all_safe

    # Speed: render ONLY the active tab. st.tabs runs all six server-side on
    # every rerun; this radio-nav (styled as the same pills) does one.
    _TABS = ["Performance", "Entry", "Externals", "Psychology", "Plan", "Review"]
    with st.container():
        st.markdown('<div class="ea-nav"></div>', unsafe_allow_html=True)
        _active = st.radio("View", _TABS, horizontal=True, key="ea_tab",
                           label_visibility="collapsed") or "Performance"

    # ── Performance ────────────────────────────────────────────────────────
    if _active == "Performance":
        # Money surfaces are a TRACK RECORD: one account, its plan, its balance.
        # Behaviour tabs keep the full executed view (challenge fills included).
        _f_track, _track_label, _track_others = _track_only(f_perf)
        if _track_label and _track_others:
            _short = _track_label.split("@")[0][:24]
            st.caption(f"Track record: {_short} \u00b7 {_track_others} other "
                       f"account{'s' if _track_others > 1 else ''} excluded here "
                       "\u2014 pick an account in Filters to switch")
        _month_card(_f_track, styler)
        _targets_tab(_track_only(df_all_safe)[0], styler)
        _alltime_card(_f_track, styler)
        if _more_detail_has_content(f_perf, df_all_safe):
            with st.container(border=True):
                st.markdown('<div class="ea-card-anchor"></div>', unsafe_allow_html=True)
                _card_header("More detail", "Early closes, assets and accounts \u2014 when there's something to compare.")
                with _budget(1):
                    _instruments_tab(f_perf, show_table)
                    if not _salty:
                        _account_comparison_tab(f_perf, styler)

        with st.container(border=True):
            st.markdown('<div class="ea-card-anchor"></div>', unsafe_allow_html=True)
            _card_header("Projections", "What this edge does over the months ahead if you keep showing up.")
            with _budget(1):
                _projections_tab(_track_only(df_all_safe)[0], styler)

    # ── Entry: three cards — setups, timing, managing ─────────────────────
    if _active == "Entry":
        with st.container(border=True):
            st.markdown('<div class="ea-card-anchor"></div>', unsafe_allow_html=True)
            _card_header("Setups", "Which entries earn and which cost \u2014 ranked from your own trades.")
            with _budget(1):
                _entry_models_tab(f_perf, show_table)
                _gap(18)
                _entry_criteria(f_perf)
                _gap(18)
                _confluences_tab(f_perf, show_table)
                _gap(18)
                _timeframes_tab(f_perf, show_table)
                if _mt5:
                    _gap(18)
                    _direction_section(_data, styler)
                    _gap(18)
                    _conviction_section(_data, styler)
                    _gap(18)
                    _a_game(_data, styler)

        with st.container(border=True):
            st.markdown('<div class="ea-card-anchor"></div>', unsafe_allow_html=True)
            _card_header("Timing", "When your edge shows up \u2014 hours, sessions and days.")
            with _budget(1):
                _hourly_expectancy_clock(df_all_safe)
                _gap(18)
                _sessions_tab(f_perf, show_table)
                _gap(18)
                _time_days_tab(f_perf, show_table)
                if _mt5:
                    _gap(18)
                    _holdtime_section(_data, styler)

        if _mt5 or _salty:
            with st.container(border=True):
                st.markdown('<div class="ea-card-anchor"></div>', unsafe_allow_html=True)
                _card_header("Managing the trade",
                             "What happens after entry \u2014 efficiency, exits, stops and what got away.")
                with _budget(1):
                    if _mt5:
                        _mae_mfe_section(_data, styler)
                        _gap(18)
                        _close_style_section(
                            _data if (_data is not None and "Targeted RR" in _data.columns)
                            else df_all_safe, styler)
                        _gap(18)
                        _execution_section(_data, styler)
                        _gap(18)
                        _exit_optimizer(_data, styler)
                        _gap(18)
                        _mae_stop_optimizer(_data, styler)
                        _gap(18)
                        _missed_runner_section(_data, styler)
                    if _salty:
                        _salty_execution_quality_tab(f_perf)

    # ── Externals: market conditions card + costs card ────────────────────
    if _active == "Externals":
        with st.container(border=True):
            st.markdown('<div class="ea-card-anchor"></div>', unsafe_allow_html=True)
            _card_header("Market conditions",
                         "The market around your trades \u2014 trend, volatility, news and gaps.")
            with _budget(1):
                _conditions_tab(f_perf, show_table)
                _gap(18)
                _obos_section(f_perf)
                _gap(18)
                _confluence_board(f_perf, scope="external")
                _gap(18)
                _liquidity_windows(f_perf)
                if _mt5:
                    _gap(18)
                    _heatmap_hour_day(_data, styler)
                    _gap(18)
                    _symbol_session_matrix(_data, styler)
        if _mt5:
            with st.container(border=True):
                st.markdown('<div class="ea-card-anchor"></div>', unsafe_allow_html=True)
                _card_header("Costs", "What fees and slippage quietly take from the edge.")
                with _budget(1):
                    _cost_drag(_data, styler)

    # ── Psychology: discipline card, losses card, WHOOP card ──────────────
    if _active == "Psychology":
        _journal_completeness_strip(df_all_safe)
        with st.container(border=True):
            st.markdown('<div class="ea-card-anchor"></div>', unsafe_allow_html=True)
            _card_header("Discipline", "One score, its trend, and the habits that build it.")
            with _budget(1):
                _psychology_tab(f_perf, df_all_safe, styler)

        with st.container(border=True):
            st.markdown('<div class="ea-card-anchor"></div>', unsafe_allow_html=True)
            _card_header("Where you lose", "Your own loss tags, the mistakes that repeat, and what a loss does to the next trade.")
            with _budget(1):
                _loss_postmortem(f_perf)
                if _mt5:
                    _gap(18)
                    _tilt(_data, styler)
                    _gap(18)
                    _mistake_section(_data, styler)
                _gap(18)
                _psych_session_alert(df_all_safe, styler)

        if _whoop_on:
            with st.container(border=True):
                st.markdown('<div class="ea-card-anchor"></div>', unsafe_allow_html=True)
                _card_header("Recovery (WHOOP)", "What your body says about your trading.")
                with _budget(1):
                    from edge_analysis.ui.whoop_tab import render_whoop_tab
                    render_whoop_tab(df_all_safe, styler)

    # ── Plan: breaker + plan card, refinements card, template card ─────────
    if _active == "Plan":
        with st.container(border=True):
            st.markdown('<div class="ea-card-anchor"></div>', unsafe_allow_html=True)
            _card_header("Trading plan", "The rules, ranked by what they're worth \u2014 and the breaker that guards the month.")
            with _budget(1):
                _breaker_strip(_track_only(df_all_safe)[0])
                render_plan_tab(df_all_safe, styler)

        with st.container(border=True):
            st.markdown('<div class="ea-card-anchor"></div>', unsafe_allow_html=True)
            _card_header("Refinements", "Data-backed tweaks worth testing next.")
            with _budget(1):
                _refinements_tab(f_perf, df_all_safe, styler)

        with st.container(border=True):
            st.markdown('<div class="ea-card-anchor"></div>', unsafe_allow_html=True)
            _card_header("My template", "Your connected journal and what it unlocks.")
            with _budget(1):
                _powered_on_panel(df_all_safe)
                _gap(18)
                _data_tab(df_all_safe, show_table)

    # ── Review: one weekly card ────────────────────────────────────────────
    if _active == "Review":
        # The review question is "what do I work on?" — so the answer leads.
        _digest_card(f_perf)
        with st.container(border=True):
            st.markdown('<div class="ea-card-anchor"></div>', unsafe_allow_html=True)
            _card_header("Weekly debrief", "Process over P&L \u2014 did you trade your system this week? Money lives on Performance.")
            with _budget(2):
                render_review_tab(df_all_safe, styler)
