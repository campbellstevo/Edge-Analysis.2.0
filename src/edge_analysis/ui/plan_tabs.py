"""
Trading Plan Dashboard + Weekly Trading Review — deterministic, live from the
journal. Modeled on Campbell's approved artifact layouts. Helpers from tabs.py
are imported lazily to avoid circular imports.
"""
from __future__ import annotations
import html as _html
import pandas as pd
import streamlit as st

PURPLE = "#4800ff"
GREEN = "#16a34a"
RED = "#ef4444"


def _t():
    from edge_analysis.ui import tabs as _tabs
    return _tabs


def get_tz_offset(df) -> int:
    """Infer the trader's UTC offset from their own journal: the difference
    between their logged local-hour column and the UTC timestamp. Cached per
    session. Falls back to +10 (the template default) when not inferable."""
    if "ea_tz_offset" in st.session_state:
        return st.session_state["ea_tz_offset"]
    off = 10
    try:
        # A date-only journal (Salty's template: the day in "Date", the clock
        # as text) already holds the trader's own calendar day. Comparing its
        # 17:30 entries with a midnight "UTC" read as a -7h offset and slid
        # every trade to the previous day: 1 Sep trades landed in August and
        # the weekly scoreboard showed Tuesday's trades as Monday's.
        if "Date" in df.columns:
            _d = pd.to_datetime(df["Date"], errors="coerce").dropna()
            if len(_d) and bool((_d == _d.dt.normalize()).all()):
                st.session_state["ea_tz_offset"] = 0
                return 0
        hour_col = next((c for c in df.columns if str(c).strip().lower().startswith("hour")), None)
        if hour_col is not None and "Date" in df.columns:
            hrs = pd.to_numeric(df[hour_col], errors="coerce")
            utc = pd.to_datetime(df["Date"], errors="coerce")
            ok = hrs.notna() & utc.notna()
            if int(ok.sum()) >= 3:
                diff = ((hrs[ok] - utc[ok].dt.hour) % 24).round().astype(int)
                m = int(diff.mode().iloc[0])
                off = m - 24 if m > 12 else m
    except Exception:
        pass
    st.session_state["ea_tz_offset"] = off
    return off


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
        if getattr(g["__dt"].dt, "tz", None) is not None:
            g["__dt"] = g["__dt"].dt.tz_localize(None)
        g["__dt"] = g["__dt"] + pd.Timedelta(hours=get_tz_offset(g))
    except Exception:
        pass
    return g


def _avg(s) -> float:
    s = pd.to_numeric(s, errors="coerce").dropna()
    return float(s.mean()) if len(s) else float("nan")


def _fmt_r(v, plus=True) -> str:
    if v != v:
        return "—"
    if abs(v) < 0.005:
        v = 0.0  # kill negative zero at the formatter, for every caller
    return f"{v:+.2f}R" if plus else f"{v:.2f}R"


def _blankish(s: pd.Series) -> pd.Series:
    return s.isna() | s.astype(str).str.strip().str.lower().isin(["", "nan", "none", "[]"])


def _col_contains(g, col, pat):
    """True / False per trade, and <NA> where the tag is blank: an untagged
    trade is neither side of the comparison (26 Sep)."""
    if col not in g.columns:
        return pd.Series(False, index=g.index)
    out = g[col].astype(str).str.contains(pat, case=False, na=False).astype("boolean")
    out[_blankish(g[col])] = pd.NA
    return out


def min_rr_recommendation(g, rr_col="__rr", planned_col="Planned R:R",
                          fallback=3.0, min_n=8):
    """The lowest planned reward-to-risk at which THIS trader actually makes
    money. Buckets trades by the target they aimed for and walks up until a
    bucket earns its keep — so the checklist gate reflects their evidence
    instead of somebody else's rule of thumb.

    Returns (threshold, evidence_string, derived_bool).
    """
    try:
        if planned_col not in g.columns or rr_col not in g.columns:
            return fallback, "", False
        planned = pd.to_numeric(g[planned_col], errors="coerce")
        rr = pd.to_numeric(g[rr_col], errors="coerce")
        ok = planned.notna() & rr.notna()
        if int(ok.sum()) < min_n * 2:
            return fallback, "", False
        best = None
        for thr in (1.5, 2.0, 2.5, 3.0, 3.5, 4.0):
            at_or_above = ok & (planned >= thr)
            below = ok & (planned < thr)
            n_a, n_b = int(at_or_above.sum()), int(below.sum())
            if n_a < min_n or n_b < 3:
                continue
            exp_a = float(rr[at_or_above].mean())
            exp_b = float(rr[below].mean())
            if exp_a > 0 and exp_a - exp_b >= 0.15:
                best = (thr, exp_a, exp_b, n_a, n_b)
                break
        if not best:
            return fallback, "", False
        thr, exp_a, exp_b, n_a, n_b = best
        ev = (f"aiming {thr:g}R+ has earned {exp_a:+.2f}R a trade over {n_a} trades, "
              f"versus {exp_b:+.2f}R when you aimed lower ({n_b} trades)")
        return thr, ev, True
    except Exception:
        return fallback, "", False


def _yes(g, col):
    """Yes / no per trade, <NA> where the tag is blank (see _col_contains)."""
    if col not in g.columns:
        return pd.Series(False, index=g.index)
    out = g[col].astype(str).str.strip().str.lower().isin(["yes", "true", "__yes__", "1"]).astype("boolean")
    out[_blankish(g[col])] = pd.NA
    return out


