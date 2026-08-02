"""In-app analyst chat + feedback channel for Edge Analysis.

Chat: floating bubble, answers questions about the trader's own journal stats
via the Anthropic API. Enabled only when ANTHROPIC_API_KEY is in secrets.
Feedback: appends a line to the owner's Notion page. Enabled only when
FEEDBACK_NOTION_TOKEN + FEEDBACK_PAGE_ID are in secrets.
"""
from __future__ import annotations
import os
import html as _h
import pandas as pd
import streamlit as st
import requests

_ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
_DEFAULT_MODEL = "claude-haiku-4-5-20251001"
_DAILY_CAP = 15
_MAX_TURNS = 8  # history turns sent to the model


def _secret(key: str):
    try:
        v = st.secrets.get(key)
        if v:
            return str(v)
    except Exception:
        pass
    return os.environ.get(key) or None


def chat_enabled() -> bool:
    return _secret("ANTHROPIC_API_KEY") is not None


def feedback_enabled() -> bool:
    return (_secret("FEEDBACK_NOTION_TOKEN") is not None
            and _secret("FEEDBACK_PAGE_ID") is not None)


# ─────────────────────────── stats context ───────────────────────────────────
def _rr_series(df: pd.DataFrame):
    col = next((c for c in ["Closed RR Num", "Closed RR", "RR", "Closed R"] if c in df.columns), None)
    if col is None:
        return None
    s = pd.to_numeric(df[col], errors="coerce")
    return s[s.notna()]


def _fmt(v: float) -> str:
    return f"{v:+.2f}R"


def _group_lines(df, rr, col, title, top=6):
    try:
        if col not in df.columns:
            return []
        g = df.loc[rr.index].copy()
        g["__rr"] = rr
        vals = g[col].astype(str).str.strip()
        rows = []
        for name, sub in g.groupby(vals):
            if not name or name.lower() in ("nan", "none", ""):
                continue
            if len(sub) < 3:
                continue
            rows.append((float(sub["__rr"].sum()), name, len(sub),
                         float(sub["__rr"].mean())))
        rows.sort(reverse=True)
        out = [f"{title}:"]
        for net, name, n, avg in rows[:top]:
            out.append(f"  {name}: net {_fmt(net)} over {n} trades (avg {_fmt(avg)})")
        return out if len(out) > 1 else []
    except Exception:
        return []


def _local_dates(df: pd.DataFrame):
    """Date parse matching the dashboard: GMT-suffix strip + trader tz shift."""
    dt = pd.to_datetime(df.get("Date", pd.Series(dtype=object)).astype(str)
                        .str.replace(r"\s*\(GMT.*\)$", "", regex=True), errors="coerce")
    try:
        if getattr(dt.dt, "tz", None) is not None:
            dt = dt.dt.tz_localize(None)
    except Exception:
        pass
    try:
        from edge_analysis.ui.plan_tabs import get_tz_offset
        dt = dt + pd.Timedelta(hours=get_tz_offset(df))
    except Exception:
        pass
    return dt


def _stats_context(df: pd.DataFrame) -> str:
    """Compact, guarded stats block the model answers from."""
    if df is None or df.empty:
        return "No trades in the current view."
    lines = []
    rr = _rr_series(df)
    try:
        if rr is not None and len(rr):
            n = len(rr)
            wins = int((rr > 0.15).sum())
            losses = int((rr < -0.15).sum())
            bes = n - wins - losses
            pf_den = float(-rr[rr < 0].sum())
            pf = float(rr[rr > 0].sum()) / pf_den if pf_den > 0 else float("inf")
            lines.append(
                f"OVERALL: {n} trades, net {_fmt(float(rr.sum()))}, "
                f"{wins}W/{bes}BE/{losses}L (win {wins / n * 100:.0f}%), "
                f"expectancy {_fmt(float(rr.mean()))}, profit factor {pf:.2f}")
    except Exception:
        pass
    try:
        dt = _local_dates(df)
        if rr is not None and dt.notna().any():
            now_p = pd.Timestamp.now().to_period("M")
            m_mask = dt.dt.to_period("M") == now_p
            m_rr = rr[rr.index.isin(dt[m_mask].index)]
            tgt = float(st.session_state.get("ea_m_tgt", 5.0))
            stp = float(st.session_state.get("ea_m_stop", -6.0))
            cap = int(st.session_state.get("ea_m_cap", 12))
            lines.append(
                f"THIS MONTH: net {_fmt(float(m_rr.sum()))} over {len(m_rr)} trades "
                f"(target {tgt:+.1f}R, max loss {stp:+.1f}R, trade cap {cap}). "
                f"Circuit-breaker rule: stop for the month at {stp:+.0f}R.")
    except Exception:
        pass
    if rr is not None:
        for col, title in (("Session Norm", "BY SESSION"), ("Session", "BY SESSION"),
                           ("Entry Model", "BY ENTRY MODEL"), ("DayName", "BY WEEKDAY")):
            got = _group_lines(df, rr, col, title)
            if got:
                lines.extend(got)
                if title == "BY SESSION":
                    break
    try:
        if rr is not None and "A+ Setup?" in df.columns:
            a_mask = df["A+ Setup?"].astype(str).str.strip().str.lower().isin(
                ["yes", "true", "__yes__", "1"])
            a = rr[rr.index.isin(df[a_mask].index)]
            o = rr[rr.index.isin(df[~a_mask].index)]
            if len(a) >= 3:
                lines.append(f"A+ SETUPS: avg {_fmt(float(a.mean()))} over {len(a)} "
                             f"vs non-A+ avg {_fmt(float(o.mean()))} over {len(o)}")
    except Exception:
        pass
    try:
        if rr is not None and "Rules Followed?" in df.columns:
            rv = df["Rules Followed?"].astype(str).str.strip().str.lower()
            kept = rr[rr.index.isin(df[rv.isin(["yes", "true", "__yes__", "1"])].index)]
            broke = rr[rr.index.isin(df[rv.isin(["no", "false", "__no__", "0"])].index)]
            if len(kept) >= 3 and len(broke) >= 3:
                lines.append(f"RULES: kept avg {_fmt(float(kept.mean()))} ({len(kept)}) "
                             f"vs broken avg {_fmt(float(broke.mean()))} ({len(broke)})")
    except Exception:
        pass
    try:
        if rr is not None and "MFE (R)" in df.columns:
            mfe = pd.to_numeric(df["MFE (R)"], errors="coerce")
            give = float((mfe - rr).clip(lower=0).sum())
            if give == give and give > 0:
                lines.append(f"GIVE-BACK: {give:.1f}R of favourable movement not banked (MFE vs close)")
    except Exception:
        pass
    return "\n".join(lines) if lines else "No computable stats in the current view."


