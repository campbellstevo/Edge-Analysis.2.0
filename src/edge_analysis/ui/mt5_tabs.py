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
import re
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

    # Prefer MT5's native computed columns when present (exact, not estimated)
    _eff = _num(df, "MFE Efficiency %")
    if _eff is not None:
        cap_eff = float(_eff.mean())
    _gb = _num(df, "Give-back after MFE (R)")
    if _gb is not None:
        avg_giveback = float(_gb.mean())
    _tgt = _num(df, "Target Achieved %")
    avg_tgt = float(_tgt.mean()) if _tgt is not None else float("nan")

    cols = st.columns(5 if not np.isnan(avg_tgt) else 4)
    with cols[0]: _kpi("Avg MFE (favour)", f"{avg_mfe:.2f}R", "avg peak in your favour")
    with cols[1]: _kpi("Avg MAE (heat)", "—" if np.isnan(avg_mae) else f"{avg_mae:.2f}R", "avg dip before close")
    with cols[2]: _kpi("Capture efficiency", "—" if np.isnan(cap_eff) else f"{cap_eff:.0f}%", "of favour banked on wins")
    with cols[3]: _kpi("Avg give-back", "—" if np.isnan(avg_giveback) else f"{avg_giveback:.2f}R", "left on table per win")
    if not np.isnan(avg_tgt):
        with cols[4]: _kpi("Target achieved", f"{avg_tgt:.0f}%", "of planned target hit")

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
    _pdcol = next((c for c in ["Price action delivery", "Price Delivery"] if c in df.columns), None)
    has_pd = _pdcol is not None
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
        g["__pd"] = g[_pdcol].astype(str).str.strip()
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
    """Render all MT5-only analytics sections."""
    data = f_perf if (f_perf is not None and not f_perf.empty) else df_all
    if data is None or data.empty:
        st.info("No trades for current filters.")
        return
    st.markdown('<div class="section">', unsafe_allow_html=True)

    st.markdown("## 📈 Performance & Money")
    _dollar_pnl_section(data, styler)
    st.divider()
    _mae_mfe_section(data, styler)
    st.divider()
    _missed_runner_section(data, styler)

    st.markdown("## 🧭 Edge Breakdown")
    _direction_section(data, styler)
    st.divider()
    _conviction_section(data, styler)
    st.divider()
    _holdtime_section(data, styler)
    st.divider()
    _spread_section(data, styler)
    st.divider()
    _timing_section(data, styler)

    st.markdown("## 🎯 Discipline & Execution")
    _discipline_section(data, styler)
    st.divider()
    _mistake_section(data, styler)
    st.divider()
    _execution_section(data, styler)

    st.markdown("</div>", unsafe_allow_html=True)


# ============================================================================
# Batch 1 additions — categorical breakdowns & behavioural analytics
# ============================================================================

def _explode_multi(df: pd.DataFrame, col: str) -> pd.DataFrame:
    g = df.copy()
    g["__tok"] = g[col].astype(str).apply(
        lambda v: [t.strip() for t in re.split(r"[;,]", v)
                   if t.strip() and t.strip().lower() not in ("nan", "none", "")]
    )
    g = g.explode("__tok")
    return g[g["__tok"].notna() & (g["__tok"].astype(str).str.strip() != "")]


