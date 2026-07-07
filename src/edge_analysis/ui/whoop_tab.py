"""Recovery tab — WHOOP physiology trends and their correlation to trade edge."""
from __future__ import annotations

import pandas as pd
import streamlit as st

try:
    import altair as alt
except Exception:  # pragma: no cover
    alt = None

from edge_analysis.ui.mt5_tabs import _tiles, _line_metric, _section_header
from edge_analysis.data import whoop


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _r_and_win(df: pd.DataFrame) -> pd.DataFrame:
    """Return trades with numeric R (`R`) and a boolean `is_win`, plus `tdate`."""
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
    """Aggregate joined trades by their assigned band into _tiles/_line rows."""
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
    if v < 34:
        return "Red (<34%)"
    if v < 67:
        return "Yellow (34–66%)"
    return "Green (67%+)"


def _band_sleep(v):
    if pd.isna(v):
        return None
    if v < 70:
        return "Under 70%"
    if v < 85:
        return "70–84%"
    return "85%+"


def _band_strain(v):
    if pd.isna(v):
        return None
    if v < 10:
        return "Low (<10)"
    if v < 15:
        return "Moderate (10–15)"
    return "High (15+)"


def _summary_tiles(daily: pd.DataFrame) -> None:
    """Latest + average physiology tiles across the window."""
    def _fmt(v, suffix="", dec=0):
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return "—"
        return f"{v:.{dec}f}{suffix}"

    latest = daily.dropna(subset=["recovery"]).tail(1)
    latest_rec = float(latest["recovery"].iloc[0]) if not latest.empty else None
    avg_rec = daily["recovery"].mean()
    avg_sleep = daily["sleep_hours"].mean()
    avg_strain = daily["day_strain"].mean()

    tiles = [
        ("Latest recovery", _fmt(latest_rec, "%"),
         "#16a34a" if (latest_rec or 0) >= 67 else "#f59e0b" if (latest_rec or 0) >= 34 else "#ef4444"),
        ("Avg recovery", _fmt(avg_rec, "%"), "#4800ff"),
        ("Avg sleep", _fmt(avg_sleep, "h", 1), "#4800ff"),
        ("Avg day strain", _fmt(avg_strain, "", 1), "#4800ff"),
    ]
    cols = st.columns(len(tiles))
    for col, (label, val, color) in zip(cols, tiles):
        with col:
            st.markdown(
                f"<div style='background:#fff;border:1px solid rgba(0,0,0,0.06);"
                f"border-radius:12px;padding:14px 16px;box-shadow:0 2px 10px rgba(0,0,0,0.04);'>"
                f"<div style='font-size:13px;color:#64748b;font-weight:600;'>{label}</div>"
                f"<div style='font-size:32px;font-weight:800;color:{color};margin-top:4px;'>{val}</div>"
                f"</div>", unsafe_allow_html=True)


def _recovery_trend(daily: pd.DataFrame, styler) -> None:
    """Recovery-over-time line, coloured by band, styler-wrapped for dark mode."""
    if alt is None:
        return
    d = daily.dropna(subset=["recovery"]).copy()
    if d.empty:
        return
    d["date_s"] = d["date"].dt.strftime("%Y-%m-%d")
    vals = d[["date_s", "recovery"]].to_dict("records")
    base = alt.Chart(alt.Data(values=vals))
    line = base.mark_line(color="#4800ff", strokeWidth=2, interpolate="monotone").encode(
        x=alt.X("date_s:T", title="", axis=alt.Axis(labelColor="#94a3b8")),
        y=alt.Y("recovery:Q", title="Recovery %", scale=alt.Scale(domain=[0, 100]),
                axis=alt.Axis(labelColor="#94a3b8", titleColor="#94a3b8",
                              grid=True, gridColor="#eef0f5")))
    band = (alt.Chart(alt.Data(values=[{"y": 67}, {"y": 34}]))
            .mark_rule(color="#cbd5e1", strokeDash=[4, 4]).encode(y="y:Q"))
    st.altair_chart(styler(alt.layer(band, line).properties(height=260)),
                    use_container_width=True)


# --------------------------------------------------------------------------- #
# main entry
# --------------------------------------------------------------------------- #
def render_whoop_tab(df_all: pd.DataFrame, styler) -> None:
    token = st.session_state.get("whoop_at")

    # --- not connected -----------------------------------------------------
    if not token:
        _section_header("Connect WHOOP")
        st.markdown(
            "Link your WHOOP account to see whether your recovery, sleep and "
            "strain line up with your trading edge — e.g. *your average R on "
            "green-recovery days vs red days.*")
        url = st.session_state.get("whoop_auth_url")
        if url:
            st.link_button("Connect WHOOP", url, type="primary")
        else:
            st.info("WHOOP credentials aren't configured yet. Add `WHOOP_CLIENT_ID`, "
                    "`WHOOP_CLIENT_SECRET` and `WHOOP_REDIRECT_URI` to the app secrets.")
        return

    # --- connected ---------------------------------------------------------
    top = st.columns([1, 1, 1, 1, 1])
    with top[-1]:
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
        msg = str(e)
        if "401" in msg:
            st.warning("WHOOP session expired. Click Disconnect and reconnect.")
        else:
            st.error(f"Couldn't load WHOOP data: {e}")
        return

    if daily is None or daily.empty:
        st.info("No WHOOP data returned for your trading date range yet.")
        return

    _summary_tiles(daily)
    st.divider()
    _section_header("Recovery over time")
    _recovery_trend(daily, styler)
    st.divider()

    # ---- correlation to trade results ------------------------------------
    trades = _r_and_win(df_all)
    merged = trades.merge(daily, left_on="tdate", right_on="date", how="inner")

    if merged.empty or merged["R"].dropna().empty:
        st.info("Not enough overlapping days between your trades and WHOOP data "
                "yet to show correlations.")
        st.caption("Trades are matched to WHOOP days by UTC calendar date.")
        return

    _section_header("Does recovery predict your edge?")
    st.caption("Every trade matched to that day's WHOOP recovery, by UTC date.")
    m = merged.copy()
    m["__band"] = m["recovery"].apply(_band_recovery)
    rec_rows = _agg_bands(m, ["Red (<34%)", "Yellow (34–66%)", "Green (67%+)"])
    if not rec_rows.empty:
        _tiles(rec_rows, styler)
    else:
        st.info("No scored recovery days overlap your trades yet.")

    st.divider()
    _section_header("Sleep vs edge")
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