# ─────────────────────────── built-in analyst ────────────────────────────────
def _rank_by(df, rr, col, min_n=3):
    if col not in df.columns:
        return []
    g = df.loc[rr.index].copy()
    g["__rr"] = rr
    vals = g[col].astype(str).str.strip()
    rows = []
    for name, sub in g.groupby(vals):
        if not name or name.lower() in ("nan", "none", ""):
            continue
        if len(sub) < min_n:
            continue
        rows.append((float(sub["__rr"].mean()), float(sub["__rr"].sum()), name, len(sub)))
    rows.sort(reverse=True)
    return rows


def _thin(n):
    return " (thin sample — treat gently)" if n < 8 else ""


def _yesmask(df, col):
    v = df[col].astype(str).str.strip().str.lower()
    yes = v.isin(["yes", "true", "__yes__", "1"])
    known = v.isin(["yes", "no", "true", "false", "__yes__", "__no__", "1", "0"])
    return yes, known


def _flag_compare(df, rr, col, label):
    """avg R with vs without a yes/no flag. None when the data can't say."""
    if col not in df.columns:
        return None
    yes, known = _yesmask(df, col)
    a = rr[rr.index.isin(df[yes & known].index)]
    b = rr[rr.index.isin(df[~yes & known].index)]
    if len(a) < 3 or len(b) < 3:
        return f"Not enough {label} tags yet — need 3+ trades on each side."
    gap = float(a.mean()) - float(b.mean())
    lead = "adds" if gap > 0 else "costs"
    return (f"{label}: avg {_fmt(float(a.mean()))} over {len(a)} with it vs "
            f"{_fmt(float(b.mean()))} over {len(b)} without — it {lead} about "
            f"{_fmt(abs(gap))} per trade.{_thin(min(len(a), len(b)))}")


def _clean_cat(series):
    return (series.astype(str).str.replace(r'[\[\]"]', "", regex=True).str.strip())


def _ordered(df, rr):
    dt = _local_dates(df)
    g = pd.DataFrame({"rr": rr, "dt": dt}).dropna()
    return g.sort_values("dt")


