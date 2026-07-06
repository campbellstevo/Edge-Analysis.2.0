"""
Trading Plan Dashboard + Weekly Trading Review — deterministic, live from the
journal. Modeled on Campbell's approved artifact layouts. Helpers from tabs.py
are imported lazily to avoid circular imports.
"""
from __future__ import annotations
import pandas as pd
import streamlit as st

PURPLE = "#4800ff"
GREEN = "#16a34a"
RED = "#ef4444"


def _t():
    from edge_analysis.ui import tabs as _tabs
    return _tabs


def _prep(df_raw: pd.DataFrame):
    """Live+Challenge trades with Melbourne-calendar dates and numeric R."""
    if df_raw is None or df_raw.empty:
        return None
    g = df_raw.copy()
    if "Type of Trade" in g.columns:
        tot = g["Type of Trade"].astype(str)
        keep = tot.str.contains("Live|Challenge", case=False, na=False) | tot.str.strip().isin(["", "nan", "None", "[]"])
        g = g[keep]
    rr_col = next((c for c in ["Closed RR", "RR", "Closed R"] if c in g.columns), None)
    if rr_col is None:
        return None
    g["__rr"] = pd.to_numeric(g[rr_col], errors="coerce")
    g = g[g["__rr"].notna()]
    if g.empty:
        return None
    g["__dt"] = pd.to_datetime(g.get("Date"), errors="coerce")
    try:
        if getattr(g["__dt"].dt, "tz", None) is None:
            g["__dt"] = (g["__dt"].dt.tz_localize("UTC")
                         .dt.tz_convert("Australia/Melbourne").dt.tz_localize(None))
        else:
            g["__dt"] = g["__dt"].dt.tz_convert("Australia/Melbourne").dt.tz_localize(None)
    except Exception:
        pass
    return g


def _avg(s) -> float:
    s = pd.to_numeric(s, errors="coerce").dropna()
    return float(s.mean()) if len(s) else float("nan")


def _fmt_r(v, plus=True) -> str:
    if v != v:
        return "—"
    return f"{v:+.2f}R" if plus else f"{v:.2f}R"


def _col_contains(g, col, pat):
    if col not in g.columns:
        return pd.Series(False, index=g.index)
    return g[col].astype(str).str.contains(pat, case=False, na=False)


def _yes(g, col):
    if col not in g.columns:
        return pd.Series(False, index=g.index)
    return g[col].astype(str).str.strip().str.lower().isin(["yes", "true", "__yes__", "1"])


