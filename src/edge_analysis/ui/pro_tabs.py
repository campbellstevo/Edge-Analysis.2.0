"""
MT5 Pro Analytics (Batch 2) — advanced simulators and behavioural models.

All sections require the richer MT5 fields and degrade gracefully when missing.
Helpers from tabs.py are imported lazily to avoid a circular import.
"""
from __future__ import annotations
import numpy as np
import pandas as pd
import altair as alt
import streamlit as st

from edge_analysis.ui.mt5_tabs import _num, _kpi, _section_header, PURPLE


def _t():
    from edge_analysis.ui import tabs as _tabs
    return _tabs


def _oc(g: pd.DataFrame, rr="__rr") -> pd.Series:
    if "Outcome" in g.columns:
        return g["Outcome"]
    return pd.Series(np.where(g[rr] > 0, "Win", np.where(g[rr] < 0, "Loss", "BE")), index=g.index)


# ── 1. Exit Optimization Simulator ────────────────────────────────────────────
def _exit_optimizer(df, styler) -> None:
    t = _t()
    st.markdown("### Exit Optimization Simulator")
    st.caption("Replays every trade under different fixed R-targets using how far it actually ran (MFE) "
               "and how far it dipped (MAE), to find the target that maximises expectancy. A model, not a guarantee.")
    mfe = _num(df, "MFE (R)"); rr = _num(df, "Closed RR"); mae = _num(df, "MAE (R)")
    if mfe is None or rr is None:
        t._unavailable("Exit Optimization Simulator"); return
    g = df.copy(); g["__mfe"] = mfe.values; g["__rr"] = rr.values
    g["__mae"] = mae.values if mae is not None else -1.0
    g = g[pd.notna(g["__mfe"]) & pd.notna(g["__rr"])]
    if len(g) < 10:
        t._insight_box("Need ~10+ trades with MFE logged for the exit simulator.", "warn"); return
    n = len(g)
    actual_total = float(g["__rr"].sum()); actual_exp = actual_total / n
    top = float(min(12.0, max(2.0, np.nanpercentile(g["__mfe"], 95))))
    targets = np.round(np.arange(1.0, top + 0.5, 0.5), 2)
    rows = []
    for T in targets:
        sim = np.where(g["__mfe"] >= T, T, np.where(g["__mae"] <= -1, -1.0, g["__rr"]))
        rows.append({"Target": float(T), "Expectancy": round(float(np.mean(sim)), 3), "Total R": round(float(np.sum(sim)), 1)})
    rdf = pd.DataFrame(rows)
    best = rdf.loc[rdf["Expectancy"].idxmax()]
    vals = t._to_alt_values(rdf)
    line = (alt.Chart(alt.Data(values=vals)).mark_line(point=True, color=PURPLE, strokeWidth=2)
            .encode(x=alt.X("Target:Q", title="Fixed R target"),
                    y=alt.Y("Expectancy:Q", title="Expectancy (R / trade)"),
                    tooltip=["Target:Q", "Expectancy:Q", "Total R:Q"]).properties(height=280))
    cur = alt.Chart(alt.Data(values=[{"y": actual_exp}])).mark_rule(color="#94a3b8", strokeDash=[4, 4]).encode(y=alt.Y("y:Q", title=None))
    best_data = alt.Chart(alt.Data(values=[{"bx": float(best["Target"]), "by": float(best["Expectancy"])}]))
    best_pt = best_data.mark_point(filled=True, size=220, color="#16a34a", stroke="#fff", strokeWidth=2.5).encode(x=alt.X("bx:Q", title=None), y=alt.Y("by:Q", title=None))
    st.altair_chart(styler(alt.layer(line, cur, best_pt)), use_container_width=True)
    c1, c2, c3 = st.columns(3)
    with c1: _kpi("Your actual expectancy", f"{actual_exp:+.2f}R", f"{actual_total:+.0f}R total")
    with c2: _kpi("Best fixed target", f"+{best['Target']:.1f}R", f"{best['Expectancy']:+.2f}R / trade")
    with c3:
        delta = best["Total R"] - actual_total
        _kpi("Improvement", f"{delta:+.0f}R", "vs your actual exits", "#16a34a" if delta >= 0 else "#ef4444")
    if best["Expectancy"] > actual_exp + 0.05:
        t._insight_box(f"A flat <b>+{best['Target']:.1f}R</b> target would lift expectancy from <b>{actual_exp:+.2f}R</b> "
                       f"to <b>{best['Expectancy']:+.2f}R</b> (~<b>{best['Total R'] - actual_total:+.0f}R</b>). "
                       f"Your discretionary exits may be leaving money on the table.", "warn")
    else:
        t._insight_box(f"Your exits (<b>{actual_exp:+.2f}R</b>) are already near the optimal fixed target — management is holding up.", "good")
    st.caption("Dashed line = your actual expectancy. Model assumes a target is banked if MFE reached it and a −1R stop otherwise.")


