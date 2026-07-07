"""Recovery tab — how your WHOOP stats affect your trading.

No raw physiology dashboards (you have those in the WHOOP app); this tab only
shows the impact of each WHOOP signal on your trade results.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from edge_analysis.ui.mt5_tabs import _tiles, _line_metric, _section_header
from edge_analysis.data import whoop
from edge_analysis.data.whoop import DRIVER_METRICS, METRIC_LABELS


# --------------------------------------------------------------------------- #
# trade prep + joins
# --------------------------------------------------------------------------- #
def _r_and_win(df: pd.DataFrame) -> pd.DataFrame:
    """Trades with numeric R (`R`), boolean `is_win`, and tz-naive `tdate`."""
    out = df.copy()
    out["R"] = pd.to_numeric(out.get("Closed RR"), errors="coerce")
    oc = out.get("Outcome Canonical")
    if oc is None:
        oc = out.get("Outcome")
    out["is_win"] = (oc.astype(str).str.lower() == "win") if oc is not None else False
    if "Date" in out.columns:
        _d = pd.to_datetime(out["Date"], errors="coerce")
        if getattr(_d.dt, "tz", None) is not None:
            _d = _d.dt.tz_convert("UTC").dt.tz_localize(None)
        out["tdate"] = _d.dt.normalize()
    else:
        out["tdate"] = pd.NaT
    return out.dropna(subset=["tdate"])


def _agg_bands(merged: pd.DataFrame, order: list) -> pd.DataFrame:
    g = merged.dropna(subset=["__band", "R"])
    rows = []
    for cat in order:
        sub = g[g["__band"] == cat]
        if sub.empty:
            continue
        rows.append({
            "Category": cat,
            "Trades": int(len(sub)),
            "Avg R": float(sub["R"].mean()),
            "Win %": float(100.0 * sub["is_win"].mean()),
            "Net R": float(sub["R"].sum()),
        })
    return pd.DataFrame(rows)


def _band_recovery(v):
    if pd.isna(v):
        return None
    return "Red (<34%)" if v < 34 else "Yellow (34–66%)" if v < 67 else "Green (67%+)"


def _band_sleep(v):
    if pd.isna(v):
        return None
    return "Under 70%" if v < 70 else "70–84%" if v < 85 else "85%+"


def _band_strain(v):
    if pd.isna(v):
        return None
    return "Low (<10)" if v < 10 else "Moderate (10–15)" if v < 15 else "High (15+)"


# --------------------------------------------------------------------------- #
# edge-driver leaderboard: every metric ranked by its effect on R
# --------------------------------------------------------------------------- #
def _edge_drivers(merged: pd.DataFrame, min_trades: int = 8) -> pd.DataFrame:
    """For each WHOOP metric, the avg-R gap between the trader's high-metric and
    low-metric days (median split), ranked by magnitude. Positive = higher is
    better; negative = higher hurts."""
    r = pd.to_numeric(merged.get("R"), errors="coerce")
    rows = []
    for m in DRIVER_METRICS:
        if m not in merged.columns:
            continue
        sub = pd.DataFrame({"v": pd.to_numeric(merged[m], errors="coerce"), "r": r}).dropna()
        if len(sub) < min_trades or sub["v"].nunique() < 2:
            continue
        med = sub["v"].median()
        lo = sub[sub["v"] <= med]["r"]
        hi = sub[sub["v"] > med]["r"]
        if len(lo) < 3 or len(hi) < 3:
            continue
        corr = sub["v"].corr(sub["r"])
        rows.append({
            "Metric": METRIC_LABELS.get(m, m),
            "gap": float(hi.mean() - lo.mean()),
            "Win %": float(100.0 * (sub["r"] > 0).mean()),
            "Trades": int(len(sub)),
            "r": round(float(corr), 2) if pd.notna(corr) else 0.0,
        })
    d = pd.DataFrame(rows)
    if not d.empty:
        d = d.reindex(d["gap"].abs().sort_values(ascending=False).index).reset_index(drop=True)
    return d


# --------------------------------------------------------------------------- #
# main entry
# --------------------------------------------------------------------------- #
def render_whoop_tab(df_all: pd.DataFrame, styler) -> None:
    token = st.session_state.get("whoop_at")

    if not token:
        if st.session_state.get("whoop_boot") == "pending":
            _section_header("WHOOP")
            st.caption("Restoring your WHOOP connection…")
            return
        _section_header("Connect WHOOP")
        st.markdown(
            "Link WHOOP to see how your recovery, sleep and strain affect your "
            "trading — which physiological signals go with your best and worst R.")
        url = st.session_state.get("whoop_auth_url")
        if url:
            st.link_button("Connect WHOOP", url, type="primary")
        else:
            st.info("WHOOP credentials aren't configured yet. Add `WHOOP_CLIENT_ID`, "
                    "`WHOOP_CLIENT_SECRET` and `WHOOP_REDIRECT_URI` to the app secrets.")
        return

    cols = st.columns([4, 1])
    with cols[1]:
        if st.button("Disconnect", key="whoop_disc"):
            st.session_state["whoop_logout"] = True
            st.rerun()

    if df_all is None or df_all.empty or "Date" not in df_all.columns:
        st.info("No dated trades yet — connect a journal to see correlations.")
        return

    dates = pd.to_datetime(df_all["Date"], errors="coerce").dropna()
    if dates.empty:
        st.info("No dated trades yet.")
        return
    _mn = dates.min()
    _mn = _mn.tz_localize("UTC") if _mn.tzinfo is None else _mn.tz_convert("UTC")
    start_iso = _mn.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    end_iso = pd.Timestamp.utcnow().tz_localize(None).strftime("%Y-%m-%dT%H:%M:%S.000Z")

    try:
        daily = whoop.cached_daily_df(token, start_iso, end_iso)
    except Exception as e:
        if "401" in str(e):
            st.warning("WHOOP session expired. Click Disconnect and reconnect.")
        else:
            st.error(f"Couldn't load WHOOP data: {e}")
        return

    if daily is None or daily.empty:
        st.info("No WHOOP data returned for your trading date range yet.")
        return

    trades = _r_and_win(df_all)
    merged = trades.merge(daily, left_on="tdate", right_on="date", how="inner")
    if merged.empty or merged["R"].dropna().empty:
        st.info("Not enough overlapping days between your trades and WHOOP data yet.")
        st.caption("Trades are matched to WHOOP days by UTC calendar date.")
        return

    st.caption(f"{len(merged)} trades across "
               f"{merged['tdate'].nunique()} WHOOP-tracked days · matched by UTC date.")

    # ---- headline: what moves your edge --------------------------------------
    _section_header("What moves your edge")
    st.markdown("Avg-R gap between your **high** and **low** days for each WHOOP "
                "stat (median split). Green = higher helps · red = higher hurts.")
    drivers = _edge_drivers(merged)
    if drivers.empty:
        st.info("Not enough overlapping data yet to rank drivers — this fills in "
                "as more trades line up with WHOOP days.")
    else:
        try:
            from edge_analysis.ui.tabs import _rank_dots
            _rank_dots(drivers.head(12), "Metric", "gap", suffix="R")
        except Exception:
            show = drivers.head(12).copy()
            show["Avg-R gap"] = show["gap"].map(lambda x: f"{x:+.2f}R")
            st.dataframe(show[["Metric", "Avg-R gap", "r", "Trades"]],
                         hide_index=True, use_container_width=True)

    st.divider()
    # ---- drill-downs on the three headline signals ---------------------------
    _section_header("Recovery band vs edge")
    m = merged.copy()
    m["__band"] = m["recovery"].apply(_band_recovery)
    rec_rows = _agg_bands(m, ["Red (<34%)", "Yellow (34–66%)", "Green (67%+)"])
    if not rec_rows.empty:
        _tiles(rec_rows, styler)
    else:
        st.caption("No scored recovery days overlap your trades yet.")

    st.divider()
    _section_header("Sleep performance vs edge")
    m["__band"] = m["sleep_perf"].apply(_band_sleep)
    sleep_rows = _agg_bands(m, ["Under 70%", "70–84%", "85%+"])
    if not sleep_rows.empty:
        _line_metric(sleep_rows, "", styler, value="Avg R",
                     x_order=["Under 70%", "70–84%", "85%+"],
                     x_title="Sleep performance", baseline=0.0)
    else:
        st.caption("No sleep-scored days overlap your trades yet.")

    st.divider()
    _section_header("Day strain vs edge")
    m["__band"] = m["day_strain"].apply(_band_strain)
    strain_rows = _agg_bands(m, ["Low (<10)", "Moderate (10–15)", "High (15+)"])
    if not strain_rows.empty:
        _line_metric(strain_rows, "", styler, value="Avg R",
                     x_order=["Low (<10)", "Moderate (10–15)", "High (15+)"],
                     x_title="Day strain", baseline=0.0)
    else:
        st.caption("No strain-scored days overlap your trades yet.")
