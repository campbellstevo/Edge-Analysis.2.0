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


# ── Approved house-style helpers ──────────────────────────────────────────────
def _section_header(title: str, caption: str = None) -> None:
    """Clean section divider: air, thin rule, purple uppercase label, intro line."""
    cap = (f"<div style='font-size:14px;color:#8a93a6;margin-top:3px;'>{caption}</div>"
           if caption else "")
    st.markdown(
        f"<div style='margin:52px 0 10px;padding-top:22px;border-top:2px solid #eef0f5;'>"
        f"<div style='font-size:13px;font-weight:700;letter-spacing:0.14em;"
        f"text-transform:uppercase;color:{PURPLE};'>{title}</div>{cap}</div>",
        unsafe_allow_html=True,
    )


def _tiles(rows, styler=None) -> None:
    """Comparison stat tiles — one card per category. Replaces 2-3 category bars."""
    if rows is None or len(rows) == 0:
        return
    d = rows.reset_index(drop=True)
    cols = st.columns(len(d))
    for col, (_, r) in zip(cols, d.iterrows()):
        avg = float(pd.to_numeric(pd.Series([r.get("Avg R")]), errors="coerce").fillna(0.0).iloc[0])
        c = "#16a34a" if avg >= 0 else "#ef4444"
        wr = float(pd.to_numeric(pd.Series([r.get("Win %")]), errors="coerce").fillna(0.0).iloc[0])
        wr = max(0.0, min(100.0, wr))
        net = r.get("Net R")
        net_s = f" · {float(net):+.1f}R net" if net is not None and pd.notna(net) else ""
        trades = int(r.get("Trades", 0) or 0)
        cat = str(r.get("Category", ""))
        with col:
            st.markdown(
                f"<div style='background:#fff;border:1px solid rgba(0,0,0,0.06);border-radius:12px;"
                f"padding:14px 16px;box-shadow:0 2px 10px rgba(0,0,0,0.04);'>"
                f"<div style='font-size:13px;color:#64748b;font-weight:600;'>{cat} · {trades} trades</div>"
                f"<div style='font-size:34px;font-weight:800;line-height:1.15;color:{c};margin:6px 0 2px;'>{avg:+.2f}R</div>"
                f"<div style='font-size:13px;color:#64748b;'>{wr:.0f}% win{net_s}</div>"
                f"<div style='height:6px;border-radius:3px;margin-top:10px;"
                f"background:linear-gradient(90deg,{c} {wr:.0f}%, #e5e7eb {wr:.0f}%);'></div>"
                f"</div>", unsafe_allow_html=True)