def _cat_stats(df: pd.DataFrame, col: str, multi: bool = False, min_n: int = 1):
    """Return DataFrame [Category, Trades, Win %, Avg R, Net R] grouped by col."""
    if col not in df.columns:
        return None
    if multi:
        g = _explode_multi(df, col)
    else:
        g = df.copy()
        g["__tok"] = g[col].astype(str).str.strip()
        g = g[~g["__tok"].str.lower().isin(["", "nan", "none"])]
    if g.empty:
        return None
    g["__rr"] = pd.to_numeric(g.get("Closed RR"), errors="coerce")
    g["__oc"] = g["Outcome"] if "Outcome" in g.columns else np.where(
        g["__rr"] > 0, "Win", np.where(g["__rr"] < 0, "Loss", "BE"))
    rows = []
    for cat, sub in g.groupby("__tok"):
        cnt = sub[pd.Series(sub["__oc"]).isin(["Win", "BE", "Loss"])]
        n = len(cnt)
        if n < min_n:
            continue
        wr = pd.Series(cnt["__oc"]).eq("Win").sum() / n * 100 if n else 0.0
        avgr = sub["__rr"].mean()
        rows.append({"Category": str(cat), "Trades": len(sub), "Win %": round(wr, 1),
                     "Avg R": round(float(avgr), 2) if pd.notna(avgr) else 0.0,
                     "Net R": round(float(sub["__rr"].sum()), 1) if sub["__rr"].notna().any() else 0.0})
    return pd.DataFrame(rows) if rows else None


def _expectancy_bar(rows, title: str, styler, sort=None, caption: str = "") -> None:
    """Clean horizontal expectancy bars: green/red by sign, with the value,
    win-rate and trade count labelled on each bar."""
    t = _t()
    st.markdown(f"### {title}")
    if caption:
        st.caption(caption)
    if rows is None or len(rows) == 0:
        t._unavailable(title)
        return
    d = rows.copy()
    d["AvgR"] = pd.to_numeric(d["Avg R"], errors="coerce").fillna(0.0)
    d["Colour"] = d["AvgR"].apply(lambda x: "good" if x >= 0 else "bad")

    def _label(r):
        parts = [f"{r['AvgR']:+.2f}R"]
        if "Win %" in d.columns and pd.notna(r.get("Win %")) and float(r.get("Win %") or 0) > 0:
            parts.append(f"{float(r['Win %']):.0f}% win")
        if "Trades" in d.columns and pd.notna(r.get("Trades")):
            parts.append(f"{int(r['Trades'])} trades")
        return "   ·   ".join(parts)
    d["Label"] = d.apply(_label, axis=1)

    lo = float(d["AvgR"].min()); hi = float(d["AvgR"].max())
    span = max(hi - lo, 0.5)
    dom = [min(lo, 0.0) - span * 0.30, max(hi, 0.0) + span * 0.55]
    ysort = sort if sort else "-x"
    vals = t._to_alt_values(d)
    base = alt.Chart(alt.Data(values=vals))

    bars = base.mark_bar(size=26, cornerRadius=4).encode(
        x=alt.X("AvgR:Q", title="Avg R per trade", scale=alt.Scale(domain=dom),
                axis=alt.Axis(tickCount=5, format="+.1f", grid=True, gridColor="#eef0f5",
                              labelColor="#94a3b8", titleColor="#94a3b8")),
        y=alt.Y("Category:N", sort=ysort, title=None,
                axis=alt.Axis(labelFontSize=13, labelColor="#0f172a", labelLimit=200,
                              ticks=False, domain=False)),
        color=alt.Color("Colour:N", legend=None,
                        scale=alt.Scale(domain=["good", "bad"], range=["#16a34a", "#ef4444"])),
        tooltip=["Category:N", "Trades:Q", "Win %:Q", "Avg R:Q", "Net R:Q"],
    )
    text = base.mark_text(
        fontSize=12, fontWeight="bold", color="#334155",
        align=alt.expr(alt.expr.if_(alt.datum.AvgR >= 0, "left", "right")),
        dx=alt.expr(alt.expr.if_(alt.datum.AvgR >= 0, 8, -8)),
    ).encode(
        x=alt.X("AvgR:Q", scale=alt.Scale(domain=dom)),
        y=alt.Y("Category:N", sort=ysort),
        text="Label:N",
    )
    rule = alt.Chart(alt.Data(values=[{"x": 0}])).mark_rule(color="#cbd5e1", strokeWidth=1.5).encode(x="x:Q")
    chart = alt.layer(bars, rule, text).properties(height=max(90, len(d) * 56))
    st.altair_chart(styler(chart), use_container_width=True)