# ─────────────────────────── Trading Plan Dashboard ──────────────────────────
def plan_model(df_raw: pd.DataFrame):
    """Everything the Plan tab reads, computed once and drawn by whoever needs
    it (the Plan tab; Focus reads the checklist and the ranked edges too).
    None when there are under 10 trades."""
    t = _t()
    g = _prep(df_raw)
    if g is None or len(g) < 10:
        return None
    # No "profitable hours" gate: hours picked by their own average R and then
    # scored on the same trades read as PROVEN on 197 of 200 pure-noise
    # journals (STAT-03), and its fallback was a retired 17:00–02:00 window
    # (COMP-03). Hour evidence lives on Entry → Timing, descriptively.
    # proven instruments: positive expectancy with a real sample
    _sym = g.get("Symbol", g.get("Instrument", pd.Series("", index=g.index))).astype(str)
    _sym_stats = g.assign(__s=_sym).groupby("__s")["__rr"].agg(["mean", "size"])
    _proven = set(_sym_stats[(_sym_stats["size"] >= 5) & (_sym_stats["mean"] > 0)].index)
    on_proven = _sym.isin(_proven) if _proven else pd.Series(True, index=g.index)

    sess = g.get("Session", pd.Series("", index=g.index)).astype(str)
    is_asia = sess.str.contains("Asia", case=False, na=False)
    is_ldn = sess.str.contains("London", case=False, na=False) & ~sess.str.contains("Overlap", case=False, na=False)
    is_ny = sess.str.contains("NY|New York", case=False, na=False)

    # Data-derived gates so the checklist reads any journal, not one playbook:
    # a group "proves" itself with 5+ trades and positive average R. When a
    # journal is too young to prove anything, the row says so — the app ships
    # no rules of its own (COMP-03; the old stand-ins were retired rules).
    def _proven_groups(series, min_n=5):
        _st = g.assign(__k=series.astype(str).str.strip()).groupby("__k")["__rr"].agg(["mean", "size"])
        _st = _st[~_st.index.isin(["", "nan", "None"])]
        return set(_st[(_st["size"] >= min_n) & (_st["mean"] > 0)].index)

    def _names(items, cap=8):  # all of them in practice: "+2" hid the best model
        items = sorted(items)
        return ", ".join(items[:cap]) + (f" +{len(items) - cap}" if len(items) > cap else "")

    _good_sess = _proven_groups(sess)
    if _good_sess:
        ok_sess = sess.str.strip().isin(_good_sess)
        sess_rule = (f"Your proven sessions — {_names(_good_sess)} (from your data)",
                     ok_sess, "proven", "other")
    else:
        sess_rule = ("Your proven sessions", None, "", "")
    _tf_series = g.get("Entry Timeframe", g.get("Timeframe", pd.Series("", index=g.index)))
    _good_tf = _proven_groups(_tf_series)
    if _good_tf:
        tf_rule = (f"Your proven timeframes — {_names(_good_tf)} (from your data)",
                   _tf_series.astype(str).str.strip().isin(_good_tf), "proven TF", "other TF")
    else:
        tf_rule = ("Your proven timeframes", None, "", "")
    _em_series = g.get("Entry Model", pd.Series("", index=g.index))
    _good_em = _proven_groups(_em_series)
    if _good_em:
        model_rule = (f"Your proven entry models — {_names(_good_em)} (from your data)",
                      _em_series.astype(str).str.strip().isin(_good_em), "proven", "other")
    else:
        model_rule = ("Your proven entry models", None, "", "")

    def _has(col):
        # the journal actually logs this column (not merely has it empty)
        return col in g.columns and g[col].map(t._clean_text).ne("").any()

    ok_head = _col_contains(g, "Mental State", "Clear|Good")
    ok_aplus = _yes(g, "A+ Setup?")
    exec_col = g.get("Execution/Bias", pd.Series("", index=g.index)).astype(str)
    ok_exec = exec_col.str.contains("Right", case=False, na=False) & ~exec_col.str.contains("Wrong", case=False, na=False)
    # no multi-entry column = nothing known, not "every trade single"
    ok_single = ~_yes(g, "Multi Entry Model Setup") if _has("Multi Entry Model Setup") else None
    ok_5m = _col_contains(g, "Entry Timeframe", "5")
    ok_model = _col_contains(g, "Entry Model", "Protected|FBOS|FBoS")
    bad_model = _col_contains(g, "Entry Model", "No.Close|No Close")
    ok_break = _yes(g, "True Break?")
    planned = (pd.to_numeric(g["Planned R:R"], errors="coerce")
               if "Planned R:R" in g.columns else pd.Series(float("nan"), index=g.index))
    _min_rr, _min_rr_ev, _min_rr_derived = min_rr_recommendation(g)
    ok_room = planned >= _min_rr
    ok_obos = _yes(g, "Oversold or Overbought?")

    def seg(mask, known=None):
        # both sides only from trades where the tag was answered
        known = pd.Series(True, index=g.index) if known is None else known
        yes, no = mask & known, ~mask & known
        a = _avg(g.loc[yes, "__rr"]); b = _avg(g.loc[no, "__rr"])
        return a, b, int(yes.sum()), int(no.sum())

    # A box shows only when THIS journal logs what it needs. A member on
    # another template saw the owner's playbook (headspace, A+, true break)
    # as nine grey "start tagging this in Notion" rows — someone else's rules.
    gates = [
        ("Headspace is Good", ok_head, "Good", "Okay/Bad",
         _has("Mental State") and bool(ok_head.any())),
        ("It's a genuine A+ setup", ok_aplus, "A+", "non-A+", _has("A+ Setup?")),
        # decision-time field only: "was the bias RIGHT" is knowable after the
        # fact and would make this gate circular
        ("Bias written down, prepared before entry",
         _yes(g, "Clear Bias/Prepared"), "prepared", "unprepared", _has("Clear Bias/Prepared")),
        # (No session gate: which sessions to trade is exactly what the data is
        # still deciding — sessions are reported in the ranked lists below.)
        ("Single entry, structure stop set", ok_single, "single", "multi",
         ok_single is not None),
        ("You followed your own rules", _yes(g, "Rules Followed?"), "followed", "broken",
         _has("Rules Followed?")),
        (*tf_rule, _has("Entry Timeframe") or _has("Timeframe")),
        (*model_rule, _has("Entry Model")),
        ("True break confirmed", ok_break, "confirmed", "No/NA", _has("True Break?")),
        (f"Minimum {_min_rr:g}R of room to target"
         + (" (from your data)" if _min_rr_derived else ""),
         ok_room, f"\u2265{_min_rr:g}R", f"<{_min_rr:g}R", bool(planned.notna().any())),
        ("Stick to your proven instruments", on_proven, "proven", "other", True),
    ]
    gates = [gt[:4] for gt in gates if gt[4]]

    all_pass = pd.Series(True, index=g.index)
    entries = []
    _young = set()
    for rule, mask, lab_y, lab_n in gates:
        if mask is None:  # nothing proven yet for this gate
            _young.add(rule)
            entries.append((rule, float("nan"), False, False, float("nan"), float("nan"),
                            0, 0, lab_y, lab_n))
            continue
        known = mask.notna().astype(bool) if hasattr(mask, "notna") else None
        mask = mask.fillna(False).astype(bool) if hasattr(mask, "fillna") else mask
        a, b, na, nb = seg(mask, known)
        logged = (na + nb) >= 5 and min(na, nb) >= 1
        low = logged and min(na, nb) < 3
        if na >= 3:
            all_pass &= mask
        edge = (a - b) if (logged and a == a and b == b) else float("nan")
        entries.append((rule, edge, logged, low, a, b, na, nb, lab_y, lab_n))

    proven = sorted([e for e in entries if e[1] == e[1] and e[1] >= 0.05 and not e[3]],
                    key=lambda e: -e[1])
    review = [e for e in entries if e not in proven]

    segs = []
    named = [("New York session", is_ny), ("London session", is_ldn), ("Asia session", is_asia),
             ("Right bias + right execution", ok_exec), ("A+ setups", ok_aplus),
             ("Non-A+ setups", ~ok_aplus & g["A+ Setup?"].notna() if "A+ Setup?" in g.columns else None),
             ("Good headspace", ok_head), ("Single entry", ok_single),
             ("Multi-entry", None if ok_single is None else ~ok_single), ("OB/OS extremes", ok_obos),
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
    return dict(g=g, entries=entries, proven=proven, review=review, young=_young,
                all_pass=all_pass, good=good, bad=bad, planned=planned,
                min_rr=_min_rr, min_rr_ev=_min_rr_ev, min_rr_derived=_min_rr_derived)


def render_plan_tab(df_raw: pd.DataFrame, styler) -> None:
    t = _t()
    m = plan_model(df_raw)
    # (the card header already says "Trading plan" — no second title)
    if m is None:
        t._unavailable("Trading Plan")
        return
    g, entries, proven, review, _young = m["g"], m["entries"], m["proven"], m["review"], m["young"]
    all_pass, good, bad, planned = m["all_pass"], m["good"], m["bad"], m["planned"]
    _min_rr, _min_rr_ev, _min_rr_derived = m["min_rr"], m["min_rr_ev"], m["min_rr_derived"]
    n_all = len(g)
    _kinds = (g["Type of Trade"].astype(str) if "Type of Trade" in g.columns
              else pd.Series("", index=g.index))
    _has_live = _kinds.str.contains("Live|Funded", case=False, na=False).any()
    _has_ch = _kinds.str.contains("Challenge|Combine|Evaluation", case=False, na=False).any()
    _which = ("Live + Challenge trades" if _has_live and _has_ch else
              "Live trades" if _has_live else "Challenge trades" if _has_ch else "Executed trades")
    st.caption(f"{_which} only · {n_all} trades · every number below is "
               "recomputed from your journal on each load.")

    st.markdown("#### Pre-trade checklist — every box yes, or pass")
    if _min_rr_derived and _min_rr_ev:
        st.markdown(
            f'<div class="ea-verdict ea-verdict-info">'
            f'<span class="ea-verdict-tick">\u25CF</span>'
            f'<span class="ea-verdict-body"><b>Your minimum target: {_min_rr:g}R</b> '
            f'— {_min_rr_ev}.</span></div>', unsafe_allow_html=True)
    def _row(i, e, faded=False):
        rule, edge, logged, low, a, b, na, nb, lab_y, lab_n = e
        if rule in _young:
            stat = ("<span style='font-size:12px;color:#64748b;'>not enough trades yet — "
                    "one needs 5+ trades at a positive average</span>")
            small = ""
        elif not logged:
            # every row here IS logged (absent columns never reach the list):
            # all trades sit on one side, so there is nothing to compare yet
            _one = (f"every trade so far is {lab_y} — nothing to compare yet" if nb == 0
                    else f"no {lab_y} trades logged yet")
            stat = f"<span style='font-size:12px;color:#64748b;'>{_one}</span>"
            small = ""
        else:
            ec = GREEN if (edge == edge and edge >= 0) else RED
            chip = (f"<span style='background:{ec}1a;color:{ec};font-weight:800;font-size:13px;"
                    f"border-radius:999px;padding:3px 12px;'>edge {edge:+.2f}R</span>"
                    if edge == edge else "")
            lows = (" <span style='font-size:10px;color:#64748b;border:1px solid rgba(148,163,184,0.4);"
                    "border-radius:999px;padding:1px 7px;'>low sample</span>" if low else "")
            stat = chip + lows
            small = (f"<div style='font-size:11px;color:#64748b;margin-top:3px;'>"
                     f"{lab_y} {_fmt_r(a)} ({na}) · {lab_n} {_fmt_r(b)} ({nb})</div>")
        op = "opacity:0.65;" if faded else ""
        num_bg = "#c3c9d4" if faded else PURPLE
        return (
            # wraps on a phone: the rule keeps a readable width and the edge
            # figures drop beneath it instead of squeezing it to ~85px
            f"<div style='display:flex;flex-wrap:wrap;align-items:center;gap:8px 14px;padding:11px 16px;{op}"
            f"border-bottom:1px solid rgba(148,163,184,0.15);'>"
            f"<div style='min-width:26px;height:26px;border-radius:50%;background:{num_bg};"
            f"color:#fff;font-size:13px;font-weight:700;display:flex;align-items:center;"
            f"justify-content:center;'>{i}</div>"
            f"<div style='flex:1 1 220px;min-width:0;font-size:14px;color:#334155;font-weight:600;'>{rule}</div>"
            f"<div style='text-align:right;margin-left:auto;'>{stat}{small}</div></div>"
        )

    rows_html = "".join(_row(i, e) for i, e in enumerate(proven, 1))
    if review:
        rows_html += ("<div style='padding:9px 16px;font-size:11px;font-weight:700;"
                      "letter-spacing:0.08em;color:#64748b;background:#fafbfd;"
                      "border-bottom:1px solid rgba(148,163,184,0.15);'>UNDER REVIEW — "
                      "NO PROVEN EDGE YET</div>")
        rows_html += "".join(_row(i, e, faded=True)
                             for i, e in enumerate(review, len(proven) + 1))
    st.markdown(
        "<div style='background:#fff;border:1px solid rgba(0,0,0,0.06);border-radius:12px;"
        "box-shadow:0 2px 10px rgba(0,0,0,0.04);overflow:hidden;margin:4px 0 10px;'>"
        + rows_html + "</div>", unsafe_allow_html=True)
    _comparable = any(e[2] for e in entries)
    if _comparable:
        t._insight_box("Any box a <b>NO</b> → no trade. The gap between textbook and off-plan "
                       "below is what following this list is worth.", "info")

    # Textbook vs off-plan: what the checklist is worth. (Per-trade expectancy
    # and profit factor live on Performance — not repeated here.)
    n_book, n_off = int(all_pass.sum()), int((~all_pass).sum())
    exp_book = _avg(g.loc[all_pass, "__rr"])
    exp_off = _avg(g.loc[~all_pass, "__rr"])

    def _side(v, n):
        if n < 8:  # no reading from under 8 trades
            return (f"{n} trade{'s' if n != 1 else ''} — too few to read", "#64748b")
        return (_fmt_r(v) + f" · {n} trades", GREEN if (v == v and v >= 0) else RED)

    st.markdown("#### Where you stand")
    if not _comparable:
        # "every box yes: all 120 trades" when no box has a NO side is a
        # tautology, not a reading
        st.caption("Appears once a box has trades on both sides — a YES and a NO to compare.")
    else:
        cards = [("EVERY BOX YES — PER TRADE", *_side(exp_book, n_book)),
                 ("ANY BOX NO — PER TRADE", *_side(exp_off, n_off))]
        st.markdown("<div style='display:flex;gap:12px;flex-wrap:wrap;margin:6px 0 10px;'>" + "".join(
            f"<div style='flex:1;min-width:150px;background:#fff;border:1px solid rgba(0,0,0,0.06);"
            f"border-radius:12px;padding:12px 14px;box-shadow:0 2px 10px rgba(0,0,0,0.04);'>"
            f"<div style='font-size:11px;font-weight:600;letter-spacing:0.06em;color:#64748b;'>{lab}</div>"
            f"<div style='font-size:22px;font-weight:800;color:{col};'>{val}</div></div>"
            for lab, val, col in cards) + "</div>", unsafe_allow_html=True)

    def _ranklist(title, items, ok):
        sym, col = ("✓", GREEN) if ok else ("✕", RED)
        rows = "".join(
            f"<div style='display:flex;justify-content:space-between;gap:10px;padding:9px 16px;"
            f"border-bottom:1px solid rgba(148,163,184,0.15);font-size:13px;'>"
            f"<span style='color:#334155;'><span style='color:{col};font-weight:800;'>{sym}</span>"
            f"  {name} <span style='color:#64748b;'>({n})</span></span>"
            f"<span style='font-weight:800;color:{GREEN if v >= 0 else RED};'>{_fmt_r(v)}</span></div>"
            for name, v, n in items)
        return (f"<div style='flex:1;min-width:280px;background:#fff;border:1px solid rgba(0,0,0,0.06);"
                f"border-radius:12px;box-shadow:0 2px 10px rgba(0,0,0,0.04);overflow:hidden;'>"
                f"<div style='padding:11px 16px;font-size:12px;font-weight:700;letter-spacing:0.08em;"
                f"color:{col};'>{title}</div>{rows}</div>")

    st.markdown("#### The edge, ranked")
    st.markdown("<div style='display:flex;gap:14px;flex-wrap:wrap;margin:4px 0 10px;'>"
                + _ranklist("EARNING R — AVERAGE PER TRADE", good, True)
                + _ranklist("COSTING R — AVERAGE PER TRADE", bad, False)
                + "</div>", unsafe_allow_html=True)

    _rules_section(good, bad)

    if planned is not None and planned.notna().sum() >= 10:
        st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)
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
            if abs(ex) < 0.005:
                ex = 0.0  # never render a red "-0.00R"
            lab = f"{lo}–{hi}RR" if hi < 99 else f"{lo}RR+"
            rws += (f"<tr><td class='text'>{lab}</td><td class='num'>{n}</td>"
                    f"<td class='num'>{wr:.0f}%</td>"
                    f"<td class='num' style='color:{GREEN if ex >= 0 else RED};font-weight:700;'>{_fmt_r(ex)}</td></tr>")
        st.markdown(
            "<div class='table-wrap'><table><thead><tr><th class='text'>Target</th>"
            "<th class='num'>Trades</th><th class='num'>Win %</th><th class='num'>Expectancy</th>"
            f"</tr></thead><tbody>{rws}</tbody></table></div>", unsafe_allow_html=True)




