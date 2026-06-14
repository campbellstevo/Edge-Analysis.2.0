"""
MT5-only analytics (Phase 2).

These sections light up when the MT5 Trade Log template is connected, taking
advantage of the richer auto-imported data (exact R, MAE/MFE, dollar P&L,
precise timestamps, execution metrics). They degrade gracefully (showing an
"unavailable" note) for the SR / Salty templates that lack these columns.

Helpers from tabs.py (_insight_box, _to_alt_values, _unavailable) are imported
lazily to avoid a circular import.
"""
from __future__ import annotations
import numpy as np
import pandas as pd
import altair as alt
import streamlit as st

PURPLE = "#4800ff"


def _t():
    from edge_analysis.ui import tabs as _tabs
    return _tabs


def _num(df: pd.DataFrame, col: str):
    """Numeric Series for col, or None if the column is absent / all-empty."""
    if col not in df.columns:
        return None
    s = pd.to_numeric(df[col], errors="coerce")
    return s if s.notna().any() else None


def _kpi(label: str, value, sub: str, color: str = PURPLE) -> None:
    st.markdown(
        f"<div class='kpi'><div class='label'>{label}</div>"
        f"<div class='value' style='color:{color}'>{value}</div>"
        f"<div class='muted'>{sub}</div></div>",
        unsafe_allow_html=True,
    )


def _outcome(g: pd.DataFrame, rr_col: str = "__rr") -> pd.Series:
    if "Outcome" in g.columns:
        return g["Outcome"]
    return np.where(g[rr_col] > 0, "Win", np.where(g[rr_col] < 0, "Loss", "BE"))


# ── 1. MAE / MFE efficiency ───────────────────────────────────────────────────
def _mae_mfe_section(df: pd.DataFrame, styler) -> None:
    t = _t()
    st.markdown("### Trade Efficiency — MAE / MFE")
    st.caption(
        "MFE = how far a trade ran in your favour before closing (in R). "
        "MAE = how far it dipped against you first. "
        "Capture = how much of the favourable move you actually banked."
    )
    mfe = _num(df, "MFE (R)"); rr = _num(df, "Closed RR"); mae = _num(df, "MAE (R)")
    if mfe is None or rr is None:
        t._unavailable("Trade Efficiency (MAE/MFE)"); return

    g = df.copy()
    g["__mfe"] = mfe.values
    g["__rr"] = rr.values
    g["__mae"] = mae.values if mae is not None else np.nan
    g = g[pd.notna(g["__mfe"]) & pd.notna(g["__rr"])]
    if g.empty:
        t._unavailable("Trade Efficiency (MAE/MFE)"); return

    wins = g[g["__rr"] > 0]
    capwins = wins[wins["__mfe"] > 0]
    cap_eff = float((capwins["__rr"] / capwins["__mfe"]).clip(0, 1).mean() * 100) if not capwins.empty else float("nan")
    avg_mfe = float(g["__mfe"].mean())
    avg_mae = float(g["__mae"].mean()) if pd.notna(g["__mae"]).any() else float("nan")
    avg_giveback = float((capwins["__mfe"] - capwins["__rr"]).clip(lower=0).mean()) if not capwins.empty else float("nan")

    c1, c2, c3, c4 = st.columns(4)
    with c1: _kpi("Avg MFE (favour)", f"{avg_mfe:.2f}R", "avg peak in your favour")
    with c2: _kpi("Avg MAE (heat)", "—" if np.isnan(avg_mae) else f"{avg_mae:.2f}R", "avg dip before close")
    with c3: _kpi("Capture efficiency", "—" if np.isnan(cap_eff) else f"{cap_eff:.0f}%", "of favour banked on wins")
    with c4: _kpi("Avg give-back", "—" if np.isnan(avg_giveback) else f"{avg_giveback:.2f}R", "left on table per win")

    plot = g.copy()
    plot["OutcomeC"] = _outcome(plot)
    plot = plot.rename(columns={"__mfe": "MFE_R", "__rr": "Captured_R"})
    vals = t._to_alt_values(plot[["MFE_R", "Captured_R", "OutcomeC"]])
    if vals:
        hi = float(max(1.0, plot["MFE_R"].max()))
        scatter = (
            alt.Chart(alt.Data(values=vals)).mark_circle(size=60, opacity=0.55)
            .encode(
                x=alt.X("MFE_R:Q", title="MFE — favourable move available (R)"),
                y=alt.Y("Captured_R:Q", title="Captured (R)"),
                color=alt.Color("OutcomeC:N", title=None,
                                scale=alt.Scale(domain=["Win", "BE", "Loss"],
                                                range=["#16a34a", "#9ca3af", "#ef4444"])),
                tooltip=[alt.Tooltip("MFE_R:Q", title="MFE", format=".2f"),
                         alt.Tooltip("Captured_R:Q", title="Captured", format=".2f"),
                         alt.Tooltip("OutcomeC:N", title="Outcome")],
            )
        )
        diag = (alt.Chart(alt.Data(values=[{"x": 0, "y": 0}, {"x": hi, "y": hi}]))
                .mark_line(strokeDash=[4, 4], color=PURPLE).encode(x="x:Q", y="y:Q"))
        st.altair_chart(styler(alt.layer(scatter, diag).properties(height=320)), use_container_width=True)
        st.caption("Dashed line = captured the full favourable move. Points well below it = exited early.")

    if not np.isnan(cap_eff):
        if cap_eff < 60:
            t._insight_box(
                f"You're banking only <b>{cap_eff:.0f}%</b> of the favourable move on winners "
                f"(avg give-back <b>{avg_giveback:.1f}R</b> per win). Consider letting winners run "
                f"closer to structure before managing.", "warn")
        else:
            t._insight_box(f"Strong capture — banking <b>{cap_eff:.0f}%</b> of the favourable move on winners.", "good")