def _line_metric(rows, title, styler, value="Avg R", x_order=None, x_title="",
                 caption="", baseline=0.0, fmt="+.2f", suffix="R") -> None:
    """Line chart for an ordered sequence (conviction, hold-time, hour, tilt).
    Points coloured green/red vs a baseline; value labelled above each point."""
    t = _t()
    if title:
        st.markdown(f"### {title}")
    if caption:
        st.caption(caption)
    if rows is None or len(rows) == 0:
        if title:
            t._unavailable(title)
        return
    d = rows.copy()
    d["__v"] = pd.to_numeric(d[value], errors="coerce")
    d = d[d["__v"].notna()]
    if d.empty:
        return
    d["__sign"] = d["__v"].apply(lambda x: "good" if x >= baseline else "bad")
    d["__lab"] = d["__v"].apply(lambda v: f"{v:{fmt}}{suffix}")
    tip = [alt.Tooltip("Category:N", title=" ")]
    for c in ("Trades", "Win %", "Avg R"):
        if c in d.columns:
            tip.append(alt.Tooltip(f"{c}:Q"))
    vals = t._to_alt_values(d)
    xenc = alt.X("Category:N", sort=(x_order if x_order else None), title=x_title,
                 axis=alt.Axis(labelAngle=0, labelFontSize=12, labelColor="#0f172a", labelLimit=140))
    base = alt.Chart(alt.Data(values=vals))
    rule = (alt.Chart(alt.Data(values=[{"y": baseline}]))
            .mark_rule(color="#cbd5e1", strokeDash=[4, 4]).encode(y=alt.Y("y:Q", title=None)))
    line = base.mark_line(color="#4800ff", strokeWidth=2.5, interpolate="monotone").encode(
        x=xenc, y=alt.Y("__v:Q", title=value,
                        axis=alt.Axis(labelColor="#94a3b8", titleColor="#94a3b8", grid=True, gridColor="#eef0f5")))
    pts = base.mark_point(filled=True, size=120, stroke="#fff", strokeWidth=2).encode(
        x=xenc, y="__v:Q",
        color=alt.Color("__sign:N", legend=None,
                        scale=alt.Scale(domain=["good", "bad"], range=["#16a34a", "#ef4444"])),
        tooltip=tip)
    text = base.mark_text(dy=-15, fontSize=12, fontWeight="bold", color="#334155").encode(
        x=xenc, y="__v:Q", text="__lab:N")
    st.altair_chart(styler(alt.layer(rule, line, pts, text).properties(height=300)), use_container_width=True)


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
        _m = float(_eff.mean())
        if 0.0 <= _m <= 100.0:
            cap_eff = _m
    if not np.isnan(cap_eff):
        cap_eff = float(min(max(cap_eff, 0.0), 100.0))
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
            alt.Chart(alt.Data(values=vals)).mark_circle(size=80, opacity=0.6, stroke="#fff", strokeWidth=1)
            .encode(
                x=alt.X("MFE_R:Q", title="MFE — favourable move available (R)",
                        axis=alt.Axis(grid=True, gridColor="#eef0f5", labelColor="#94a3b8", titleColor="#94a3b8")),
                y=alt.Y("Captured_R:Q", title="Captured (R)",
                        axis=alt.Axis(grid=True, gridColor="#eef0f5", labelColor="#94a3b8", titleColor="#94a3b8")),
                color=alt.Color("OutcomeC:N", title=None,
                                scale=alt.Scale(domain=["Win", "BE", "Loss"],
                                                range=["#16a34a", "#9ca3af", "#ef4444"])),
                tooltip=[alt.Tooltip("MFE_R:Q", title="MFE", format=".2f"),
                         alt.Tooltip("Captured_R:Q", title="Captured", format=".2f"),
                         alt.Tooltip("OutcomeC:N", title="Outcome")],
            )
        )
        diag = (alt.Chart(alt.Data(values=[{"x": 0, "y": 0}, {"x": hi, "y": hi}]))
                .mark_line(strokeDash=[4, 4], color=PURPLE)
                .encode(x=alt.X("x:Q", title=None), y=alt.Y("y:Q", title=None)))
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
    with c1: _kpi("Net P&L", f"{'-' if net < 0 else ''}${abs(net):,.0f}", f"over {len(g)} trades", "#16a34a" if net >= 0 else "#ef4444")
    with c2: _kpi("Avg / trade", f"{'-' if avg < 0 else ''}${abs(avg):,.2f}", "mean dollar result")
    with c3: _kpi("Profit factor", "—" if np.isnan(pf) else f"{pf:.2f}", "gross win $ / gross loss $")
    with c4: _kpi("Costs", f"{'-' if costs < 0 else ''}${abs(costs):,.0f}", "commission + swap")

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
                        .encode(x=alt.X("Date:T", title=None), y=alt.Y("CumUSD:Q", title=None)))
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
            tbl["Category"] = tbl["Hour"].map(lambda h: f"{int(h):02d}")
            st.markdown("**By hour of day** — win %, dashed line = 50/50")
            _line_metric(tbl, "", styler, value="Win %", x_order=list(tbl["Category"]),
                         x_title="Hour of day (Melb)", baseline=50.0, fmt=".0f", suffix="%")
            best = tbl.loc[tbl["Win %"].idxmax()]; worst = tbl.loc[tbl["Win %"].idxmin()]
            if int(best.get("Trades", 0)) >= 5:
                t._insight_box(
                    f"Best hour: <b>{int(best['Hour']):02d}:00</b> ({best['Win %']:.0f}% over {int(best['Trades'])} trades). "
                    f"Weakest: <b>{int(worst['Hour']):02d}:00</b> ({worst['Win %']:.0f}%).")


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

    _pe = _num(df, "Planned Entry"); _ep = _num(df, "Entry Price"); _slp = _num(df, "SL")
    if _pe is not None and _ep is not None and _slp is not None:
        gg = df.copy()
        gg["__pe"], gg["__ep"], gg["__sl"] = _pe.values, _ep.values, _slp.values
        gg = gg[gg["__pe"].notna() & gg["__ep"].notna() & gg["__sl"].notna()]
        gg = gg[(gg["__ep"] - gg["__sl"]).abs() > 0]
        if len(gg) >= 5:
            _long = gg.get("Direction", pd.Series("", index=gg.index)).astype(str).str.contains(
                "Long", case=False, na=False)
            _dev = pd.Series(
                np.where(_long, gg["__ep"] - gg["__pe"], gg["__pe"] - gg["__ep"]),
                index=gg.index) / (gg["__ep"] - gg["__sl"]).abs()
            _dev = _dev.clip(-3, 3)
            _avg_dev, _tot_dev = float(_dev.mean()), float(_dev.sum())
            st.markdown("**Entry deviation — planned vs actual**")
            dc1, dc2 = st.columns(2)
            with dc1:
                _kpi("Avg entry slip", f"{_avg_dev:+.2f}R", "vs planned entry, in stop-units")
            with dc2:
                _kpi("Total slip cost", f"{_tot_dev:+.1f}R", f"over {len(gg)} planned entries",
                     "#ef4444" if _tot_dev > 1 else PURPLE)
            if _avg_dev > 0.08:
                t._insight_box(
                    f"You enter on average <b>{_avg_dev:+.2f}R</b> worse than your planned level — "
                    f"about <b>{_tot_dev:+.1f}R</b> total given away to chasing. "
                    "Set the limit order at the plan and let it come to you.", "warn")

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
            srr = pd.to_numeric(sub.get("__rr"), errors="coerce") if "__rr" in sub.columns else None
            avgr = float(srr.mean()) if srr is not None and srr.notna().any() else 0.0
            netr = float(srr.sum()) if srr is not None and srr.notna().any() else None
            rows.append({"Category": grade, "Trades": len(sub), "Win %": round(wr, 1),
                         "Avg R": round(avgr, 2),
                         "Net R": round(netr, 1) if netr is not None else None})
        if rows:
            st.markdown("**By price-delivery grade**")
            _tiles(pd.DataFrame(rows))