def _rules_js(expr: str, key: str):
    try:
        from streamlit_js_eval import streamlit_js_eval
        return streamlit_js_eval(js_expressions=expr, key=key)
    except Exception:
        return None


def _rules_state() -> dict:
    """Rules live in session, mirrored to this device's browser storage."""
    if "ea_rules" not in st.session_state:
        st.session_state["ea_rules"] = {"custom": [], "accepted": [], "declined": []}
        st.session_state["ea_rules_loaded"] = False
    if not st.session_state.get("ea_rules_loaded"):
        raw = _rules_js("localStorage.getItem('ea_rules') || ''", key="ea_rules_load")
        if raw:
            try:
                import json as _json
                data = _json.loads(raw)
                if isinstance(data, dict):
                    st.session_state["ea_rules"] = {
                        "custom": list(data.get("custom", []))[:30],
                        "accepted": list(data.get("accepted", []))[:30],
                        "declined": list(data.get("declined", []))[:60],
                        "texts": dict(data.get("texts") or {}),
                    }
            except Exception:
                pass
            st.session_state["ea_rules_loaded"] = True
    return st.session_state["ea_rules"]


def _rules_save() -> None:
    import json as _json
    st.session_state["ea_rules_loaded"] = True
    payload = _json.dumps(st.session_state["ea_rules"])
    _rules_js("localStorage.setItem('ea_rules', " + _json.dumps(payload) + ")",
              key=f"ea_rules_save_{abs(hash(payload)) % 100000}")