def _builtin_answer(q: str, df: pd.DataFrame):
    """Deterministic answers for the common questions. Returns None when unsure."""
    try:
        ql = " " + q.lower().strip() + " "
        rr = _rr_series(df)
        if rr is None or not len(rr):
            return "No completed trades in the current view — adjust the filters and ask again."
        has = lambda *ws: any(w in ql for w in ws)
        sess_col = "Session Norm" if "Session Norm" in df.columns else ("Session" if "Session" in df.columns else None)

        # ── meta ─────────────────────────────────────────────────────────────
        if has("help", "what can you", "what do you answer", "examples"):
            return ("I answer from your own data: sessions · entry models · months & weeks · "
                    "streaks & drawdown · best/worst trades · pace vs target · the breaker · "
                    "rules, A+ and conviction · sweep/divergence/double confirmation · "
                    "conditions, news, gaps, volatility · mistakes & why you lose · "
                    "give-back & TP discipline · timing (hour/day) · dollars · "
                    "\"what's working\" and \"what should I cut\".")

        if has("improving", "getting better", "progress", "better than before", "improved"):
            g = _ordered(df, rr)
            if len(g) < 12:
                return "Fewer than 12 trades — too early to call a trend in your edge."
            half = len(g) // 2
            e1, e2 = float(g["rr"].iloc[:half].mean()), float(g["rr"].iloc[half:].mean())
            verdict = "improving" if e2 > e1 + 0.05 else ("slipping" if e2 < e1 - 0.05 else "holding steady")
            return (f"First {half} trades: expectancy {_fmt(e1)}. Last {len(g) - half}: {_fmt(e2)}. "
                    f"You're {verdict}.{_thin(half)}")

        # ── keep-list / cut-list (before generic words like "working") ───────
        if has("doing well", "doing right", "doing good", "going well", "working",
               "keep doing", "strength", "good at", "best thing", "what works"):
            keeps = []
            if sess_col:
                srows = _rank_by(df, rr, sess_col)
                if srows and srows[0][0] > 0.1:
                    b = srows[0]
                    keeps.append(f"{b[2]} session — avg {_fmt(b[0])} over {b[3]} trades")
            mrows = _rank_by(df, rr, "Entry Model")
            if mrows and mrows[0][0] > 0.1:
                b = mrows[0]
                keeps.append(f"{b[2]} entries — avg {_fmt(b[0])} over {b[3]}")
            if "A+ Setup?" in df.columns:
                yes, _ = _yesmask(df, "A+ Setup?")
                a = rr[rr.index.isin(df[yes].index)]
                if len(a) >= 3 and float(a.mean()) > 0.1:
                    keeps.append(f"your A+ setups — avg {_fmt(float(a.mean()))} over {len(a)}")
            if "Rules Followed?" in df.columns:
                yes, _ = _yesmask(df, "Rules Followed?")
                kept = rr[rr.index.isin(df[yes].index)]
                if len(kept) >= 3 and float(kept.mean()) > 0.1:
                    keeps.append(f"trades where you followed your rules — avg {_fmt(float(kept.mean()))} over {len(kept)}")
            if not keeps:
                return ("Nothing clears +0.10R with a real sample yet — the edge is still forming. "
                        "Keep logging; the Refinements card tracks what's working as it emerges.")
            return (f"What's earning its place: {' · '.join(keeps[:3])}. "
                    "More of THIS, logged and repeated, is the whole plan.")

        if has("remove", "cut ", " drop", "stop doing", "get rid", "eliminate", "leak",
               "holding me back", "holding back", "hold back", "holding my", "stop trading",
               "biggest problem", "number 1", "number one", "worst thing", "biggest issue",
               "what's wrong", "whats wrong", "improve", "fix my", "weakness"):
            cuts = []
            if sess_col:
                srows = _rank_by(df, rr, sess_col)
                if srows and srows[-1][0] < -0.1:
                    w = srows[-1]
                    cuts.append(f"{w[2]} session — avg {_fmt(w[0])} over {w[3]} trades")
            mrows = _rank_by(df, rr, "Entry Model")
            if mrows and mrows[-1][0] < -0.1:
                w = mrows[-1]
                cuts.append(f"{w[2]} entries — avg {_fmt(w[0])} over {w[3]}")
            if "A+ Setup?" in df.columns:
                yes, _ = _yesmask(df, "A+ Setup?")
                o_ = rr[rr.index.isin(df[~yes].index)]
                if len(o_) >= 8 and float(o_.mean()) < -0.1:
                    cuts.append(f"non-A+ trades — avg {_fmt(float(o_.mean()))} over {len(o_)}")
            if "Rules Followed?" in df.columns:
                v = df["Rules Followed?"].astype(str).str.strip().str.lower()
                broke = rr[rr.index.isin(df[v.isin(["no", "false", "__no__", "0"])].index)]
                if len(broke) >= 3 and float(broke.mean()) < -0.1:
                    cuts.append(f"rule-break trades — avg {_fmt(float(broke.mean()))} over {len(broke)}")
            if not cuts:
                return ("Nothing in the data screams 'cut' right now — no session, model or tag "
                        "averages worse than -0.10R with a real sample. The Plan tab keeps the ranking.")
            return (f"By the numbers, the cut list is: {' · '.join(cuts[:3])}. "
                    "One removal at a time — the Plan tab ranks these with full evidence.")

        # ── months / weeks / streaks / drawdown / progress ───────────────────
        if has("best month", "worst month", "monthly", "month by month", "each month"):
            g = _ordered(df, rr)
            m = g.set_index("dt")["rr"].resample("MS").agg(["sum", "count"])
            m = m[m["count"] > 0]
            if len(m) < 2:
                return "Only one month of data so far — the month-by-month story starts next month."
            bi, wi = m["sum"].idxmax(), m["sum"].idxmin()
            return (f"Best month: {bi.strftime('%B %Y')} at {_fmt(float(m.loc[bi, 'sum']))} over "
                    f"{int(m.loc[bi, 'count'])} trades. Worst: {wi.strftime('%B %Y')} at "
                    f"{_fmt(float(m.loc[wi, 'sum']))} over {int(m.loc[wi, 'count'])}. "
                    "The Month-by-month card has every one.")

        if has("best week", "worst week"):
            g = _ordered(df, rr)
            wsr = g.set_index("dt")["rr"].resample("W-SUN").agg(["sum", "count"])
            wsr = wsr[wsr["count"] > 0]
            if len(wsr) < 2:
                return "Not enough weeks yet for a best/worst call."
            bi, wi = wsr["sum"].idxmax(), wsr["sum"].idxmin()
            return (f"Best week: w/c {(bi - pd.Timedelta(days=6)).strftime('%d %b')} at "
                    f"{_fmt(float(wsr.loc[bi, 'sum']))} ({int(wsr.loc[bi, 'count'])} trades). "
                    f"Worst: w/c {(wi - pd.Timedelta(days=6)).strftime('%d %b')} at "
                    f"{_fmt(float(wsr.loc[wi, 'sum']))} ({int(wsr.loc[wi, 'count'])}).")

        if has("this week", "week so far", "current week"):
            g = _ordered(df, rr)
            now = pd.Timestamp.now()
            mon = (now - pd.Timedelta(days=int(now.dayofweek))).normalize()
            wk = g[g["dt"] >= mon]["rr"]
            if not len(wk):
                return "No completed trades yet this week."
            return (f"This week: {_fmt(float(wk.sum()))} over {len(wk)} trades "
                    f"(avg {_fmt(float(wk.mean()))}). The Weekly debrief has the trade-by-trade.")

        if has("streak", "in a row", "consecutive"):
            g = _ordered(df, rr)
            seq = g["rr"].apply(lambda v: 1 if v > 0.15 else (-1 if v < -0.15 else 0)).tolist()
            mw = ml = cw = cl = 0
            for v in seq:
                cw = cw + 1 if v == 1 else 0
                cl = cl + 1 if v == -1 else 0
                mw, ml = max(mw, cw), max(ml, cl)
            cur = 0
            for v in reversed(seq):
                if v == 0:
                    continue
                if cur == 0:
                    cur = v
                elif (v > 0) == (cur > 0):
                    cur += v
                else:
                    break
            cur_s = ("no open streak" if cur == 0 else
                     f"currently {abs(cur)} {'win' if cur > 0 else 'loss'}{'es' if cur < -1 else 's' if cur > 1 else ''} running")
            return (f"Longest winning streak: {mw}. Longest losing streak: {ml} — that's the number "
                    f"your risk plan has to survive. Right now: {cur_s}.")

        if has("drawdown", "draw down", "biggest dip", "underwater"):
            g = _ordered(df, rr)
            cum = g["rr"].cumsum()
            dd = float((cum - cum.cummax()).min())
            return (f"Max drawdown: {_fmt(dd)} peak-to-trough across all logged trades. "
                    f"Your monthly breaker at {float(st.session_state.get('ea_m_stop', -6.0)):+.0f}R "
                    "exists to keep any single month from getting near that.")

        if has("today", "yesterday"):
            g = _ordered(df, rr)
            day = pd.Timestamp.now().normalize() - (pd.Timedelta(days=1) if "yesterday" in ql else pd.Timedelta(0))
            dsub = g[g["dt"].dt.normalize() == day]["rr"]
            label = "Yesterday" if "yesterday" in ql else "Today"
            if not len(dsub):
                return f"{label}: no completed trades logged."
            return f"{label}: {_fmt(float(dsub.sum()))} over {len(dsub)} trade{'s' if len(dsub) != 1 else ''}."

        # ── best/worst single trades ─────────────────────────────────────────
        if has("best trade", "biggest win", "biggest winner", "largest win"):
            g = _ordered(df, rr)
            i = g["rr"].idxmax()
            return (f"Biggest win: {_fmt(float(g.loc[i, 'rr']))} on "
                    f"{g.loc[i, 'dt'].strftime('%d %b %Y')}.")
        if has("worst trade", "biggest loss", "biggest loser", "largest loss"):
            g = _ordered(df, rr)
            i = g["rr"].idxmin()
            return (f"Biggest loss: {_fmt(float(g.loc[i, 'rr']))} on "
                    f"{g.loc[i, 'dt'].strftime('%d %b %Y')}. One number worth checking: "
                    "was the stop where the plan said?")

        # ── pace / breaker (before generic month words) ──────────────────────
        if has("pace", "on track", "this month", "month so far", "target"):
            dt = _local_dates(df)
            m_mask = dt.dt.to_period("M") == pd.Timestamp.now().to_period("M")
            m_rr = rr[rr.index.isin(dt[m_mask].index)]
            tgt = float(st.session_state.get("ea_m_tgt", 5.0))
            stp = float(st.session_state.get("ea_m_stop", -6.0))
            cap = int(st.session_state.get("ea_m_cap", 12))
            net_m = float(m_rr.sum())
            out = (f"This month: {_fmt(net_m)} over {len(m_rr)} trades. Target {tgt:+.1f}R "
                   f"({_fmt(tgt - net_m)} away), stop {stp:+.1f}R ({net_m - stp:.1f}R of room). "
                   f"Trades: {len(m_rr)} of your {cap} cap")
            out += " — over it, pace discipline first." if len(m_rr) > cap else "."
            return out

        if has("breaker", "circuit", "max loss"):
            dt = _local_dates(df)
            m_rr = rr[rr.index.isin(dt[dt.dt.to_period("M") == pd.Timestamp.now().to_period("M")].index)]
            stp = float(st.session_state.get("ea_m_stop", -6.0))
            net_m = float(m_rr.sum())
            if net_m <= stp:
                return (f"Breaker is HIT: {_fmt(net_m)} this month vs the {stp:+.0f}R line. "
                        "The rule is flat until the 1st — no half risk, no exceptions.")
            return (f"Breaker is open: {_fmt(net_m)} this month, {net_m - stp:.1f}R above the "
                    f"{stp:+.0f}R line. It's a binary stop — hit it and the month is done.")

        # ── groups: session / model / weekday / hour / instrument / hold ─────
        if has("session") and sess_col:
            rows = _rank_by(df, rr, sess_col)
            if not rows:
                return "No session has 3+ trades yet — the ranking needs a few more."
            b = rows[0]; w = rows[-1]
            out = (f"Best session: {b[2]} — avg {_fmt(b[0])} over {b[3]} trades"
                   f" (net {_fmt(b[1])}){_thin(b[3])}.")
            if len(rows) > 1 and has("worst", "avoid"):
                return (f"Weakest session: {w[2]} — avg {_fmt(w[0])} over {w[3]} trades"
                        f" (net {_fmt(w[1])}){_thin(w[3])}. {out}")
            if len(rows) > 1:
                out += f" Weakest: {w[2]} at avg {_fmt(w[0])} over {w[3]}."
            return out + " Detail lives on the Entry tab."

        if has("entry model", "which model", "best model", "worst model", "best setup", "worst setup"):
            rows = _rank_by(df, rr, "Entry Model")
            if rows:
                b = rows[0]; w = rows[-1]
                out = f"Best entry model: {b[2]} — avg {_fmt(b[0])} over {b[3]} trades{_thin(b[3])}."
                if len(rows) > 1:
                    out += f" Weakest with 3+ trades: {w[2]} at avg {_fmt(w[0])} over {w[3]}."
                return out + " Full ranking is on the Entry tab."

        if has("weekday", "best day", "worst day", "which day", "day of week",
               "monday", "tuesday", "wednesday", "thursday", "friday"):
            col = "DayName" if "DayName" in df.columns else None
            if col is None and "Date" in df.columns:
                df = df.copy()
                df["__dayname"] = _local_dates(df).dt.day_name()
                col = "__dayname"
            rows = _rank_by(df, rr, col) if col else []
            if rows:
                b = rows[0]; w = rows[-1]
                return (f"Best weekday: {b[2]} — avg {_fmt(b[0])} over {b[3]} trades{_thin(b[3])}. "
                        f"Weakest: {w[2]} at avg {_fmt(w[0])} over {w[3]}.")

        if has("what time", "best time", "which hour", "best hour", "time of day"):
            hcol = next((c for c in ["Hour (Melb)", "Hour"] if c in df.columns), None)
            g = df.copy()
            if hcol is None:
                g["__hr"] = _local_dates(g).dt.hour
                hcol = "__hr"
            g["__hrlab"] = pd.to_numeric(g[hcol], errors="coerce").dropna().astype(int).map(lambda h: f"{h:02d}:00")
            rows = _rank_by(g, rr, "__hrlab")
            if rows:
                b = rows[0]; w = rows[-1]
                return (f"Best hour: {b[2]} — avg {_fmt(b[0])} over {b[3]} trades{_thin(b[3])}. "
                        f"Weakest: {w[2]} at avg {_fmt(w[0])} over {w[3]}. "
                        "The When-You-Trade-Best heatmap on Externals shows the full grid.")

        if has("instrument", "pair", "symbol", "gold", "which market"):
            icol = next((c for c in ["Instrument", "Pair", "Symbol"] if c in df.columns), None)
            if icol:
                rows = _rank_by(df, rr, icol)
                if len(rows) == 1:
                    b = rows[0]
                    return (f"One instrument in the log: {b[2]} — net {_fmt(b[1])} over {b[3]} trades "
                            f"(avg {_fmt(b[0])}).")
                if rows:
                    b = rows[0]; w = rows[-1]
                    return (f"Best instrument: {b[2]} avg {_fmt(b[0])} over {b[3]}. "
                            f"Weakest: {w[2]} avg {_fmt(w[0])} over {w[3]}.")

        if has("hold", "duration", "how long"):
            dcol = next((c for c in ["Duration Bin", "Hold Time", "Duration"] if c in df.columns), None)
            if dcol:
                rows = _rank_by(df, rr, dcol)
                if rows:
                    b = rows[0]
                    return (f"Best hold-time window: {b[2]} — avg {_fmt(b[0])} over {b[3]} trades"
                            f"{_thin(b[3])}. The Hold-Time section on Entry has the curve.")
            return "No hold-time data in this journal yet (the MT5 sync fills it)."

        # ── criteria & conditions ────────────────────────────────────────────
        if has("sweep"):
            r = _flag_compare(df, rr, "Sweep?", "Sweep")
            if r:
                return r
        if has("divergence", " div"):
            r = _flag_compare(df, rr, "DIV?", "Divergence")
            if r:
                return r
        if has("double confirmation", "multi entry", "confluence"):
            r = _flag_compare(df, rr, "Multi Entry Model Setup", "Double confirmation")
            if r:
                return r
        if has("overbought", "oversold", "ob/os", "obos"):
            r = _flag_compare(df, rr, "Oversold or Overbought?", "OB/OS extreme entry")
            if r:
                return r
        if has("conviction"):
            if "Conviction (1-5)" in df.columns:
                cv = pd.to_numeric(df["Conviction (1-5)"], errors="coerce")
                hi = rr[rr.index.isin(df[cv >= 4].index)]
                lo = rr[rr.index.isin(df[cv.notna() & (cv < 4)].index)]
                if len(hi) >= 3 and len(lo) >= 3:
                    return (f"High conviction (4-5): avg {_fmt(float(hi.mean()))} over {len(hi)}. "
                            f"Lower (1-3): avg {_fmt(float(lo.mean()))} over {len(lo)}. "
                            "If the gap is real, conviction deserves a place in your entry checklist.")
                return "Not enough conviction scores logged yet (need 3+ on each side)."
        if has("mental state", "mood", "state of mind", "mindset"):
            if "Mental State" in df.columns:
                ms = df["Mental State"].astype(str)
                clear = rr[rr.index.isin(df[ms.str.contains("Clear", case=False, na=False)].index)]
                other = rr[rr.index.isin(df[~ms.str.contains("Clear", case=False, na=False)
                                            & ~ms.str.strip().isin(["", "nan", "None"])].index)]
                if len(clear) >= 3 and len(other) >= 3:
                    return (f"Clear-headed: avg {_fmt(float(clear.mean()))} over {len(clear)}. "
                            f"Other states: avg {_fmt(float(other.mean()))} over {len(other)}.")
                return "Not enough Mental State tags yet — log it on a few more trades."
            return "No Mental State column in this journal."
        if has("news"):
            rows = _rank_by(pd.DataFrame({"c": _clean_cat(df["News Aspect"])}).join(df.drop(columns=["News Aspect"], errors="ignore")), rr, "c") if "News Aspect" in df.columns else []
            if rows:
                b = rows[0]; w = rows[-1]
                return (f"News: best case is “{b[2]}” at avg {_fmt(b[0])} over {b[3]}; "
                        f"worst is “{w[2]}” at {_fmt(w[0])} over {w[3]}.")
            return "No News Aspect tags with 3+ trades yet."
        if has(" gap", "gaps"):
            rows = _rank_by(pd.DataFrame({"c": _clean_cat(df["GAP Alignment"])}).join(df.drop(columns=["GAP Alignment"], errors="ignore")), rr, "c") if "GAP Alignment" in df.columns else []
            if rows:
                b = rows[0]; w = rows[-1]
                return (f"Gaps: “{b[2]}” leads at avg {_fmt(b[0])} over {b[3]}; "
                        f"“{w[2]}” trails at {_fmt(w[0])} over {w[3]}.")
            return "No GAP Alignment tags with 3+ trades yet."
        if has("volume", "liquidity", "liquid"):
            hr = pd.to_numeric(df.get("Hour (Melb)"), errors="coerce") if "Hour (Melb)" in df.columns else _local_dates(df).dt.hour
            gg = pd.DataFrame({"rr": rr, "hr": hr}).dropna()
            if len(gg) < 8:
                return "Not enough hour-stamped trades to split by volume tier yet."
            def _tier(h):
                h = int(h)
                if h >= 22 or h < 3: return "peak (NY+overlap)"
                if 17 <= h < 22: return "rising (London)"
                if 3 <= h < 7: return "fading (late NY)"
                return "dead (Asia)"
            gg["t"] = gg["hr"].map(_tier)
            bits = []
            for name, sub in gg.groupby("t"):
                if len(sub) >= 3:
                    bits.append((float(sub["rr"].mean()), f"{name}: avg {_fmt(float(sub['rr'].mean()))} over {len(sub)}"))
            if not bits:
                return "No volume window has 3+ trades yet."
            bits.sort(reverse=True)
            return ("Your edge by volume tier \u2014 " + " \u00b7 ".join(b for _, b in bits) +
                    ". The Liquidity Windows bars on Externals keep this live.")
        if has("volatility", "volatile"):
            rows = _rank_by(pd.DataFrame({"c": _clean_cat(df["Volatility"])}).join(df.drop(columns=["Volatility"], errors="ignore")), rr, "c") if "Volatility" in df.columns else []
            if rows:
                b = rows[0]; w = rows[-1]
                return (f"Volatility: {b[2]} conditions average {_fmt(b[0])} over {b[3]}; "
                        f"{w[2]} averages {_fmt(w[0])} over {w[3]}.")
            return "No Volatility tags with 3+ trades yet."
        if has("trending", "ranging", "market condition", "conditions"):
            ccol = next((c for c in ["Conditions ETF", "Conditions MTF", "Conditions HTF"] if c in df.columns), None)
            if ccol:
                rows = _rank_by(pd.DataFrame({"c": _clean_cat(df[ccol])}).join(df.drop(columns=[ccol], errors="ignore")), rr, "c")
                if rows:
                    b = rows[0]; w = rows[-1]
                    return (f"Market conditions ({ccol.split()[-1]} frame): {b[2]} leads at avg {_fmt(b[0])} "
                            f"over {b[3]}; {w[2]} trails at {_fmt(w[0])} over {w[3]}. "
                            "The Conditions bars on Externals rank every state.")
            return "No conditions tags with 3+ trades yet."

        # ── discipline & psychology ──────────────────────────────────────────
        if has("rule", "rules"):
            if "Rules Followed?" in df.columns:
                yes, known = _yesmask(df, "Rules Followed?")
                kept = rr[rr.index.isin(df[yes & known].index)]
                broke = rr[rr.index.isin(df[~yes & known].index)]
                if len(kept) >= 3 and len(broke) >= 3:
                    gap = float(kept.mean()) - float(broke.mean())
                    return (f"Rules kept: avg {_fmt(float(kept.mean()))} over {len(kept)}. "
                            f"Rules broken: avg {_fmt(float(broke.mean()))} over {len(broke)}. "
                            f"Following your own rules is worth about {_fmt(gap)} per trade.")
                return "Not enough Rules Followed? tags yet (need 3+ on each side)."
            return "No Rules Followed? column in this journal."

        if has("a+", "a plus", "a-game", "a game"):
            if "A+ Setup?" in df.columns:
                yes, _ = _yesmask(df, "A+ Setup?")
                a = rr[rr.index.isin(df[yes].index)]
                o_ = rr[rr.index.isin(df[~yes].index)]
                if len(a) >= 3:
                    return (f"A+ setups: avg {_fmt(float(a.mean()))} over {len(a)} trades vs "
                            f"{_fmt(float(o_.mean()))} over {len(o_)} for everything else{_thin(len(a))}. "
                            "The gap is the strongest argument for taking fewer, better trades.")
                return "Fewer than 3 trades tagged A+ so far — tag them in Notion and ask again."
            return "No A+ Setup? column in this journal."

        if has("tilt", "after a loss", "revenge"):
            g = _ordered(df, rr)
            g["__prev"] = g["rr"].shift(1)
            al = g[g["__prev"] < -0.15]["rr"]; aw = g[g["__prev"] > 0.15]["rr"]
            if len(al) >= 3 and len(aw) >= 3:
                return (f"After a loss your next trade averages {_fmt(float(al.mean()))} "
                        f"({len(al)} samples) vs {_fmt(float(aw.mean()))} after a win ({len(aw)}). "
                        + ("Losses are echoing — a forced pause after a red trade would pay. "
                           if float(al.mean()) < float(aw.mean()) - 0.2 else "No strong tilt signal. ")
                        + "Detail: Psychology tab.")

        if has("mistake", "mistakes"):
            if "Mistake" in df.columns:
                mk = _clean_cat(df["Mistake"])
                g2 = df.copy(); g2["__mk"] = mk
                g2 = g2[~g2["__mk"].str.lower().isin(["", "nan", "none", "na"])]
                if len(g2) >= 3:
                    agg = []
                    for name, sub in g2.groupby("__mk"):
                        srr = rr[rr.index.isin(sub.index)]
                        agg.append((float(srr.sum()), name, len(sub)))
                    agg.sort()
                    worst = agg[0]
                    return (f"Most expensive mistake: “{worst[1]}” — net {_fmt(worst[0])} across "
                            f"{worst[2]} trade{'s' if worst[2] != 1 else ''}. "
                            f"{len(agg)} distinct mistake tags logged; the Mistake-leak report ranks them all.")
                return "Fewer than 3 trades have a Mistake tag — log them and this gets sharp."
            return "No Mistake column in this journal."

        if has("why do i lose", "why am i losing", "why i lose", "reason", "losing money"):
            if "Reason of loss" in df.columns:
                why = _clean_cat(df["Reason of loss"])
                g2 = df.copy(); g2["__why"] = why
                g2 = g2[~g2["__why"].str.lower().isin(["", "nan", "none", "na"])]
                losses = rr[rr < -0.15]
                g2 = g2[g2.index.isin(losses.index)]
                if len(g2):
                    agg = []
                    for name, sub in g2.groupby("__why"):
                        srr = rr[rr.index.isin(sub.index)]
                        agg.append((float(srr.sum()), name, len(sub)))
                    agg.sort()
                    top = agg[:2]
                    parts = [f"“{n}” ({_fmt(s)} over {c})" for s, n, c in top]
                    return ("In your own words, the losses come from: " + " and ".join(parts) +
                            ". The Loss Post-Mortem on Psychology has every tag ranked.")
                return "No tagged losses yet — fill Reason of loss on red trades and ask again."
            return "No Reason of loss column in this journal."

        # ── management / money / simple stats ────────────────────────────────
        if has("early close", "close early", "closed early", "take profit", " tp", "set tp", "auto close", "partial"):
            _tc = next((c for c in ["Targeted RR", "Planned R:R", "Planned RR", "RR"]
                        if c in df.columns), None)
            if _tc is None:
                return "No set-target column — the TP comparison needs the target you set per trade."
            tgt = df[_tc].apply(lambda v: pd.to_numeric(str(v).replace("RR", "").replace("R", ""), errors="coerce"))
            gg = pd.DataFrame({"rr": rr, "tgt": tgt}).dropna()
            gg = gg[gg["tgt"] > 0.3]
            if len(gg) < 5:
                return "Fewer than 5 trades with a parseable set target — log the target and ask again."
            hit = gg[gg["rr"] >= gg["tgt"] - 0.1]
            stopped = gg[gg["rr"] <= -0.85]
            early = gg.drop(hit.index).drop(stopped.index)
            return (f"Of {len(gg)} trades with a set TP: {len(hit)} ran to target "
                    f"(avg {_fmt(float(hit['rr'].mean())) if len(hit) else '—'}), "
                    f"{len(early)} closed before it (avg {_fmt(float(early['rr'].mean())) if len(early) else '—'}), "
                    f"{len(stopped)} stopped out. Full breakdown: Entry tab → Manual close vs set TP.")

        if has("give back", "giveback", "gave back", "mfe", "left on the table"):
            if "MFE (R)" in df.columns:
                mfe = pd.to_numeric(df["MFE (R)"], errors="coerce")
                give = float((mfe - rr).clip(lower=0).sum())
                if give == give:
                    return (f"You've shown {give:.1f}R of favourable movement that wasn't banked "
                            "(MFE vs close). A pre-defined +1R action — partial or trail — is the fix. "
                            "Detail: Entry tab, Trade efficiency.")
            return "No MFE (R) column — give-back needs it (the MT5 sync fills it)."

        if has("dollar", "money", "$", "usd", "cash"):
            pcol = next((c for c in ["PnL (USD)", "PnL"] if c in df.columns), None)
            if pcol:
                p = pd.to_numeric(df[pcol], errors="coerce").dropna()
                if len(p):
                    tot = float(p.sum())
                    return (f"Net dollars: {'-' if tot < 0 else '+'}${abs(tot):,.2f} over {len(p)} trades. "
                            "R is the honest measure though — dollar size shifts with lot size.")
            return "No dollar P&L column in this view."

        if has("long", "short", "direction"):
            if "Direction" in df.columns:
                dv = df["Direction"].astype(str).str.strip().str.lower()
                lo = rr[rr.index.isin(df[dv.str.startswith("l")].index)]
                sh = rr[rr.index.isin(df[dv.str.startswith("s")].index)]
                if len(lo) >= 3 and len(sh) >= 3:
                    return (f"Longs: avg {_fmt(float(lo.mean()))} over {len(lo)}. "
                            f"Shorts: avg {_fmt(float(sh.mean()))} over {len(sh)}."
                            f"{_thin(min(len(lo), len(sh)))}")

        if has("average win", "avg win", "average loss", "avg loss", "average winner", "average loser"):
            w_ = rr[rr > 0.15]; l_ = rr[rr < -0.15]
            return (f"Average winner: {_fmt(float(w_.mean())) if len(w_) else '—'} ({len(w_)} wins). "
                    f"Average loser: {_fmt(float(l_.mean())) if len(l_) else '—'} ({len(l_)} losses). "
                    f"That ratio is what lets a {int(len(w_) / max(1, len(w_) + len(l_)) * 100)}% win rate pay.")

        if has("break even", "breakeven", "be rate", "scratch"):
            n = len(rr); bes = int((rr.abs() <= 0.15).sum())
            return (f"Break-evens: {bes} of {n} trades ({bes / n * 100:.0f}%). "
                    "A high BE rate usually means stops moved to entry early — safety that costs the winners.")

        if has("win rate", "winrate", "win %", "how often do i win"):
            n = len(rr); wins = int((rr > 0.15).sum()); bes = int((rr.abs() <= 0.15).sum())
            aw = float(rr[rr > 0.15].mean()) if wins else float("nan")
            return (f"Win rate: {wins / n * 100:.0f}% over {n} completed trades "
                    f"({wins}W / {bes}BE / {n - wins - bes}L). With winners averaging "
                    f"{_fmt(aw) if aw == aw else '—'}, a sub-30% win rate can still be a real edge.")

        if has("profit factor"):
            pf_den = float(-rr[rr < 0].sum())
            pf = float(rr[rr > 0].sum()) / pf_den if pf_den > 0 else float("inf")
            return (f"Profit factor: {pf:.2f} — gross wins ÷ gross losses. "
                    "Above 1 means the wins outweigh the losses; yours is "
                    + ("holding above water." if pf >= 1 else "under 1 — the Plan tab ranks what to cut."))

        if has("expectancy", "edge", "profitable", "net", "total", "how much", "overall", "how am i"):
            n = len(rr)
            pf_den = float(-rr[rr < 0].sum())
            pf = float(rr[rr > 0].sum()) / pf_den if pf_den > 0 else float("inf")
            return (f"Overall: net {_fmt(float(rr.sum()))} over {n} trades, expectancy "
                    f"{_fmt(float(rr.mean()))} per trade, profit factor {pf:.2f}. "
                    + ("The edge is real — protect it with consistent risk." if rr.mean() > 0
                       else "Expectancy is negative in this view — the Plan tab ranks what to cut."))

        if has("how many trades", "trade count", "number of trades"):
            return f"{len(rr)} completed trades in the current view."

        if has("sleep", "recovery", "whoop", "strain"):
            return ("WHOOP questions live on the Psychology tab's Recovery card — the driver "
                    "leaderboard ranks which body metrics actually move your R.")
    except Exception:
        return None
    return None