# ── Entry point ───────────────────────────────────────────────────────────────
def render_mt5_tab(f_perf: pd.DataFrame, df_all: pd.DataFrame, styler) -> None:
    """Render all MT5-only analytics sections."""
    data = f_perf if (f_perf is not None and not f_perf.empty) else df_all
    if data is None or data.empty:
        st.info("No trades for current filters.")
        return
    st.markdown('<div class="section">', unsafe_allow_html=True)

    _section_header("Performance & Money")
    _dollar_pnl_section(data, styler)
    st.divider()
    _mae_mfe_section(data, styler)
    st.divider()
    _missed_runner_section(data, styler)

    _section_header("Edge Breakdown")
    _direction_section(data, styler)
    st.divider()
    _conviction_section(data, styler)
    st.divider()
    _holdtime_section(data, styler)
    st.divider()
    _spread_section(data, styler)
    st.divider()
    _timing_section(data, styler)

    _section_header("Discipline & Execution")
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
    bars = rdf.rename(columns={"Cost vs clean (R)": "R cost vs clean"})[
        ["Category", "R cost vs clean", "Trades"]]
    t._rank_dots(bars, "Category", "R cost vs clean", fmt="+.1f")
    st.caption("Bar = total R lost (or saved) versus a clean trade \u00b7 count = how often it happened. "
               f"Clean-trade baseline: {baseline:+.2f}R avg.")
    worst = rdf.iloc[0]
    total_cost = float(rdf["Cost vs clean (R)"].clip(upper=0).sum())
    st.caption(f"Clean-trade baseline: {baseline:+.2f}R avg.")
    t._insight_box(
        f"Your costliest leak is <b>{worst['Category']}</b> — {int(worst['Trades'])} trades at "
        f"<b>{worst['Avg R']:+.2f}R</b> avg (vs {baseline:+.2f}R clean), ~<b>{worst['Cost vs clean (R)']:.0f}R</b> lost. "
        f"All mistakes combined cost roughly <b>{total_cost:.0f}R</b>.", "bad")


def _conviction_section(df: pd.DataFrame, styler) -> None:
    rows = _cat_stats(df, "Conviction (1-5)", min_n=3)
    order = ["1", "2", "3", "4", "5"]
    if rows is not None:
        rows = rows[rows["Category"].isin(order)]
        rows = rows.assign(__o=rows["Category"].map(lambda v: order.index(v) if v in order else 9)).sort_values("__o").drop(columns="__o")
    _line_metric(rows, "Conviction Calibration", styler, value="Avg R", x_order=order,
                 x_title="Conviction (1 = low, 5 = high)",
                 caption="Average R by your 1–5 conviction. A rising line = your read is calibrated.")
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
        rows = _two(rf, "Rules followed", "Rules broken")
        if rows is not None:
            st.markdown("#### Rules Followed vs Broken")
            _tiles(rows); did = True
    if "A+ Setup?" in g.columns:
        ap = g["A+ Setup?"].astype(str).str.strip().str.lower().eq("yes")
        rows = _two(ap, "A+ setup", "Not A+")
        if rows is not None:
            if did:
                st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)
            st.markdown("#### A+ Setups vs The Rest")
            _tiles(rows); did = True
    if not did:
        t._unavailable("Discipline Scorecard")
        return
    both = []
    if "Rules Followed?" in g.columns:
        r = _two(rf, "Rules followed", "Rules broken")
        if r is not None and len(r) == 2:
            both.append(("breaking your rules", float(r.iloc[0]["Avg R"]) - float(r.iloc[1]["Avg R"])))
    if "A+ Setup?" in g.columns:
        r = _two(ap, "A+ setup", "Not A+")
        if r is not None and len(r) == 2:
            both.append(("taking non-A+ setups", float(r.iloc[0]["Avg R"]) - float(r.iloc[1]["Avg R"])))
    worst = max(both, key=lambda x: x[1]) if both else None
    if worst and worst[1] > 0:
        t._insight_box(f"Discipline pays: <b>{worst[1]:+.2f}R</b> per trade is the gap you give up by {worst[0]}.", "warn")