# A ranked slice becomes a suggested rule only when it is something you
# choose (a session, a setup grade, how you enter) and the evidence is more
# than a handful of trades. "Avoid good headspace" or a 3-trade London edge
# are readings, not rules (his notes, 26 Sep). Pairs that are one rule (A+ vs
# non-A+, single vs multi entry) share a group; the stronger reading speaks.
_REC_RULES = {
    # name: (group, rule when it earns, rule when it costs)
    "A+ setups": ("aplus", "Only take A+ setups", None),
    "Non-A+ setups": ("aplus", None, "Only take A+ setups"),
    "Single entry": ("single", "One entry per idea \u2014 no adding", None),
    "Multi-entry": ("single", None, "One entry per idea \u2014 no adding"),
    "New York session": ("ny", "Trade the New York session", "Skip the New York session"),
    "London session": ("ldn", "Trade the London session", "Skip the London session"),
    "Asia session": ("asia", "Trade the Asia session", "Skip the Asia session"),
    "Right bias + right execution": ("exec", "Only trade when bias and execution line up", None),
    "OB/OS extremes": ("obos", "Wait for an OB/OS extreme", None),
    "True break confirmed": ("break", "Wait for a confirmed break", None),
    "No-Close entries": ("noclose", None, "No entry without a close"),
    "Good headspace": ("head", "Only trade in a good headspace", None),
}
REC_MIN_N = 5
REC_MIN_R = 0.15