def _mistake_section(df: pd.DataFrame, styler) -> None:
    t = _t()
    st.markdown("### Mistake Leak Report")
    st.caption("How often each mistake shows up and the average R it costs you versus clean trades.")
    if "Mistake" not in df.columns:
        t._unavailable("Mistake Leak Report"); return
    g = df.copy()
    g["__rr"] = pd.to_numeric(g.get("Closed RR"), errors="coerce")
    g["__mk"] = g["Mistake"].astype(str)
    clean = g[g["__mk"].str.strip().str.lower().isin(["", "nan", "none", "na"])]
    baseline = float(clean["__rr"].mean()) if not clean.empty and clean["__rr"].notna().any() else float(g["__rr"].mean() or 0.0)

    ex = _explode_multi(g, "Mistake")
    ex = ex[~ex["__tok"].str.lower().eq("na")]
    if ex.empty:
        t._insight_box("No mistakes tagged yet — keep logging the <b>Mistake</b> field and this will fill in.", "good")
        return
    rows = []
    for mk, sub in ex.groupby("__tok"):
        avg = float(sub["__rr"].mean()) if sub["__rr"].notna().any() else 0.0
        cost = (avg - baseline) * len(sub)  # R vs a clean trade, summed
        rows.append({"Category": mk, "Trades": len(sub), "Win %": 0.0,
                     "Avg R": round(avg, 2), "Net R": round(float(sub["__rr"].sum()), 1),
                     "Cost vs clean (R)": round(cost, 1)})
    rdf = pd.DataFrame(rows).sort_values("Cost vs clean (R)")
    rdf["Cost"] = pd.to_numeric(rdf["Cost vs clean (R)"], errors="coerce").fillna(0.0)
    rdf["Colour"] = rdf["Cost"].apply(lambda x: "ok" if x >= 0 else "bad")
    rdf["Label"] = rdf.apply(lambda r: f"{r['Cost']:+.0f}R   ·   {int(r['Trades'])} trades", axis=1)
    lo = float(rdf["Cost"].min()); hi = float(rdf["Cost"].max())
    span = max(hi - lo, 2.0)
    dom = [min(lo, 0.0) - span * 0.30, max(hi, 0.0) + span * 0.40]
    vals = t._to_alt_values(rdf)
    base = alt.Chart(alt.Data(values=vals))
    bar = (base.mark_bar(size=26, cornerRadius=4)
           .encode(x=alt.X("Cost:Q", title="R cost vs a clean trade  (red = costing you)",
                           scale=alt.Scale(domain=dom),
                           axis=alt.Axis(tickCount=5, format="+.0f", grid=True, gridColor="#eef0f5",
                                         labelColor="#94a3b8", titleColor="#94a3b8")),
                   y=alt.Y("Category:N", sort="x", title=None,
                           axis=alt.Axis(labelFontSize=13, labelColor="#0f172a", ticks=False, domain=False)),
                   color=alt.Color("Colour:N", legend=None,
                                   scale=alt.Scale(domain=["ok", "bad"], range=["#94a3b8", "#ef4444"])),
                   tooltip=["Category:N", "Trades:Q", "Avg R:Q", "Cost vs clean (R):Q"]))
    text = (base.mark_text(fontSize=12, fontWeight="bold", color="#334155",
                           align=alt.expr(alt.expr.if_(alt.datum.Cost >= 0, "left", "right")),
                           dx=alt.expr(alt.expr.if_(alt.datum.Cost >= 0, 8, -8)))
            .encode(x=alt.X("Cost:Q", scale=alt.Scale(domain=dom)), y=alt.Y("Category:N", sort="x"), text="Label:N"))
    rule = alt.Chart(alt.Data(values=[{"x": 0}])).mark_rule(color="#cbd5e1", strokeWidth=1.5).encode(x="x:Q")
    st.altair_chart(styler(alt.layer(bar, rule, text).properties(height=max(110, len(rdf) * 56))), use_container_width=True)
    worst = rdf.iloc[0]
    total_cost = float(rdf["Cost vs clean (R)"].clip(upper=0).sum())
    st.caption(f"Clean-trade baseline: {baseline:+.2f}R avg.")
    t._insight_box(
        f"Your costliest leak is <b>{worst['Category']}</b> — {int(worst['Trades'])} trades at "
        f"<b>{worst['Avg R']:+.2f}R</b> avg (vs {baseline:+.2f}R clean), ~<b>{worst['Cost vs clean (R)']:.0f}R</b> lost. "
        f"All mistakes combined cost roughly <b>{total_cost:.0f}R</b>.", "bad")