# ─────────────────────────── model call ──────────────────────────────────────
_SYSTEM = (
    "You are Edge, the built-in analyst of a private trading-journal dashboard. "
    "Answer using ONLY the STATS block below — it is this trader's own logged data. "
    "Be direct and concise (2-6 sentences), quote numbers in R exactly as given. "
    "If the stats don't contain the answer, say so and name the dashboard tab that would "
    "(Performance, Entry, Externals, Psychology, Plan, Review). "
    "Never give trade signals, predictions, position sizes, or financial advice — "
    "you analyse the past; the trader decides the future. Sample sizes under 8 deserve a "
    "reliability caveat.\n\nSTATS:\n{stats}"
)


def _ask_llm(stats: str, history: list) -> str:
    key = _secret("ANTHROPIC_API_KEY")
    model = _secret("ANTHROPIC_MODEL") or _DEFAULT_MODEL
    msgs = [{"role": r, "content": t} for r, t in history[-_MAX_TURNS * 2:]]
    try:
        resp = requests.post(
            _ANTHROPIC_URL,
            headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                     "content-type": "application/json"},
            json={"model": model, "max_tokens": 400,
                  "system": _SYSTEM.format(stats=stats), "messages": msgs},
            timeout=30)
        if resp.status_code != 200:
            return ("The analyst is unavailable right now (service error "
                    f"{resp.status_code}). Try again in a minute.")
        data = resp.json()
        parts = data.get("content") or []
        text = "".join(p.get("text", "") for p in parts if p.get("type") == "text")
        return text.strip() or "No answer came back — try rephrasing."
    except requests.Timeout:
        return "The analyst took too long — try again."
    except Exception:
        return "The analyst is unavailable right now — try again in a minute."