def rule_recommendations(good, bad):
    """[(rid, rule, evidence, keep)] — at most one per group, strongest first."""
    best = {}
    for items, keep in ((good, True), (bad, False)):
        for name, v, n in items:
            spec = _REC_RULES.get(name)
            if not spec or n < REC_MIN_N or v != v or abs(v) < REC_MIN_R:
                continue
            group, if_good, if_bad = spec
            rule = if_good if keep else if_bad
            if not rule:
                continue
            ev = f"{'worth' if keep else 'costing'} {_fmt_r(v)} a trade over {n} trades"
            rid = f"{'keep' if keep else 'avoid'}:{name}"
            if group not in best or abs(v) > best[group][4]:
                best[group] = (rid, rule, ev, keep, abs(v))
    return [r[:4] for r in sorted(best.values(), key=lambda r: -r[4])]


def _rules_section(good, bad) -> None:
    t = _t()
    st.markdown("#### My rules")
    st.caption(("Your own rules, plus any you add from the suggestions under them. "
                if t._verdicts_on() else "Your own rules. ") + "Saved on this device.")
    state = _rules_state()
    texts = state.setdefault("texts", {})
    recs = rule_recommendations(good, bad)
    # rules accepted before texts were kept: name them from today's reading
    for rid, rule, _ev, _k in recs:
        if rid in state["accepted"] and rid not in texts:
            texts[rid] = rule

    def _row(icon, tone, title, sub, marker):
        _c = {"keep": GREEN, "avoid": RED, "mine": "#4800ff"}[tone]
        return (f"<div class='ea-row-nowrap ea-rulerow {marker}' style='--c:{_c};'>"
                f"<span class='ea-rulerow-ico'>{icon}</span>"
                f"<span class='ea-rulerow-txt'><b>{_html.escape(title)}</b>"
                + (f"<small>{_html.escape(sub)}</small>" if sub else "")
                + "</span></div>")

    active = [("custom", r, r) for r in state["custom"]] + [
        ("rec", rid, texts.get(rid, rid.split(":", 1)[-1])) for rid in state["accepted"]]
    if active:
        for k, (kind, ident, rule) in enumerate(active):
            c1, c2 = st.columns([12, 1], vertical_alignment="center")
            with c1:
                st.markdown(_row("\u2713", "mine", rule, "", "ea-myrule"), unsafe_allow_html=True)
            with c2:
                if st.button("", key=f"rule_del_{k}", icon=":material/close:", help="Remove this rule"):
                    if kind == "custom":
                        state["custom"].remove(ident)
                    elif ident in state["accepted"]:
                        state["accepted"].remove(ident)
                        state["declined"].append(ident)
                    _rules_save()
                    st.rerun()
    else:
        st.caption("No rules yet \u2014 write your own below"
                   + (" or add a suggestion." if t._verdicts_on() else "."))

    c1, c2 = st.columns([12, 2], vertical_alignment="center")
    with c1:
        st.markdown('<div class="ea-mk ea-row-nowrap"></div>', unsafe_allow_html=True)
        new_rule = st.text_input("Add a rule", key="ea_new_rule",
                                 label_visibility="collapsed",
                                 placeholder="Write your own rule\u2026")
    with c2:
        if st.button("Add", key="ea_add_rule", use_container_width=True):
            if new_rule and new_rule.strip():
                state["custom"].append(new_rule.strip()[:160])
                _rules_save()
                st.rerun()

    # Suggestions come from an uncorrected many-way search that proposes a
    # rule on pure noise (STAT-05): owner-only until each passes its null
    # test (roadmap 1.12, D4). Members keep their own rules.
    pending = [r for r in recs if r[0] not in state["accepted"] and r[0] not in state["declined"]]
    if not t._verdicts_on():
        pending = []
    if pending:
        st.markdown("<div style='font-size:11px;font-weight:700;letter-spacing:0.07em;color:#64748b;"
                    "margin:14px 0 2px;'>SUGGESTED FROM YOUR DATA</div>", unsafe_allow_html=True)
        st.caption(f"Only slices you choose, with {REC_MIN_N}+ trades and at least "
                   f"{REC_MIN_R:.2f}R a trade either way. Add one to make it yours.")
        for rid, rule, ev, keep in pending:
            c1, c2, c3 = st.columns([10, 1.4, 1], vertical_alignment="center")
            with c1:
                st.markdown(_row("\u2713" if keep else "\u2715", "keep" if keep else "avoid",
                                 rule, ev, "ea-rec"), unsafe_allow_html=True)
            with c2:
                if st.button("Add", key=f"rec_ok_{rid}", icon=":material/add:",
                             type="primary", use_container_width=True):
                    state["accepted"].append(rid)
                    texts[rid] = rule
                    _rules_save()
                    st.rerun()
            with c3:
                if st.button("", key=f"rec_no_{rid}", icon=":material/close:",
                             help="Not for me \u2014 hide this suggestion"):
                    state["declined"].append(rid)
                    _rules_save()
                    st.rerun()