def _direction_section(df: pd.DataFrame, styler) -> None:
    t = _t()
    st.markdown("### Long vs Short")
    st.caption("Expectancy, win rate and net R by trade direction.")
    rows = _cat_stats(df, "Direction")
    if rows is None or len(rows) == 0:
        t._unavailable("Long vs Short"); return
    order = ["Long", "Short"]
    rows = rows.assign(__o=rows["Category"].map(lambda v: order.index(v) if v in order else 9)).sort_values("__o").drop(columns="__o")
    _tiles(rows)


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
    rows = _cat_stats(g, "__cat", min_n=3)
    if rows is not None:
        rows = rows.assign(__o=rows["Category"].map(lambda v: labels.index(v) if v in labels else 9)).sort_values("__o").drop(columns="__o")
    _line_metric(rows, "Hold-Time Window", styler, value="Avg R", x_order=labels,
                 x_title="Hold time",
                 caption="Average R by how long trades were held — find your optimal hold window.")


def _spread_section(df: pd.DataFrame, styler) -> None:
    t = _t()
    spread = _num(df, "Spread at Entry")
    rr = _num(df, "Closed RR")
    if spread is None or rr is None:
        return
    g = df.copy(); g["Spread"] = spread.values; g["R"] = rr.values
    g = g[pd.notna(g["Spread"]) & pd.notna(g["R"])]
    if len(g) < 5 or g["Spread"].nunique() < 2:
        return
    st.markdown("### Spread vs Outcome")
    st.caption("Each dot is a trade: entry spread vs realised R. The purple trend line shows whether "
               "wide spreads (news / Asia) are eating your edge.")
    g["OutcomeC"] = _outcome(g, "R")
    slope, intercept = np.polyfit(g["Spread"].astype(float), g["R"].astype(float), 1)
    xs = [float(g["Spread"].min()), float(g["Spread"].max())]
    reg_vals = [{"Spread": x, "R": float(slope * x + intercept)} for x in xs]
    vals = t._to_alt_values(g[["Spread", "R", "OutcomeC"]])
    s_lo = float(g["Spread"].min()); s_hi = float(g["Spread"].max())
    s_pad = max((s_hi - s_lo) * 0.08, 0.2)
    rule = (alt.Chart(alt.Data(values=[{"y": 0}]))
            .mark_rule(color="#cbd5e1", strokeDash=[4, 4]).encode(y=alt.Y("y:Q", title=None)))
    pts = alt.Chart(alt.Data(values=vals)).mark_circle(size=80, opacity=0.55, stroke="#fff", strokeWidth=1).encode(
        x=alt.X("Spread:Q", title="Spread at entry",
                scale=alt.Scale(domain=[s_lo - s_pad, s_hi + s_pad]),
                axis=alt.Axis(grid=True, gridColor="#eef0f5", labelColor="#94a3b8", titleColor="#94a3b8")),
        y=alt.Y("R:Q", title="Realised R",
                axis=alt.Axis(format="+.0f", grid=True, gridColor="#eef0f5", labelColor="#94a3b8", titleColor="#94a3b8")),
        color=alt.Color("OutcomeC:N", legend=None,
                        scale=alt.Scale(domain=["Win", "BE", "Loss"],
                                        range=["#16a34a", "#9ca3af", "#ef4444"])),
        tooltip=[alt.Tooltip("Spread:Q", title="Spread", format=".1f"),
                 alt.Tooltip("R:Q", title="Realised R", format="+.2f"),
                 alt.Tooltip("OutcomeC:N", title="Outcome")])
    reg = (alt.Chart(alt.Data(values=reg_vals))
           .mark_line(color=PURPLE, strokeWidth=2.5).encode(x="Spread:Q", y="R:Q"))
    st.altair_chart(styler(alt.layer(rule, pts, reg).properties(height=300)), use_container_width=True)
    if slope < -0.05:
        t._insight_box(f"Edge degrades as spread widens (≈<b>{slope:+.2f}R</b> per point of spread). "
                       f"Consider standing down when spreads blow out.", "warn")
    else:
        t._insight_box("No meaningful spread penalty — your edge holds up when spreads widen.", "good")


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