# ─────────────────────────── Trading Plan Dashboard ──────────────────────────
def render_plan_tab(df_raw: pd.DataFrame, styler) -> None:
    t = _t()
    g = _prep(df_raw)
    st.markdown("### Trading Plan")
    if g is None or len(g) < 10:
        t._unavailable("Trading Plan")
        return
    n_all = len(g)
    st.caption(f"Live + Challenge trades only · {n_all} trades · every number below is "
               "recomputed from your journal on each load.")

    hr = pd.to_numeric(g.get("Hour (Melb)"), errors="coerce")
    in_window = hr.isin([17, 18, 19, 20, 21, 22, 23, 0, 1, 2]) if hr is not None else pd.Series(False, index=g.index)
    midday = hr.isin([11, 12, 13, 14, 15, 16]) if hr is not None else pd.Series(False, index=g.index)

    sess = g.get("Session", pd.Series("", index=g.index)).astype(str)
    is_asia = sess.str.contains("Asia", case=False, na=False)
    is_ldn = sess.str.contains("London", case=False, na=False) & ~sess.str.contains("Overlap", case=False, na=False)
    is_ny = sess.str.contains("NY|New York", case=False, na=False)

    ok_head = _col_contains(g, "Mental State", "Clear|Good")
    ok_aplus = _yes(g, "A+ Setup?")
    exec_col = g.get("Execution/Bias", pd.Series("", index=g.index)).astype(str)
    ok_exec = exec_col.str.contains("Right", case=False, na=False) & ~exec_col.str.contains("Wrong", case=False, na=False)
    ok_single = ~_yes(g, "Multi Entry Model Setup")
    ok_5m = _col_contains(g, "Entry Timeframe", "5")
    ok_model = _col_contains(g, "Entry Model", "Protected|FBOS|FBoS")
    bad_model = _col_contains(g, "Entry Model", "No.Close|No Close")
    ok_break = _yes(g, "True Break?")
    planned = pd.to_numeric(g.get("Planned R:R"), errors="coerce")
    ok_room = planned >= 3
    ok_obos = _yes(g, "Oversold or Overbought?")

    def seg(mask):
        a = _avg(g.loc[mask, "__rr"]); b = _avg(g.loc[~mask, "__rr"])
        na, nb = int(mask.sum()), int((~mask).sum())
        return a, b, na, nb

    gates = [
        ("Headspace is Good", ok_head, "Good", "Okay/Bad"),
        ("It's a genuine A+ setup", ok_aplus, "A+", "non-A+"),
        ("Bias is clear, entry is textbook", ok_exec, "Right", "off-plan"),
        ("London or New York — never Asia", (is_ldn | is_ny), "LDN/NY", "other"),
        ("Inside your 5 PM–2 AM window", in_window, "in window", "outside"),
        ("Single entry, structure stop set", ok_single, "single", "multi"),
        ("5M entries only", ok_5m, "5M", "other TF"),
        ("Protected Structure or FBoS", ok_model, "PS/FBoS", "other"),
        ("True break confirmed", ok_break, "confirmed", "No/NA"),
        ("Minimum 3R of room to target", ok_room, "≥3R", "<3R"),
    ]

    st.markdown("#### Pre-trade checklist — every box yes, or pass")
    rows_html = ""
    all_pass = pd.Series(True, index=g.index)
    for i, (rule, mask, lab_y, lab_n) in enumerate(gates, 1):
        mask = mask.fillna(False) if hasattr(mask, "fillna") else mask
        a, b, na, nb = seg(mask)
        logged = (na + nb) >= 5 and min(na, nb) >= 1
        low = logged and min(na, nb) < 3
        if na >= 3:
            all_pass &= mask
        if not logged:
            stat = ("<span style='font-size:12px;color:#94a3b8;'>not logged yet — "
                    "start tagging this in Notion</span>")
            small = ""
        else:
            edge = (a - b) if (a == a and b == b) else float("nan")
            ec = GREEN if (edge == edge and edge >= 0) else RED
            chip = (f"<span style='background:{ec}1a;color:{ec};font-weight:800;font-size:13px;"
                    f"border-radius:999px;padding:3px 12px;'>edge {edge:+.2f}R</span>"
                    if edge == edge else "")
            lows = (" <span style='font-size:10px;color:#94a3b8;border:1px solid rgba(148,163,184,0.4);"
                    "border-radius:999px;padding:1px 7px;'>low sample</span>" if low else "")
            stat = chip + lows
            small = (f"<div style='font-size:11px;color:#94a3b8;margin-top:3px;'>"
                     f"{lab_y} {_fmt_r(a)} ({na}) · {lab_n} {_fmt_r(b)} ({nb})</div>")
        rows_html += (
            f"<div style='display:flex;align-items:center;gap:14px;padding:11px 16px;"
            f"border-bottom:1px solid rgba(148,163,184,0.15);'>"
            f"<div style='min-width:26px;height:26px;border-radius:50%;background:{PURPLE};"
            f"color:#fff;font-size:13px;font-weight:700;display:flex;align-items:center;"
            f"justify-content:center;'>{i}</div>"
            f"<div style='flex:1;font-size:14px;color:#334155;font-weight:600;'>{rule}</div>"
            f"<div style='text-align:right;'>{stat}{small}</div></div>"
        )
    st.markdown(
        "<div style='background:#fff;border:1px solid rgba(0,0,0,0.06);border-radius:12px;"
        "box-shadow:0 2px 10px rgba(0,0,0,0.04);overflow:hidden;margin:4px 0 10px;'>"
        + rows_html + "</div>", unsafe_allow_html=True)
    t._insight_box("Any box a <b>NO</b> → no trade. The gap between textbook and off-plan "
                   "below is what following this list is worth.", "info")

    exp_all = _avg(g["__rr"])
    exp_book = _avg(g.loc[all_pass, "__rr"])
    wins = g.loc[g["__rr"] > 0, "__rr"].sum()
    losses = abs(g.loc[g["__rr"] < 0, "__rr"].sum())
    pf = float(wins / losses) if losses else float("nan")
    st.markdown("#### Where you stand")
    cards = [("PER TRADE", _fmt_r(exp_all), "#0f172a"),
             ("WHEN TEXTBOOK", _fmt_r(exp_book) + f" · {int(all_pass.sum())} trades",
              GREEN if (exp_book == exp_book and exp_book >= 0) else RED),
             ("PROFIT FACTOR", "—" if pf != pf else f"{pf:.2f}", PURPLE)]
    st.markdown("<div style='display:flex;gap:12px;flex-wrap:wrap;margin:6px 0 10px;'>" + "".join(
        f"<div style='flex:1;min-width:150px;background:#fff;border:1px solid rgba(0,0,0,0.06);"
        f"border-radius:12px;padding:12px 14px;box-shadow:0 2px 10px rgba(0,0,0,0.04);'>"
        f"<div style='font-size:11px;font-weight:600;letter-spacing:0.06em;color:#94a3b8;'>{lab}</div>"
        f"<div style='font-size:22px;font-weight:800;color:{col};'>{val}</div></div>"
        for lab, val, col in cards) + "</div>", unsafe_allow_html=True)

    segs = []
    named = [("New York session", is_ny), ("London session", is_ldn), ("Asia session", is_asia),
             ("Right bias + right execution", ok_exec), ("A+ setups", ok_aplus),
             ("Non-A+ setups", ~ok_aplus & g["A+ Setup?"].notna() if "A+ Setup?" in g.columns else None),
             ("5 PM–2 AM window", in_window), ("Trading 11 AM–4 PM", midday),
             ("Good headspace", ok_head), ("Single entry", ok_single),
             ("Multi-entry", ~ok_single), ("OB/OS extremes", ok_obos),
             ("True break confirmed", ok_break), ("No-Close entries", bad_model)]
    for name, mask in named:
        if mask is None:
            continue
        mask = mask.fillna(False)
        n = int(mask.sum())
        if n >= 3:
            segs.append((name, _avg(g.loc[mask, "__rr"]), n))
    segs = [s for s in segs if s[1] == s[1]]
    good = sorted([s for s in segs if s[1] > 0.05], key=lambda x: -x[1])[:8]
    bad = sorted([s for s in segs if s[1] < -0.02], key=lambda x: x[1])[:8]

    def _ranklist(title, items, ok):
        sym, col = ("✓", GREEN) if ok else ("✕", RED)
        rows = "".join(
            f"<div style='display:flex;justify-content:space-between;gap:10px;padding:9px 16px;"
            f"border-bottom:1px solid rgba(148,163,184,0.15);font-size:13px;'>"
            f"<span style='color:#334155;'><span style='color:{col};font-weight:800;'>{sym}</span>"
            f"  {name} <span style='color:#94a3b8;'>({n})</span></span>"
            f"<span style='font-weight:800;color:{GREEN if v >= 0 else RED};'>{_fmt_r(v)}</span></div>"
            for name, v, n in items)
        return (f"<div style='flex:1;min-width:280px;background:#fff;border:1px solid rgba(0,0,0,0.06);"
                f"border-radius:12px;box-shadow:0 2px 10px rgba(0,0,0,0.04);overflow:hidden;'>"
                f"<div style='padding:11px 16px;font-size:12px;font-weight:700;letter-spacing:0.08em;"
                f"color:{col};'>{title}</div>{rows}</div>")

    st.markdown("#### The edge, ranked")
    st.markdown("<div style='display:flex;gap:14px;flex-wrap:wrap;margin:4px 0 10px;'>"
                + _ranklist("DO MORE OF — PROVEN EDGE", good, True)
                + _ranklist("STRICT DON'TS — THESE BLEED", bad, False)
                + "</div>", unsafe_allow_html=True)

    if planned is not None and planned.notna().sum() >= 10:
        st.markdown("#### For reference — targeted RR")
        st.caption("Not a rule — win rate and expectancy by the RR you aimed for.")
        bins = [(1, 2), (2, 3), (3, 4), (4, 5), (5, 6), (6, 99)]
        rws = ""
        for lo, hi in bins:
            m = (planned >= lo) & (planned < hi)
            n = int(m.sum())
            if n == 0:
                continue
            sub = g.loc[m, "__rr"]
            wr = float((sub > 0).mean() * 100)
            ex = _avg(sub)
            lab = f"{lo}–{hi}RR" if hi < 99 else f"{lo}RR+"
            rws += (f"<tr><td class='text'>{lab}</td><td class='num'>{n}</td>"
                    f"<td class='num'>{wr:.0f}%</td>"
                    f"<td class='num' style='color:{GREEN if ex >= 0 else RED};font-weight:700;'>{_fmt_r(ex)}</td></tr>")
        st.markdown(
            "<div class='table-wrap'><table><thead><tr><th class='text'>Target</th>"
            "<th class='num'>Trades</th><th class='num'>Win %</th><th class='num'>Expectancy</th>"
            f"</tr></thead><tbody>{rws}</tbody></table></div>", unsafe_allow_html=True)