# ── 2. Stop-Loss Optimizer (MAE) ──────────────────────────────────────────────
def _mae_stop_optimizer(df, styler) -> None:
    t = _t()
    st.markdown("### Stop-Loss Optimizer (MAE)")
    st.caption("How far your winners actually dipped before working. A tighter stop that still survives most winners "
               "improves your R:R.")
    mae = _num(df, "MAE (R)"); rr = _num(df, "Closed RR")
    if mae is None or rr is None:
        t._unavailable("Stop-Loss Optimizer"); return
    g = df.copy(); g["__mae"] = mae.values; g["__rr"] = rr.values
    g = g[pd.notna(g["__mae"]) & pd.notna(g["__rr"])]
    wins = g[g["__rr"] > 0]
    if len(wins) < 8:
        t._insight_box("Need ~8+ winning trades with MAE logged for the stop optimizer.", "warn"); return
    mag = (-wins["__mae"]).clip(lower=0)
    stops = np.round(np.arange(0.3, 2.05, 0.1), 2)
    rows = [{"Stop (R)": float(S), "Winners surviving %": round(float((mag <= S).mean() * 100), 1)} for S in stops]
    rdf = pd.DataFrame(rows)
    keep = rdf[rdf["Winners surviving %"] >= 95]
    rec = float(keep.iloc[0]["Stop (R)"]) if not keep.empty else float(rdf["Stop (R)"].max())
    vals = t._to_alt_values(rdf)
    area = (alt.Chart(alt.Data(values=vals)).mark_area(opacity=0.12, color=PURPLE)
            .encode(x=alt.X("Stop (R):Q", title="Stop distance (R)"), y=alt.Y("Winners surviving %:Q")))
    line = (alt.Chart(alt.Data(values=vals)).mark_line(color=PURPLE, strokeWidth=2)
            .encode(x="Stop (R):Q", y=alt.Y("Winners surviving %:Q", scale=alt.Scale(domain=[0, 100])),
                    tooltip=["Stop (R):Q", "Winners surviving %:Q"]))
    rec_surv = float(rdf.loc[rdf["Stop (R)"] == rec, "Winners surviving %"].iloc[0]) if (rdf["Stop (R)"] == rec).any() else 100.0
    rec_data = alt.Chart(alt.Data(values=[{"bx": rec, "by": rec_surv}]))
    rec_pt = rec_data.mark_point(filled=True, size=220, color="#16a34a", stroke="#fff", strokeWidth=2.5).encode(x=alt.X("bx:Q", title=None), y=alt.Y("by:Q", title=None))
    st.altair_chart(styler(alt.layer(area, line, rec_pt).properties(height=260)), use_container_width=True)
    med = float(mag.median()); p90 = float(mag.quantile(0.9))
    c1, c2, c3 = st.columns(3)
    with c1: _kpi("Median winner MAE", f"−{med:.2f}R", "typical heat on a winner")
    with c2: _kpi("90% of winners within", f"−{p90:.2f}R", "rarely dip past this")
    with c3: _kpi("Suggested stop", f"−{rec:.1f}R", "keeps ≥95% of winners")
    t._insight_box(f"95% of your winners never dipped past <b>−{rec:.1f}R</b>. If you're risking more than that, "
                   f"a tighter stop would barely touch your winners while shrinking every loss — a direct R:R upgrade.", "good")