def _llm_allowed() -> bool:
    """Server-side daily cap keyed to the signed-in account, so a refresh
    doesn't reset it. Anonymous/demo sessions get a small session-only cap."""
    try:
        uid = st.session_state.get("user_id")
        if uid:
            from edge_analysis.user_store import bump_llm_use
            return bump_llm_use(str(uid), _DAILY_CAP)
        return int(st.session_state.get("ea_chat_used", 0)) < 5
    except Exception:
        return True


# ─────────────────────────── UI ──────────────────────────────────────────────
def render_chat_bubble(df: pd.DataFrame) -> None:
    """Floating 'Ask your data' popover, pinned bottom-right by theme CSS.

    The built-in analyst answers the common questions for free; when an
    API key is present, unmatched questions upgrade to the LLM."""
    hist = st.session_state.setdefault("ea_chat", [])
    used = int(st.session_state.get("ea_chat_used", 0))
    left = max(0, _DAILY_CAP - used)
    llm_on = chat_enabled()
    with st.container():
        st.markdown('<div class="ea-chatfab"></div>', unsafe_allow_html=True)
        with st.popover("💬 Ask your data"):
            st.markdown('<div class="ea-chat-body"></div>', unsafe_allow_html=True)
            if not hist:
                st.caption("Ask about your own stats — \"what's my best session?\", "
                           "\"am I on pace this month?\", \"what do rules breaks cost me?\"")
            for role, text in hist[-12:]:
                safe = _h.escape(text).replace("\n", "<br>")
                if role == "user":
                    st.markdown(
                        f"<div style='background:#f0ebff;border-radius:12px 12px 2px 12px;"
                        f"padding:9px 13px;margin:4px 0 4px 48px;font-size:13.5px;'>{safe}</div>",
                        unsafe_allow_html=True)
                else:
                    st.markdown(
                        f"<div style='background: rgb(248, 249, 252);border-radius:12px 12px 12px 2px;"
                        f"padding:9px 13px;margin:4px 48px 4px 0;font-size:13.5px;'>{safe}</div>",
                        unsafe_allow_html=True)
            with st.form("ea_chat_form", clear_on_submit=True, border=False):
                q = st.text_input("Question", key="ea_chat_q",
                                  placeholder="Ask about your stats…",
                                  label_visibility="collapsed")
                sent = st.form_submit_button("Ask", use_container_width=True)
            if sent and q and q.strip():
                hist.append(("user", q.strip()))
                ans = _builtin_answer(q, df)
                if ans is None and llm_on and left > 0 and _llm_allowed():
                    with st.spinner("Reading your stats…"):
                        ans = _ask_llm(_stats_context(df), hist)
                    st.session_state["ea_chat_used"] = used + 1
                elif ans is None:
                    ans = ("I didn't catch that one. Try: \"what's my best session?\" · "
                           "\"am I on pace this month?\" · \"what do rule breaks cost me?\" · "
                           "\"long vs short?\" · \"how much have I given back?\"")
                hist.append(("assistant", ans))
                st.rerun()
            _cap_note = (f" · {left} AI questions left today" if llm_on else "")
            st.caption("Answers come from your own data, instantly and privately"
                       + _cap_note + " · not financial advice")