# ── 2. Dollar P&L ─────────────────────────────────────────────────────────────
def _dollar_pnl_section(df: pd.DataFrame, styler) -> None:
    t = _t()
    st.markdown("### Dollar P&L")
    st.caption("Real account P&L in dollars, straight from MT5 — alongside the R-based view.")
    pnl = _num(df, "PnL")
    if pnl is None:
        t._unavailable("Dollar P&L"); return
    g = df.copy(); g["__pnl"] = pnl.values
    g = g[pd.notna(g["__pnl"])]
    if g.empty:
        t._unavailable("Dollar P&L"); return

    net = float(g["__pnl"].sum())
    avg = float(g["__pnl"].mean())
    wins = g[g["__pnl"] > 0]; losses = g[g["__pnl"] < 0]
    pf = float(wins["__pnl"].sum() / abs(losses["__pnl"].sum())) if not losses.empty and losses["__pnl"].sum() != 0 else float("nan")
    comm = _num(df, "Commission"); swap = _num(df, "Swap")
    costs = 0.0
    if comm is not None: costs += float(pd.to_numeric(g.get("Commission"), errors="coerce").fillna(0).sum())
    if swap is not None: costs += float(pd.to_numeric(g.get("Swap"), errors="coerce").fillna(0).sum())

    c1, c2, c3, c4 = st.columns(4)
    with c1: _kpi("Net P&L", f"${net:,.0f}", f"over {len(g)} trades", "#16a34a" if net >= 0 else "#ef4444")
    with c2: _kpi("Avg / trade", f"${avg:,.1f}", "mean dollar result")
    with c3: _kpi("Profit factor", "—" if np.isnan(pf) else f"{pf:.2f}", "gross win $ / gross loss $")
    with c4: _kpi("Costs", f"${costs:,.0f}", "commission + swap")

    if "Date" in g.columns:
        gg = g.copy()
        gg["__d"] = pd.to_datetime(gg["Date"], errors="coerce")
        gg = gg[gg["__d"].notna()].sort_values("__d")
        if not gg.empty:
            gg["cum"] = gg["__pnl"].cumsum()
            vals = t._to_alt_values(gg[["__d", "cum"]].rename(columns={"__d": "Date", "cum": "CumUSD"}))
            if vals:
                area = (alt.Chart(alt.Data(values=vals)).mark_area(opacity=0.12, color=PURPLE)
                        .encode(x=alt.X("Date:T", title=None), y=alt.Y("CumUSD:Q", title="Cumulative $")))
                line = (alt.Chart(alt.Data(values=vals)).mark_line(strokeWidth=2, color=PURPLE)
                        .encode(x="Date:T", y="CumUSD:Q"))
                st.altair_chart(styler(alt.layer(area, line).properties(height=300)), use_container_width=True)

    t._insight_box(
        f"Net <b>${net:,.0f}</b> across {len(g)} trades (avg <b>${avg:,.1f}</b>/trade). "
        + ("Profit factor <b>{:.2f}</b>.".format(pf) if not np.isnan(pf) else ""),
        "good" if net >= 0 else "bad")