def _conviction_section(df: pd.DataFrame, styler) -> None:
    rows = _cat_stats(df, "Conviction (1-5)")
    order = ["1", "2", "3", "4", "5"]
    if rows is not None:
        rows = rows[rows["Category"].isin(order)]
        rows = rows.assign(__o=rows["Category"].map(lambda v: order.index(v) if v in order else 9)).sort_values("__o").drop(columns="__o")
    _expectancy_bar(rows, "Conviction Calibration", styler,
                    sort=order, caption="Average R by your 1–5 conviction. If it doesn't rise with conviction, your read is miscalibrated.")
    if rows is not None and len(rows) >= 2:
        hi = rows[rows["Category"].isin(["4", "5"])]["Avg R"].mean()
        lo = rows[rows["Category"].isin(["1", "2"])]["Avg R"].mean()
        if pd.notna(hi) and pd.notna(lo):
            if hi > lo:
                _t()._insight_box(f"Calibrated ✓ — high-conviction (4–5) trades average <b>{hi:+.2f}R</b> vs <b>{lo:+.2f}R</b> for low (1–2).", "good")
            else:
                _t()._insight_box(f"Miscalibrated — high-conviction trades (<b>{hi:+.2f}R</b>) aren't beating low-conviction ones (<b>{lo:+.2f}R</b>). Your gut may be inverted.", "warn")


def _discipline_section(df: pd.DataFrame, styler) -> None:
    t = _t()
    st.markdown("### Discipline Scorecard")
    st.caption("What following your rules and taking only A+ setups is actually worth in R.")
    g = df.copy()
    g["__rr"] = pd.to_numeric(g.get("Closed RR"), errors="coerce")
    g["__oc"] = g["Outcome"] if "Outcome" in g.columns else np.where(g["__rr"] > 0, "Win", np.where(g["__rr"] < 0, "Loss", "BE"))

    def _two(mask_true, label_true, label_false):
        out = []
        for lab, sub in ((label_true, g[mask_true]), (label_false, g[~mask_true])):
            cnt = sub[pd.Series(sub["__oc"]).isin(["Win", "BE", "Loss"])]
            if cnt.empty:
                continue
            wr = pd.Series(cnt["__oc"]).eq("Win").sum() / len(cnt) * 100
            out.append({"Category": lab, "Trades": len(sub), "Win %": round(wr, 1),
                        "Avg R": round(float(sub["__rr"].mean()), 2) if sub["__rr"].notna().any() else 0.0,
                        "Net R": round(float(sub["__rr"].sum()), 1)})
        return pd.DataFrame(out) if out else None

    did = False
    if "Rules Followed?" in g.columns:
        rf = g["Rules Followed?"].astype(str).str.strip().str.lower().isin(["true", "yes", "__yes__", "1"])
        _expectancy_bar(_two(rf, "Rules followed", "Rules broken"), "Rules Followed vs Broken", styler,
                        sort=["Rules followed", "Rules broken"]); did = True
    if "A+ Setup?" in g.columns:
        ap = g["A+ Setup?"].astype(str).str.strip().str.lower().eq("yes")
        st.divider()
        _expectancy_bar(_two(ap, "A+ setup", "Not A+"), "A+ Setups vs The Rest", styler,
                        sort=["A+ setup", "Not A+"]); did = True
    if not did:
        t._unavailable("Discipline Scorecard")