# ─────────────────────────── Weekly Trading Review ───────────────────────────
def render_review_tab(df_raw: pd.DataFrame, styler) -> None:
    t = _t()
    g = _prep(df_raw)
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
        return (f"<div style='flex:1;min-width:150px;background: rgb(248, 249, 252);border:1px solid rgba(0,0,0,0.06);"
                f"border-radius:12px;padding:12px 14px;'>"
                f"<div style='font-size:11px;font-weight:600;letter-spacing:0.06em;color:#64748b;'>{lab}</div>"
                f"<div style='font-size:22px;font-weight:800;color:{col};'>{val}</div>"
                f"<div style='font-size:12px;color:#64748b;'>{sub}</div></div>")

    # only the tags this journal uses (a never-filled Conviction made every
    # week read "0 of N fully tagged")
    from edge_analysis.ui.reshape import used_tags
    manual = used_tags(g, ["A+ Setup?", "Conviction (1-5)", "Mental State", "Mistake"])

    def _tagged(row):
        for c in manual:
            _v = row.get(c)
            if isinstance(_v, bool):
                continue  # a checkbox state is a logged value either way
            _s = str(_v if _v is not None else "").strip().lower()
            if c == "Mistake" and _s in ("na", "none", "no mistake"):
                continue  # "NA" is an answer: no mistake on this trade
            if _s in ("", "nan", "none", "na", "[]"):
                return False
        return True

    full_n = int(wk.apply(_tagged, axis=1).sum()) if manual else None
    rules_kept = rules_known = None
    if "Rules Followed?" in wk.columns:
        _rv = wk["Rules Followed?"].astype(str).str.strip().str.lower()
        _kn = _rv.isin(["yes", "no", "true", "false", "__yes__", "__no__", "1", "0"])
        if int(_kn.sum()):
            rules_known = int(_kn.sum())
            rules_kept = int((_rv.isin(["yes", "true", "__yes__", "1"]) & _kn).sum())
    apl = None
    if "A+ Setup?" in wk.columns:
        apl = int(wk["A+ Setup?"].astype(str).str.strip().str.lower()
                  .isin(["yes", "true", "__yes__", "1"]).sum())
    comps = []
    if full_n is not None and n:
        comps.append(full_n / n)
    if rules_known:
        comps.append(rules_kept / rules_known)
    if give == give and (max(net, 0.0) + float(give)) > 0:
        comps.append(max(net, 0.0) / (max(net, 0.0) + float(give)))
    grade = None
    # A process grade reads the tags: a week that is mostly untagged gets
    # none rather than an F for trades nobody has scored yet (26 Sep)
    _tagged_enough = full_n is None or (n and full_n >= n / 2)
    if comps and n >= 3 and _tagged_enough:
        _sc = sum(comps) / len(comps) * 100
        grade = "A" if _sc >= 85 else "B" if _sc >= 70 else "C" if _sc >= 55 else "D" if _sc >= 40 else "F"

    # ── Mockup V7: the week as one report. The conclusion first, four
    # numbers against your own last four weeks, the week day by day, and
    # what to keep and what to fix. Process stays the frame (the grade).
    from edge_analysis.ui import reshape as rx
    _p4 = g[(g["__dt"].dt.to_period("W-SUN") < sel_p) & (g["__dt"].dt.to_period("W-SUN") >= sel_p - 4)]
    _avg4 = float(_p4["__rr"].sum()) / 4 if len(_p4) else None
    _carried = n > 1 and net >= 0 and ex_best < -0.5
    _all_rules = bool(rules_known) and rules_kept == rules_known and rules_known == n
    if n < 3:
        headline = f"A quiet week: {n} trade{'s' if n != 1 else ''}."
    elif _carried:
        headline = "A green week, made by one trade."
    elif net > 0:
        headline = "A green week, and every trade followed your rules." if _all_rules else "A green week."
    elif _all_rules:
        headline = "A red week, but every trade followed your rules."
    else:
        headline = "A red week." if net < 0 else "A flat week."
    _em_col = next((c for c in ("Entry Model", "Entry Model 1") if c in wk.columns), None)
    _best_row = wk.loc[best_i]
    _best_em = t._clean_text(_best_row.get(_em_col)) if _em_col else ""
    if _carried:
        sub = (f"{_best_row['__dt'].strftime('%A')}'s <b>{_fmt_r(float(rr.max()))}</b>"
               + (f" {rx._h.escape(_best_em)}" if _best_em else "")
               + f" carried it. Without it: <b>{_fmt_r(ex_best)}</b>.")
    else:
        sub = f"{n_w} won \u00b7 {n_be} break-even \u00b7 {n_l} lost."
    stats = [("Net", rx.fmt_r(net), (f"last 4 weeks: {rx.fmt_r(_avg4)} a week" if _avg4 is not None else "first weeks logged"),
              GREEN if net >= 0 else RED),
             ("Trades", f"{n}", f"{n_w}W \u00b7 {n_be}BE \u00b7 {n_l}L", "#4800ff")]
    if rules_known:
        stats.append(("Rules followed", f"{rules_kept} of {rules_known}", "by your own tag",
                      GREEN if rules_kept == rules_known else "#b45309"))
    elif full_n is not None:
        stats.append(("Logged in full", f"{full_n} of {n}", "every tag filled", GREEN if full_n == n else "#b45309"))
    if give == give:
        stats.append(("Given back", f"{give:.1f}R", "best price not banked", RED if give > 2 else "#4800ff"))
    _dn = wk.assign(__d=wk["__dt"].dt.day_name())
    _days = []
    for _d in ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]:
        _x = _dn[_dn["__d"] == _d]
        if _d in ("Saturday", "Sunday") and _x.empty:
            continue
        _days.append((_d[:3], float(_x["__rr"].sum()) if len(_x) else None, len(_x)))
    keep = []
    if _em_col and wk[_em_col].notna().any():
        _mm = wk[_em_col].map(t._clean_text)
        _by = wk[_mm != ""].assign(__m=_mm[_mm != ""]).groupby("__m")["__rr"].agg(["sum", "size"])
        if len(_by) and float(_by["sum"].max()) > 0:
            _m = _by["sum"].idxmax()
            _k = int(_by.loc[_m, "size"])
            keep.append(f"<b>{rx._h.escape(str(_m))}</b> made {_fmt_r(float(_by.loc[_m, 'sum']))} "
                        f"over {_k} trade{'s' if _k != 1 else ''}.")
    if _all_rules:
        keep.append(f"Rules followed on all {n} trades.")
    if full_n is not None and full_n == n and n:
        keep.append("Every trade logged in full.")
    if give == give and n_w and give <= 0.5:
        keep.append(f"Exits held: only {give:.1f}R of the best prices given back.")
    fix = []
    if "Mistake" in wk.columns:
        _mk = wk["Mistake"].map(t._clean_text).str.split(r"\s*,\s*").explode().str.strip()
        _mk = _mk[~_mk.str.lower().isin(["", "na", "none", "no mistake"])]
        if len(_mk):
            fix.append(("Mistakes logged", ", ".join(f"{k} \u00d7{v}" for k, v in _mk.value_counts().items())))
    if rules_known and rules_kept < rules_known:
        fix.append((f"Rules broken on {rules_known - rules_kept} of {rules_known}", "by your own tag"))
    if give == give and give > 2 and t._verdicts_on():
        fix.append(("Define the +1R action before entry",
                    f"{give:.1f}R given back vs {_fmt_r(net)} banked \u2014 partial or trail, executed mechanically"))
    if full_n is not None and full_n < n:
        fix.append((f"Backfill the journal \u2014 {n - full_n} of {n} trades not fully tagged",
                    "the discipline score can't see unlogged trades"))
    rx.week_report("", headline, sub, grade if grade else None, stats, _days, keep, fix)
    # the share card: R only, so it is safe to post in the group
    with st.expander("Share this week \u2014 an image for the group, R only"):
        _lines = [f"{round(n_w / n * 100)}% won \u00b7 {n} trade{'s' if n != 1 else ''}"]
        if rules_known:
            _lines.append(f"rules followed {rules_kept} of {rules_known}")
        _lines.append(f"best {rx.fmt_r(float(rr.max()), 1)}" + (f" \u00b7 {_best_em}" if _best_em else ""))
        if grade:
            _lines.append(f"process grade {grade}")
        _png = rx.share_card_png(f"Week of {sel_p.start_time.strftime('%d %b')}", rx.fmt_r(net, 1),
                                 "this week", _lines, list(g["__rr"].cumsum().tail(80)), net >= 0)
        st.image(_png, use_container_width=True)
        st.download_button("Download the image", _png, use_container_width=True, mime="image/png",
                           file_name=f"edge-week-{sel_p.start_time.strftime('%Y-%m-%d')}.png",
                           key="ea_share_week")
        st.caption("Nothing on it but R: no balance, lot size or dollars.")
    if not grade and comps:
        st.caption(f"{n} trade{'s' if n != 1 else ''} \u2014 too few to grade the week's process.")
    st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

    # scoreboard — a column the journal never fills (P&L, MFE, lots on an
    # R-only template) is left out, not shown as a column of dashes
    def _any_num(col):
        return col in wk.columns and pd.to_numeric(wk[col], errors="coerce").notna().any()

    _show_pnl, _show_mfe, _show_lots = _any_num("PnL"), _any_num("MFE (R)"), _any_num("Lot Size")
    _show_pnl = _show_pnl and not t._dollars_hidden()   # not a column of "•••"
    st.markdown("#### Trade by trade")
    rows = ""
    for _, r in wk.iterrows():
        rv = float(r["__rr"])
        res = "Win" if rv > 0.15 else ("Loss" if rv < -0.15 else "BE")
        rescol = GREEN if res == "Win" else (RED if res == "Loss" else "#64748b")
        day = r["__dt"].strftime("%a")
        sess = t._clean_text(r.get("Session"))[:18]
        dirn = t._clean_text(r.get("Direction"))
        pnl = pd.to_numeric(pd.Series([r.get("PnL")]), errors="coerce").iloc[0]
        pnl_s = "—" if pd.isna(pnl) else _t()._money(f"{'-' if pnl < 0 else '+'}${abs(pnl):,.2f}")
        mfe_v = pd.to_numeric(pd.Series([r.get("MFE (R)")]), errors="coerce").iloc[0]
        mfe_s = "—" if pd.isna(mfe_v) else f"+{mfe_v:.2f}R"
        lots = pd.to_numeric(pd.Series([r.get("Lot Size")]), errors="coerce").iloc[0]
        lots_s = "—" if pd.isna(lots) else f"{lots:g}"
        import html as _hh
        extras = ""
        for _tc in ["A+ Setup?", "Conviction (1-5)", "Rules Followed?", "Mistake"]:
            if _tc not in wk.columns:
                continue
            _raw = r.get(_tc)
            if isinstance(_raw, bool):
                _v = "Yes" if _raw else "No"
            else:
                _v = str(_raw if _raw is not None else "").strip()
            if _v.lower() in ("", "nan", "none", "na", "[]"):
                # an untagged field is flagged amber; a blank Mistake is no mistake
                _dc = "#64748b" if _tc == "Mistake" else "#b45309"
                extras += f"<td class='text' style='color:{_dc};'>—</td>"
            else:
                _vl = _v.lower()
                if _tc != "Mistake":
                    _v = "Yes" if _vl in ("yes", "true", "__yes__", "1") else (
                        "No" if _vl in ("no", "false", "__no__", "0") else _v)
                extras += f"<td class='text'>{_hh.escape(_v[:26])}</td>"
        rows += (f"<tr><td class='text'>{day} · {sess}</td><td class='text'>{dirn}</td>"
                 f"<td class='text' style='color:{rescol};font-weight:700;'>{res}</td>"
                 f"<td class='num' style='color:{GREEN if rv >= 0 else RED};font-weight:700;'>{rv:+.2f}</td>"
                 + (f"<td class='num'>{pnl_s}</td>" if _show_pnl else "")
                 + (f"<td class='num'>{mfe_s}</td>" if _show_mfe else "")
                 + (f"<td class='num'>{lots_s}</td>" if _show_lots else "")
                 + extras + "</tr>")
    _tag_ths = "".join(
        f"<th class='text'>{_l}</th>" for _c, _l in (("A+ Setup?", "A+"), ("Conviction (1-5)", "Conv"),
                                                     ("Rules Followed?", "Rules"), ("Mistake", "Mistake"))
        if _c in wk.columns)
    st.markdown(
        "<div class='table-wrap ea-keepcols'><table><thead><tr><th class='text'>Day / Session</th>"
        "<th class='text'>Dir</th><th class='text'>Result</th><th class='num'>R</th>"
        + ("<th class='num'>P&L</th>" if _show_pnl else "")
        + ("<th class='num'>MFE</th>" if _show_mfe else "")
        + ("<th class='num'>Lots</th>" if _show_lots else "")
        + _tag_ths + "</tr></thead>"
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
    # No "Stop trading <session>" fix: one week's session total is one or two
    # trades — it fired on a single stop-out in 37 of 46 demo weeks (STAT-06).
    # The week's sessions are on the scoreboard above.

    # vs last week
    if not pw.empty:
        st.markdown("#### vs last week — process, not profit")
        pr = pw["__rr"]
        pn = len(pw)
        p_full = int(pw.apply(_tagged, axis=1).sum()) if manual else None
        p_rk = p_kn = None
        if "Rules Followed?" in pw.columns:
            _pv = pw["Rules Followed?"].astype(str).str.strip().str.lower()
            _pk = _pv.isin(["yes", "no", "true", "false", "__yes__", "__no__", "1", "0"])
            if int(_pk.sum()):
                p_kn = int(_pk.sum())
                p_rk = int((_pv.isin(["yes", "true", "__yes__", "1"]) & _pk).sum())
        p_mfe = pd.to_numeric(pw["MFE (R)"], errors="coerce") if "MFE (R)" in pw.columns else None
        p_give = float(((p_mfe - pr).clip(lower=0)).sum()) if p_mfe is not None and p_mfe.notna().any() else float("nan")
        _cmp = []
        if full_n is not None and p_full is not None and pn:
            _cmp.append(("Fully logged", f"{p_full} of {pn}", f"{full_n} of {n}",
                         (full_n / max(1, n)) >= (p_full / max(1, pn))))
        if rules_known and p_kn:
            _cmp.append(("Rules followed", f"{round(p_rk / p_kn * 100)}%", f"{round(rules_kept / rules_known * 100)}%",
                         (rules_kept / rules_known) >= (p_rk / p_kn)))
        if give == give and p_give == p_give:
            _cmp.append(("Given back", f"{p_give:.1f}R", f"{give:.1f}R", float(give) <= p_give))
        if not _cmp:
            _cmp.append(("Net R", _fmt_r(float(pr.sum())), _fmt_r(net), net >= float(pr.sum())))
        st.markdown("".join(
            f"<div style='display:flex;gap:18px;align-items:center;padding:5px 0;'>"
            f"<div style='flex:0 1 150px;min-width:0;font-size:13.5px;font-weight:700;color:#0f172a;'>{_l}</div>"
            f"<div style='flex:0 1 140px;min-width:0;font-size:12.5px;color:#64748b;'>last {_a}</div>"
            f"<div style='font-size:13px;font-weight:800;color:{GREEN if _ok else RED};'>now {_b}</div></div>"
            for _l, _a, _b, _ok in _cmp), unsafe_allow_html=True)
        # prescriptive on two weeks of trades — owner only until it passes a
        # null test (1.12); members keep the side-by-side above
        if n > pn and net < float(pr.sum()) and t._verdicts_on():
            t._insight_box("Activity up, edge down — more trades produced less R than last week. "
                           "Fewer, better entries beat more entries.", "warn")