# ── 3. Timing & duration ──────────────────────────────────────────────────────
def _winrate_table(g: pd.DataFrame, by: str):
    rows = []
    for key, grp in g.groupby(by):
        cnt = grp[grp["__oc"].isin(["Win", "BE", "Loss"])]
        n = len(cnt)
        if n == 0:
            continue
        wr = cnt["__oc"].eq("Win").sum() / n * 100.0
        avg_r = pd.to_numeric(grp["__rr"], errors="coerce").mean()
        rows.append({by: key, "Trades": len(grp), "Win %": round(wr, 1),
                     "Avg R": round(float(avg_r), 2) if pd.notna(avg_r) else 0.0})
    return pd.DataFrame(rows)


def _timing_section(df: pd.DataFrame, styler) -> None:
    t = _t()
    st.markdown("### Timing & Duration")
    st.caption("Win rate and average R by hour of day and by how long trades were held — from MT5 timestamps.")
    rr = _num(df, "Closed RR")
    if rr is None:
        t._unavailable("Timing & Duration"); return
    g = df.copy()
    g["__rr"] = rr.values
    g["__oc"] = _outcome(g)

    hour = _num(df, "Hour (Melb)")
    if hour is not None:
        g["__hr"] = hour.values
    elif "Date" in g.columns:
        g["__hr"] = pd.to_datetime(g["Date"], errors="coerce").dt.hour
    else:
        g["__hr"] = np.nan

    gh = g[pd.notna(g["__hr"])].copy()
    if not gh.empty:
        gh["__hr"] = gh["__hr"].astype(int)
        tbl = _winrate_table(gh, "__hr").rename(columns={"__hr": "Hour"}).sort_values("Hour")
        if not tbl.empty:
            vals = t._to_alt_values(tbl)
            bar = (alt.Chart(alt.Data(values=vals)).mark_bar(color=PURPLE, opacity=0.85)
                   .encode(x=alt.X("Hour:O", title="Hour of day"),
                           y=alt.Y("Win %:Q", title="Win %"),
                           tooltip=["Hour:O", "Trades:Q", "Win %:Q", "Avg R:Q"])
                   .properties(height=240))
            st.markdown("**By hour of day**")
            st.altair_chart(styler(bar), use_container_width=True)
            best = tbl.loc[tbl["Win %"].idxmax()]; worst = tbl.loc[tbl["Win %"].idxmin()]
            t._insight_box(
                f"Best hour: <b>{int(best['Hour']):02d}:00</b> ({best['Win %']:.0f}% over {int(best['Trades'])} trades). "
                f"Weakest: <b>{int(worst['Hour']):02d}:00</b> ({worst['Win %']:.0f}%).")

    dur_col = "Trade Duration" if "Trade Duration" in g.columns else ("Duration" if "Duration" in g.columns else None)
    if dur_col:
        gd = g[g[dur_col].astype(str).str.strip().ne("") & g[dur_col].notna()].copy()
        if not gd.empty:
            order = ["0-30m", "30m-1h", "1h-2h", "2h-3h", "3h-4h", "4h-5h", "5h-6h", "6h-7h", "7h-8h", "8h+"]
            tbl = _winrate_table(gd, dur_col).rename(columns={dur_col: "Duration"})
            tbl["__o"] = tbl["Duration"].map(lambda v: order.index(v) if v in order else 99)
            tbl = tbl.sort_values("__o").drop(columns="__o")
            if not tbl.empty:
                vals = t._to_alt_values(tbl)
                bar = (alt.Chart(alt.Data(values=vals)).mark_bar(color="#0ea5e9", opacity=0.85)
                       .encode(x=alt.X("Duration:N", sort=order, title="Hold time"),
                               y=alt.Y("Win %:Q", title="Win %"),
                               tooltip=["Duration:N", "Trades:Q", "Win %:Q", "Avg R:Q"])
                       .properties(height=240))
                st.markdown("**By trade duration**")
                st.altair_chart(styler(bar), use_container_width=True)