def _direction_section(df: pd.DataFrame, styler) -> None:
    _expectancy_bar(_cat_stats(df, "Direction"), "Long vs Short", styler,
                    sort=["Long", "Short"], caption="Expectancy, win rate and net R by trade direction.")


def _holdtime_section(df: pd.DataFrame, styler) -> None:
    t = _t()
    hold = _num(df, "Hold Time (min)")
    if hold is None:
        return
    g = df.copy(); g["__h"] = hold.values
    g = g[pd.notna(g["__h"])]
    if g.empty:
        return
    bins = [0, 15, 30, 60, 120, 240, 1e9]
    labels = ["0–15m", "15–30m", "30–60m", "1–2h", "2–4h", "4h+"]
    g["__cat"] = pd.cut(g["__h"], bins=bins, labels=labels, right=True, include_lowest=True).astype(str)
    rows = _cat_stats(g, "__cat")
    if rows is not None:
        rows = rows.assign(__o=rows["Category"].map(lambda v: labels.index(v) if v in labels else 9)).sort_values("__o").drop(columns="__o")
    _expectancy_bar(rows, "Hold-Time Window", styler, sort=labels,
                    caption="Average R by how long trades were held — find your optimal hold window.")


def _spread_section(df: pd.DataFrame, styler) -> None:
    spread = _num(df, "Spread at Entry")
    if spread is None:
        return
    g = df.copy(); g["__s"] = spread.values
    g = g[pd.notna(g["__s"])]
    if g.empty or g["__s"].nunique() < 2:
        return
    try:
        g["__cat"] = pd.qcut(g["__s"], q=min(3, g["__s"].nunique()),
                             labels=["Tight spread", "Normal spread", "Wide spread"][:min(3, g["__s"].nunique())], duplicates="drop").astype(str)
    except Exception:
        return
    _expectancy_bar(_cat_stats(g, "__cat"), "Spread vs Outcome", styler,
                    sort=["Tight spread", "Normal spread", "Wide spread"],
                    caption="Does your edge degrade when spreads widen (news / Asia)? Grouped by entry spread.")


def _missed_runner_section(df: pd.DataFrame, styler) -> None:
    t = _t()
    st.markdown("### Missed Runners")
    st.caption("Trades where you exited and price then hit full TP without you — and the R it left behind.")
    if "Hit Full TP Without You" not in df.columns:
        t._unavailable("Missed Runners"); return
    g = df.copy()
    g["__hit"] = g["Hit Full TP Without You"].astype(str).str.strip().str.lower()
    missed = g[g["__hit"] == "yes"]
    total = len(g[g["__hit"].isin(["yes", "no"])])
    n = len(missed)
    pct = round(n / max(1, total) * 100, 1)
    rr = pd.to_numeric(missed.get("Closed RR"), errors="coerce")
    mfe = pd.to_numeric(missed.get("MFE (R)"), errors="coerce")
    left = float((mfe - rr).clip(lower=0).sum()) if (mfe is not None and rr is not None and not missed.empty) else float("nan")
    c1, c2, c3 = st.columns(3)
    with c1: _kpi("Missed runners", f"{n}", f"{pct}% of trades", "#ef4444" if pct > 15 else PURPLE)
    with c2: _kpi("R left behind", "—" if np.isnan(left) else f"{left:.0f}R", "captured-to-TP gap")
    with c3:
        avg_left = (left / n) if (n and not np.isnan(left)) else float("nan")
        _kpi("Avg per miss", "—" if np.isnan(avg_left) else f"{avg_left:.1f}R", "left on each")
    if n and not np.isnan(left) and pct > 12:
        t._insight_box(f"You exited <b>{n}</b> trades ({pct}%) that then ran to full TP, leaving ~<b>{left:.0f}R</b> on the table. "
                       f"Cross-check with the Exit Optimizer before tightening management.", "warn")