# ── 3. Monte Carlo on your real R distribution ────────────────────────────────
def _monte_carlo(df, styler) -> None:
    t = _t()
    st.markdown("### Monte Carlo — Your Real R Distribution")
    st.caption("Resamples your actual trade outcomes thousands of times to project equity, risk of ruin, and optimal risk.")
    rr = _num(df, "Closed RR")
    if rr is None:
        t._unavailable("Monte Carlo"); return
    r = rr.dropna().values
    if len(r) < 20:
        t._insight_box("Need ~20+ completed trades for a reliable Monte Carlo.", "warn"); return

    with st.expander("Simulation settings"):
        risk = t._slider_row(
            "Risk per trade", lambda v: f"{v:.2f}%",
            lambda: st.slider("Risk per trade", min_value=0.25, max_value=5.0,
                              value=1.0, step=0.25, key="pro_mc_risk",
                              label_visibility="collapsed"))
        n_tr = t._slider_row(
            "Trades to project", lambda v: f"{v}",
            lambda: st.slider("Trades to project", min_value=50, max_value=1000,
                              value=300, step=50, key="pro_mc_n",
                              label_visibility="collapsed"))
        start = t._slider_row(
            "Starting balance", lambda v: f"${v:,.0f}",
            lambda: st.slider("Starting balance", min_value=1_000, max_value=200_000,
                              value=10_000, step=1_000, key="pro_mc_bal",
                              label_visibility="collapsed"))

    N = 2000
    rng = np.random.default_rng(7)
    draws = rng.choice(r, size=(N, int(n_tr)), replace=True)
    growth = np.cumprod(1 + draws * (risk / 100.0), axis=1)
    eq = float(start) * growth
    final = eq[:, -1]
    p5, p50, p95 = [float(x) for x in np.percentile(final, [5, 50, 95])]
    min_eq = eq.min(axis=1)
    ruin = float((min_eq <= float(start) * 0.5).mean() * 100)  # 50% drawdown = "ruin"

    idx = np.arange(1, int(n_tr) + 1)
    cur = pd.DataFrame({"Trade": idx,
                        "p5": np.percentile(eq, 5, axis=0),
                        "p50": np.percentile(eq, 50, axis=0),
                        "p95": np.percentile(eq, 95, axis=0)})
    cur = cur[cur["Trade"] % max(1, int(n_tr) // 120) == 0]
    band = (alt.Chart(alt.Data(values=t._to_alt_values(cur))).mark_area(opacity=0.15, color=PURPLE)
            .encode(x=alt.X("Trade:Q"), y=alt.Y("p5:Q", title="Balance ($)"), y2="p95:Q"))
    med = (alt.Chart(alt.Data(values=t._to_alt_values(cur))).mark_line(color=PURPLE, strokeWidth=2)
           .encode(x=alt.X("Trade:Q", title=None), y=alt.Y("p50:Q", title=None),
                   tooltip=["Trade:Q", "p50:Q", "p5:Q", "p95:Q"]))
    st.altair_chart(styler(alt.layer(band, med).properties(height=300)), use_container_width=True)

    wins = r[r > 0]; losses = r[r < 0]
    W = len(wins) / len(r)
    avgW = float(wins.mean()) if len(wins) else 0.0
    avgL = float(abs(losses.mean())) if len(losses) else 1.0
    b = (avgW / avgL) if avgL else 0.0
    kelly = (W - (1 - W) / b) if b else 0.0
    k1, k2, k3, k4 = st.columns(4)
    with k1: _kpi("Median outcome", f"${p50:,.0f}", f"from ${float(start):,.0f}", "#16a34a" if p50 >= start else "#ef4444")
    with k2: _kpi("Unlucky (5th pct)", f"${p5:,.0f}", "bottom 5% of runs")
    with k3: _kpi("Risk of 50% DD", f"{ruin:.1f}%", "paths halving the account", "#ef4444" if ruin > 20 else PURPLE)
    with k4: _kpi("Kelly risk", f"{max(0.0, kelly) * 100:.1f}%", f"half-Kelly ≈ {max(0.0, kelly) * 50:.1f}%")
    msg = (f"At <b>{risk:.2f}%</b> risk, the median of {N:,} simulated runs is <b>${p50:,.0f}</b> after {int(n_tr)} trades, "
           f"with a <b>{ruin:.1f}%</b> chance of halving the account along the way.")
    if risk > max(0.0, kelly) * 100 and kelly > 0:
        msg += f" You're risking above Kelly ({kelly*100:.1f}%) — consider sizing down toward half-Kelly to cut ruin risk."
    t._insight_box(msg, "bad" if ruin > 25 else "info")


# ── 4. Tilt / Post-Loss behaviour ─────────────────────────────────────────────
def _tilt(df, styler) -> None:
    t = _t()
    st.markdown("### Tilt / Post-Loss Behaviour")
    st.caption("What happens to your trading right after a loss — the fingerprint of revenge trading.")
    g = df.copy()
    g["__dt"] = pd.to_datetime(g.get("Date"), errors="coerce")
    if g["__dt"].isna().all():
        t._unavailable("Tilt / Post-Loss Behaviour"); return
    g = g[g["__dt"].notna()].sort_values("__dt")
    g["__rr"] = pd.to_numeric(g.get("Closed RR"), errors="coerce")
    g["__oc"] = _oc(g).values
    g["__prev"] = g["__oc"].shift(1)
    rows = []
    for prev in ["Win", "BE", "Loss"]:
        sub = g[g["__prev"] == prev]
        cnt = sub[pd.Series(sub["__oc"]).isin(["Win", "BE", "Loss"])]
        if cnt.empty:
            continue
        wr = pd.Series(cnt["__oc"]).eq("Win").sum() / len(cnt) * 100
        rows.append({"Category": f"After a {prev}", "Trades": len(sub), "Win %": round(wr, 1),
                     "Avg R": round(float(sub["__rr"].mean()), 2) if sub["__rr"].notna().any() else 0.0,
                     "Net R": round(float(sub["__rr"].sum()), 1)})
    if not rows:
        t._unavailable("Tilt / Post-Loss Behaviour"); return
    from edge_analysis.ui.mt5_tabs import _line_metric
    order = [c for c in ["After a Win", "After a BE", "After a Loss"] if c in {r["Category"] for r in rows}]
    _line_metric(pd.DataFrame(rows), "", styler, value="Win %", x_order=order,
                 x_title="", baseline=50.0, fmt=".0f", suffix="%",
                 caption="Win rate by prior-trade outcome. A slope falling to the right = tilt after losses.")
    after_loss = next((r for r in rows if r["Category"] == "After a Loss"), None)
    after_win = next((r for r in rows if r["Category"] == "After a Win"), None)
    if after_loss and after_win:
        d = after_win["Win %"] - after_loss["Win %"]
        if d > 8:
            t._insight_box(f"Clear tilt signal — win rate drops to <b>{after_loss['Win %']:.0f}%</b> after a loss "
                           f"vs <b>{after_win['Win %']:.0f}%</b> after a win (a {d:.0f}-point swing). "
                           f"A mandatory pause after every loss would likely recover R.", "bad")
        else:
            t._insight_box(f"No strong tilt — your post-loss win rate ({after_loss['Win %']:.0f}%) holds up vs post-win "
                           f"({after_win['Win %']:.0f}%). Good emotional control.", "good")


# ── 5. A-Game vs Everything ───────────────────────────────────────────────────
def _a_game(df, styler) -> None:
    t = _t()
    st.markdown("### A-Game vs Everything")
    st.caption("What your stats look like when you trade your best — and what the off-plan trades cost you.")
    g = df.copy()
    g["__rr"] = pd.to_numeric(g.get("Closed RR"), errors="coerce")
    g["__oc"] = _oc(g).values
    mask = pd.Series(True, index=g.index)
    used = []
    if "A+ Setup?" in g.columns:
        mask &= g["A+ Setup?"].astype(str).str.strip().str.lower().eq("yes"); used.append("A+")
    if "Rules Followed?" in g.columns:
        mask &= g["Rules Followed?"].astype(str).str.strip().str.lower().isin(["true", "yes", "__yes__", "1"]); used.append("Rules followed")
    if "Conviction (1-5)" in g.columns:
        mask &= pd.to_numeric(g["Conviction (1-5)"], errors="coerce") >= 4; used.append("Conviction ≥4")
    if "Mental State" in g.columns:
        mask &= g["Mental State"].astype(str).str.contains("Clear", case=False, na=False); used.append("Clear & Calm")
    if not used:
        t._unavailable("A-Game vs Everything"); return

    def _stat(sub):
        cnt = sub[pd.Series(sub["__oc"]).isin(["Win", "BE", "Loss"])]
        if cnt.empty:
            return None
        return dict(n=len(sub),
                    wr=pd.Series(cnt["__oc"]).eq("Win").sum() / len(cnt) * 100,
                    exp=float(sub["__rr"].mean()) if sub["__rr"].notna().any() else 0.0,
                    net=float(sub["__rr"].sum()))
    a = _stat(g[mask]); alls = _stat(g); off = _stat(g[~mask])
    if not a or not alls:
        t._insight_box("Not enough A-game trades yet (need your manual fields filled).", "warn"); return
    c1, c2, c3 = st.columns(3)
    with c1: _kpi("A-Game win rate", f"{a['wr']:.0f}%", f"{a['n']} trades · {a['exp']:+.2f}R", "#16a34a")
    with c2: _kpi("All trades", f"{alls['wr']:.0f}%", f"{alls['n']} trades · {alls['exp']:+.2f}R")
    with c3:
        if off:
            _kpi("Off-plan cost", f"{off['net']:+.0f}R", f"{off['n']} off-plan trades", "#ef4444" if off['net'] < 0 else PURPLE)
        else:
            _kpi("Off-plan cost", "—", "no off-plan trades")
    st.caption("A-Game = " + " + ".join(used) + ".")
    if off and off["net"] < 0:
        t._insight_box(f"Your A-game trades return <b>{a['exp']:+.2f}R</b> at <b>{a['wr']:.0f}%</b>. The off-plan trades "
                       f"({off['n']}) drained <b>{off['net']:+.0f}R</b>. Trading only your A-setups is the cleanest edge you have.", "warn")
    else:
        t._insight_box(f"A-game expectancy <b>{a['exp']:+.2f}R</b> at <b>{a['wr']:.0f}%</b> win rate over {a['n']} trades.", "good")


# ── 6. Hour × Day expectancy heatmap ──────────────────────────────────────────
def _heatmap_hour_day(df, styler) -> None:
    t = _t()
    st.markdown("### When You Trade Best")
    st.caption("Your best and worst trading windows — average R per trade by weekday and hour (Melbourne time), minimum 2 trades.")
    g = df.copy()
    g["__rr"] = pd.to_numeric(g.get("Closed RR"), errors="coerce")
    hour = _num(df, "Hour (Melb)")
    if hour is not None:
        g["__hr"] = hour.values
    else:
        g["__hr"] = pd.to_datetime(g.get("Date"), errors="coerce").dt.hour
    if "Day" in g.columns and g["Day"].astype(str).str.strip().ne("").any():
        g["__day"] = g["Day"].astype(str).str.strip().str[:3]
    else:
        g["__day"] = pd.to_datetime(g.get("Date"), errors="coerce").dt.day_name().str[:3]
    g = g[pd.notna(g["__hr"]) & g["__day"].astype(str).str.len().gt(0) & g["__rr"].notna()]
    if g.empty:
        t._unavailable("Hour × Day heatmap"); return
    g["__hr"] = g["__hr"].astype(int)
    agg = g.groupby(["__day", "__hr"]).agg(AvgR=("__rr", "mean"), Trades=("__rr", "size")).reset_index()
    agg = agg.rename(columns={"__day": "Day", "__hr": "Hour"})
    agg["AvgR"] = agg["AvgR"].round(2)
    agg2 = agg[agg["Trades"] >= 2].copy()
    if agg2.empty:
        agg2 = agg.copy()
    agg2["Window"] = agg2["Day"].astype(str) + "  ·  " + agg2["Hour"].map(lambda h: f"{int(h):02d}:00")
    agg2 = agg2.sort_values("AvgR", ascending=False)
    show = agg2 if len(agg2) <= 10 else pd.concat([agg2.head(5), agg2.tail(5)])
    t._rank_dots(show, "Window", "AvgR")


# ── 7. Symbol × Session edge matrix ───────────────────────────────────────────
def _symbol_session_matrix(df, styler) -> None:
    t = _t()
    st.markdown("### Where Your Edge Lives")
    st.caption("Average R per trade by instrument and session — your strongest and weakest combinations, minimum 2 trades.")
    g = df.copy()
    g["__rr"] = pd.to_numeric(g.get("Closed RR"), errors="coerce")
    sym = next((c for c in ["Instrument", "Pair", "Symbol"] if c in g.columns), None)
    sess = next((c for c in ["Session Norm", "Session"] if c in g.columns), None)
    if sym is None or sess is None:
        t._unavailable("Symbol × Session matrix"); return
    g["__sym"] = g[sym].astype(str).str.strip()
    g["__sess"] = g[sess].astype(str).str.strip()
    g = g[g["__sym"].str.len().gt(0) & g["__sess"].str.len().gt(0) & g["__rr"].notna()
          & ~g["__sym"].str.lower().isin(["nan", "none"]) & ~g["__sess"].str.lower().isin(["nan", "none"])]
    if g.empty:
        t._unavailable("Symbol × Session matrix"); return
    agg = g.groupby(["__sym", "__sess"]).agg(AvgR=("__rr", "mean"), Trades=("__rr", "size")).reset_index()
    agg = agg.rename(columns={"__sym": "Symbol", "__sess": "Session"})
    agg["AvgR"] = agg["AvgR"].round(2)
    agg2 = agg[agg["Trades"] >= 2].copy()
    if agg2.empty:
        agg2 = agg.copy()
    agg2["Combo"] = agg2["Symbol"].astype(str) + "  ·  " + agg2["Session"].astype(str)
    agg2 = agg2.sort_values("AvgR", ascending=False)
    show = agg2 if len(agg2) <= 10 else pd.concat([agg2.head(5), agg2.tail(5)])
    t._rank_dots(show, "Combo", "AvgR")


# ── 8. Cost drag ──────────────────────────────────────────────────────────────
def _cost_drag(df, styler) -> None:
    t = _t()
    st.markdown("### Cost Drag")
    st.caption("How much commission and swap eat into your gross P&L.")
    pnl = _num(df, "PnL"); comm = _num(df, "Commission"); swap = _num(df, "Swap")
    if pnl is None or (comm is None and swap is None):
        t._unavailable("Cost Drag"); return
    net = float(pnl.sum())
    costs = 0.0
    if comm is not None:
        costs += float(comm.sum())
    if swap is not None:
        costs += float(swap.sum())
    gross = net - costs  # PnL is typically net of costs; gross = net minus (negative) costs
    drag_pct = abs(costs) / abs(gross) * 100 if gross else 0.0
    c1, c2, c3 = st.columns(3)
    with c1: _kpi("Net P&L", f"${net:,.0f}", "after costs", "#16a34a" if net >= 0 else "#ef4444")
    with c2: _kpi("Total costs", f"${abs(costs):,.0f}", "commission + swap")
    with c3: _kpi("Cost drag", f"{drag_pct:.1f}%", "of gross profit")
    if drag_pct > 8:
        t._insight_box(f"Costs are eating <b>{drag_pct:.1f}%</b> of your gross profit (${abs(costs):,.0f}). "
                       f"Worth checking your spread/commission tier or holding fewer trades overnight (swap).", "warn")


# ── Entry point ───────────────────────────────────────────────────────────────
def render_pro_tab(f_perf: pd.DataFrame, df_all: pd.DataFrame, styler) -> None:
    data = f_perf if (f_perf is not None and not f_perf.empty) else df_all
    if data is None or data.empty:
        st.info("No trades for current filters.")
        return
    st.markdown('<div class="section">', unsafe_allow_html=True)
    _section_header("Trade Management")
    _exit_optimizer(data, styler); st.divider()
    _mae_stop_optimizer(data, styler)
    _section_header("Risk & Projection")
    _monte_carlo(data, styler)
    _section_header("Behaviour")
    _tilt(data, styler); st.divider()
    _a_game(data, styler)
    _section_header("Edge Maps")
    _heatmap_hour_day(data, styler); st.divider()
    _symbol_session_matrix(data, styler); st.divider()
    _cost_drag(data, styler)
    st.markdown("</div>", unsafe_allow_html=True)