# ── 4. Execution quality ──────────────────────────────────────────────────────
def _execution_section(df: pd.DataFrame, styler) -> None:
    t = _t()
    st.markdown("### Execution Quality")
    st.caption("How cleanly you execute the plan: entry deviation, planned vs realised R, and price-delivery grade.")
    dev = _num(df, "Deviation Score")
    planned = _num(df, "Planned R:R")
    rr = _num(df, "Closed RR")
    has_pd = "Price Delivery" in df.columns
    if dev is None and planned is None and not has_pd:
        t._unavailable("Execution Quality"); return

    cards = []
    if dev is not None:
        cards.append(("Avg deviation score", f"{float(dev.mean()):.2f}", "lower = closer to plan"))
    if planned is not None and rr is not None:
        g = df.copy(); g["__p"] = planned.values; g["__r"] = rr.values
        wins = g[g["__r"] > 0]
        if not wins.empty:
            ach = float((wins["__r"] / wins["__p"].replace(0, np.nan)).clip(0, 2).mean() * 100)
            cards.append(("Plan achievement", f"{ach:.0f}%", "realised R vs planned R (wins)"))
        cards.append(("Avg planned R:R", f"{float(g['__p'].mean()):.1f}", "your target ambition"))
    if cards:
        cols = st.columns(len(cards))
        for col, (lab, val, sub) in zip(cols, cards):
            with col: _kpi(lab, val, sub)

    if has_pd:
        g = df.copy()
        g["__pd"] = g["Price Delivery"].astype(str).str.strip()
        g = g[~g["__pd"].isin(["", "nan", "None"])]
        if rr is not None:
            g["__rr"] = pd.to_numeric(df["Closed RR"], errors="coerce")
        if "Outcome" in g.columns:
            g["__oc"] = g["Outcome"]
        else:
            g["__oc"] = np.where(g.get("__rr", 0) > 0, "Win", np.where(g.get("__rr", 0) < 0, "Loss", "BE"))
        rows = []
        for grade in ["Good", "Average", "Poor"]:
            sub = g[g["__pd"].str.contains(grade, case=False, na=False)]
            cnt = sub[sub["__oc"].isin(["Win", "BE", "Loss"])]
            if cnt.empty:
                continue
            wr = cnt["__oc"].eq("Win").sum() / len(cnt) * 100.0
            rows.append({"Price Delivery": grade, "Trades": len(sub), "Win %": round(wr, 1)})
        if rows:
            vals = t._to_alt_values(pd.DataFrame(rows))
            bar = (alt.Chart(alt.Data(values=vals)).mark_bar(opacity=0.85)
                   .encode(x=alt.X("Price Delivery:N", sort=["Good", "Average", "Poor"], title=None),
                           y=alt.Y("Win %:Q", title="Win %"),
                           color=alt.Color("Price Delivery:N", legend=None,
                                           scale=alt.Scale(domain=["Good", "Average", "Poor"],
                                                           range=["#16a34a", "#f59e0b", "#ef4444"])),
                           tooltip=["Price Delivery:N", "Trades:Q", "Win %:Q"])
                   .properties(height=240))
            st.markdown("**Win rate by price-delivery grade**")
            st.altair_chart(styler(bar), use_container_width=True)


# ── Entry point ───────────────────────────────────────────────────────────────
def render_mt5_tab(f_perf: pd.DataFrame, df_all: pd.DataFrame, styler) -> None:
    """Render all four MT5-only analytics sections."""
    data = f_perf if (f_perf is not None and not f_perf.empty) else df_all
    if data is None or data.empty:
        st.info("No trades for current filters.")
        return
    st.markdown('<div class="section">', unsafe_allow_html=True)
    _mae_mfe_section(data, styler)
    st.divider()
    _dollar_pnl_section(data, styler)
    st.divider()
    _timing_section(data, styler)
    st.divider()
    _execution_section(data, styler)
    st.markdown("</div>", unsafe_allow_html=True)