# ─────────────────────────── feedback ────────────────────────────────────────
def send_feedback(text: str) -> bool:
    tok = _secret("FEEDBACK_NOTION_TOKEN")
    pid = _secret("FEEDBACK_PAGE_ID")
    if not (tok and pid and text.strip()):
        return False
    who = str(st.session_state.get("ea_user_email") or "anonymous")
    stamp = pd.Timestamp.now().strftime("%Y-%m-%d %H:%M")
    body = f"[{stamp}] {who}: {text.strip()[:1800]}"
    try:
        r = requests.patch(
            f"https://api.notion.com/v1/blocks/{pid}/children",
            headers={"Authorization": f"Bearer {tok}",
                     "Notion-Version": "2022-06-28",
                     "Content-Type": "application/json"},
            json={"children": [{"object": "block", "type": "paragraph",
                                "paragraph": {"rich_text": [
                                    {"type": "text", "text": {"content": body}}]}}]},
            timeout=15)
        return r.status_code == 200
    except Exception:
        return False


def feedback_body() -> None:
    st.caption("Found a bug, missing a stat, or want a feature? It lands straight "
               "with the builder.")
    txt = st.text_area("Your message", key="ea_fb_text", height=120,
                       label_visibility="collapsed",
                       placeholder="What's broken / what would make this better?")
    if st.button("Send feedback", type="primary", use_container_width=True):
        if txt and txt.strip():
            if send_feedback(txt):
                st.success("Sent — thank you. It's already in the builder's inbox.")
                st.session_state.pop("ea_fb_text", None)
            else:
                st.error("Couldn't send right now — try again in a minute.")
        else:
            st.warning("Write a line first.")