# ─────────────────────────── Weekly Trading Review ───────────────────────────
def render_review_tab(df_raw: pd.DataFrame, styler) -> None:
    t = _t()
    g = _prep(df_raw)
    st.markdown("### Weekly Review")
    if g is None or g["__dt"].isna().all():
        t._unavailable("Weekly Review")
        return
    g = g[g["__dt"].notna()].sort_values("__dt")
    now = pd.Timestamp.now()
    weeks = sorted(g["__dt"].dt.to_period("W-SUN").unique())
    labels = {p: f"{p.start_time.strftime('%d %b')} – {p.end_time.strftime('%d %b %Y')}" for p in weeks}
    default_p = now.to_period("W-SUN")
    opts = [labels[p] for p in weeks[::-1]]
    sel = st.selectbox("Week", opts, index=0 if labels.get(default_p) not in opts
                       else opts.index(labels[default_p]), label_visibility="collapsed")
    sel_p = next(p for p in weeks if labels[p] == sel)
    wk = g[g["__dt"].dt.to_period("W-SUN") == sel_p]
    prev_p = sel_p - 1
    pw = g[g["__dt"].dt.to_period("W-SUN") == prev_p]

    if wk.empty:
        st.caption("No trades this week.")
        return

    rr = wk["__rr"]
    n = len(wk)
    n_w, n_l = int((rr > 0.15).sum()), int((rr < -0.15).sum())
    n_be = n - n_w - n_l
    net = float(rr.sum())
    usd = pd.to_numeric(wk["PnL"], errors="coerce") if "PnL" in wk.columns else None
    net_usd = float(usd.sum()) if usd is not None and usd.notna().any() else None
    best_i = rr.idxmax()
    ex_best = float(rr.drop(best_i).sum()) if n > 1 else 0.0
    mfe = pd.to_numeric(wk["MFE (R)"], errors="coerce") if "MFE (R)" in wk.columns else None
    give = ((mfe - rr).clip(lower=0)).sum() if mfe is not None and mfe.notna().any() else float("nan")

    def card(lab, val, sub, col):
        return (f"<div style='flex:1;min-width:150px;background:#fff;border:1px solid rgba(0,0,0,0.06);"
                f"border-radius:12px;padding:12px 14px;box-shadow:0 2px 10px rgba(0,0,0,0.04);'>"
                f"<div style='font-size:11px;font-weight:600;letter-spacing:0.06em;color:#94a3b8;'>{lab}</div>"
                f"<div style='font-size:22px;font-weight:800;color:{col};'>{val}</div>"
                f"<div style='font-size:12px;color:#64748b;'>{sub}</div></div>")

    cards = [card("TRADES", f"{n}", f"{n_w}W · {n_be}BE · {n_l}L", "#0f172a"),
             card("NET R", _fmt_r(net), f"ex-best: {_fmt_r(ex_best)}", GREEN if net >= 0 else RED)]
    if net_usd is not None:
        cards.append(card("NET P&L", f"{'-' if net_usd < 0 else '+'}${abs(net_usd):,.2f}",
                          "dollars, from MT5", GREEN if net_usd >= 0 else RED))
    if give == give:
        cards.append(card("R LEFT ON TABLE", f"{give:.2f}R", "MFE given back", RED if give > 2 else "#0f172a"))
    st.markdown("<div style='display:flex;gap:12px;flex-wrap:wrap;margin:6px 0 12px;'>"
                + "".join(cards) + "</div>", unsafe_allow_html=True)

    if n > 1 and net >= 0 and ex_best < -0.5:
        t._insight_box(
            f"<b>One trade wide.</b> Your best trade ({_fmt_r(float(rr.max()))}) carried the week — "
            f"without it you're at <b>{_fmt_r(ex_best)}</b>. Green on paper, thin on process.", "warn")

    # scoreboard
    st.markdown("#### Scoreboard — trade by trade")
    rows = ""
    for _, r in wk.iterrows():
        rv = float(r["__rr"])
        res = "Win" if rv > 0.15 else ("Loss" if rv < -0.15 else "BE")
        rescol = GREEN if res == "Win" else (RED if res == "Loss" else "#94a3b8")
        day = r["__dt"].strftime("%a")
        sess = str(r.get("Session", "") or "")[:18]
        dirn = str(r.get("Direction", "") or "")
        pnl = pd.to_numeric(pd.Series([r.get("PnL")]), errors="coerce").iloc[0]
        pnl_s = "—" if pd.isna(pnl) else f"{'-' if pnl < 0 else '+'}${abs(pnl):,.2f}"
        mfe_v = pd.to_numeric(pd.Series([r.get("MFE (R)")]), errors="coerce").iloc[0]
        mfe_s = "—" if pd.isna(mfe_v) else f"+{mfe_v:.2f}R"
        lots = pd.to_numeric(pd.Series([r.get("Lot Size")]), errors="coerce").iloc[0]
        lots_s = "—" if pd.isna(lots) else f"{lots:g}"
        rows += (f"<tr><td class='text'>{day} · {sess}</td><td class='text'>{dirn}</td>"
                 f"<td class='text' style='color:{rescol};font-weight:700;'>{res}</td>"
                 f"<td class='num' style='color:{GREEN if rv >= 0 else RED};font-weight:700;'>{rv:+.2f}</td>"
                 f"<td class='num'>{pnl_s}</td><td class='num'>{mfe_s}</td><td class='num'>{lots_s}</td></tr>")
    st.markdown(
        "<div class='table-wrap'><table><thead><tr><th class='text'>Day / Session</th>"
        "<th class='text'>Dir</th><th class='text'>Result</th><th class='num'>R</th>"
        "<th class='num'>P&L</th><th class='num'>MFE</th><th class='num'>Lots</th></tr></thead>"
        f"<tbody>{rows}</tbody></table></div>", unsafe_allow_html=True)

    # what worked / didn't
    sess_s = wk.get("Session", pd.Series("", index=wk.index)).astype(str)
    dir_s = wk.get("Direction", pd.Series("", index=wk.index)).astype(str)
    lines = []
    for name, grp in wk.groupby(dir_s):
        if name and str(name) != "nan":
            lines.append(f"{name}s {_fmt_r(float(grp['__rr'].sum()))} over {len(grp)}")
    if lines:
        st.caption("Direction split: " + " · ".join(lines))
    sess_tot = {name: float(grp["__rr"].sum()) for name, grp in wk.groupby(sess_s) if name and str(name) != "nan"}
    if sess_tot:
        best_s = max(sess_tot, key=sess_tot.get)
        worst_s = min(sess_tot, key=sess_tot.get)
        if sess_tot[worst_s] < -0.8:
            t._insight_box(f"<b>{worst_s}</b> cost you <b>{_fmt_r(sess_tot[worst_s])}</b> this week — "
                           f"the week's damage clusters there, while <b>{best_s}</b> paid "
                           f"<b>{_fmt_r(sess_tot[best_s])}</b>.", "bad")

    # management leaks
    if mfe is not None and mfe.notna().any():
        leaks = []
        for _, r in wk.iterrows():
            mv = pd.to_numeric(pd.Series([r.get("MFE (R)")]), errors="coerce").iloc[0]
            if pd.isna(mv):
                continue
            gv = max(0.0, float(mv) - float(r["__rr"]))
            if gv >= 0.5:
                leaks.append((f"{r['__dt'].strftime('%a')} · {str(r.get('Session',''))[:14]}", gv))
        if leaks:
            leaks.sort(key=lambda x: -x[1])
            st.markdown("#### Management leaks — MFE vs closed R")
            st.markdown("<div style='display:flex;gap:10px;flex-wrap:wrap;margin:4px 0 8px;'>" + "".join(
                f"<div style='background:#fff;border:1px solid rgba(0,0,0,0.06);border-radius:10px;"
                f"padding:9px 14px;box-shadow:0 2px 8px rgba(0,0,0,0.03);font-size:13px;'>"
                f"<span style='color:#64748b;'>{lab}</span> "
                f"<span style='color:{RED};font-weight:800;'>gave back {gv:.2f}R</span></div>"
                for lab, gv in leaks[:6]) + "</div>", unsafe_allow_html=True)
            if give == give and net == net:
                t._insight_box(
                    f"Combined <b>{give:.2f}R</b> left on the table vs <b>{_fmt_r(net)}</b> banked. "
                    "Define the +1R action (partial or trail) before entry and execute it mechanically.",
                    "warn")

    # discipline: blank manual fields
    manual = [c for c in ["A+ Setup?", "Conviction (1-5)", "Mental State", "Mistake"] if c in wk.columns]
    if manual:
        blank = 0
        for _, r in wk.iterrows():
            if all(str(r.get(c, "") or "").strip().lower() in ("", "nan", "none", "na") for c in manual):
                blank += 1
        if blank:
            t._insight_box(
                f"<b>{blank} of {n}</b> trades this week have blank manual fields (A+, Conviction, "
                "Mental State, Mistake) — the discipline sections can't score what isn't logged. "
                "Backfill them in Notion while the trades are fresh.", "warn")

    # vs last week
    if not pw.empty:
        st.markdown("#### vs last week")
        pr = pw["__rr"]
        pn = len(pw)
        c1 = card("LAST WEEK", _fmt_r(float(pr.sum())), f"{pn} trades", GREEN if pr.sum() >= 0 else RED)
        c2 = card("THIS WEEK", _fmt_r(net), f"{n} trades", GREEN if net >= 0 else RED)
        st.markdown(f"<div style='display:flex;gap:12px;flex-wrap:wrap;'>{c1}{c2}</div>",
                    unsafe_allow_html=True)
        if n > pn and net < float(pr.sum()):
            t._insight_box("Activity up, edge down — more trades produced less R than last week. "
                           "Fewer, better entries beat more entries.", "warn")
