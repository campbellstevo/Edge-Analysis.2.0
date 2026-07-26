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
    col = next((c for c in ["Closed RR", "RR", "Closed R"] if c in df.columns), None)
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


def _builtin_answer(q: str, df: pd.DataFrame):
    """Deterministic answers for the common questions. Returns None when unsure."""
    try:
        ql = " " + q.lower().strip() + " "
        rr = _rr_series(df)
        if rr is None or not len(rr):
            return "No completed trades in the current view — adjust the filters and ask again."
        has = lambda *ws: any(w in ql for w in ws)
        sess_col = "Session Norm" if "Session Norm" in df.columns else ("Session" if "Session" in df.columns else None)

        if has("help", "what can you", "what do you", "examples"):
            return ("Try: \"what's my best session?\" · \"am I on pace this month?\" · "
                    "\"what do rule breaks cost me?\" · \"best entry model?\" · "
                    "\"long vs short?\" · \"how much have I given back?\"")

        if has("session") and sess_col:
            rows = _rank_by(df, rr, sess_col)
            if not rows:
                return "No session has 3+ trades yet — the ranking needs a few more."
            b = rows[0]; w = rows[-1]
            out = (f"Best session: {b[2]} — avg {_fmt(b[0])} over {b[3]} trades"
                   f" (net {_fmt(b[1])}){_thin(b[3])}.")
            if len(rows) > 1 and has("worst", "avoid", "stop"):
                return (f"Weakest session: {w[2]} — avg {_fmt(w[0])} over {w[3]} trades"
                        f" (net {_fmt(w[1])}){_thin(w[3])}. {out}")
            if len(rows) > 1:
                out += f" Weakest: {w[2]} at avg {_fmt(w[0])} over {w[3]}."
            return out + " Detail lives on the Entry tab."

        if has("entry model", "model", "setup") and not has("a+", "a plus"):
            rows = _rank_by(df, rr, "Entry Model")
            if rows:
                b = rows[0]; w = rows[-1]
                out = f"Best entry model: {b[2]} — avg {_fmt(b[0])} over {b[3]} trades{_thin(b[3])}."
                if len(rows) > 1:
                    out += f" Weakest with 3+ trades: {w[2]} at avg {_fmt(w[0])} over {w[3]}."
                return out + " Full ranking is on the Entry tab."

        if has("a+", "a plus", "a-game", "a game"):
            if "A+ Setup?" in df.columns:
                m = df["A+ Setup?"].astype(str).str.strip().str.lower().isin(["yes", "true", "__yes__", "1"])
                a = rr[rr.index.isin(df[m].index)]; o_ = rr[rr.index.isin(df[~m].index)]
                if len(a) >= 3:
                    return (f"A+ setups: avg {_fmt(float(a.mean()))} over {len(a)} trades vs "
                            f"{_fmt(float(o_.mean()))} over {len(o_)} for everything else{_thin(len(a))}. "
                            "The gap is the strongest argument for taking fewer, better trades.")
                return "Fewer than 3 trades tagged A+ so far — tag them in Notion and ask again."
            return "No A+ Setup? column in this journal."

        if has("rule", "rules"):
            if "Rules Followed?" in df.columns:
                rv = df["Rules Followed?"].astype(str).str.strip().str.lower()
                kept = rr[rr.index.isin(df[rv.isin(["yes", "true", "__yes__", "1"])].index)]
                broke = rr[rr.index.isin(df[rv.isin(["no", "false", "__no__", "0"])].index)]
                if len(kept) >= 3 and len(broke) >= 3:
                    gap = float(kept.mean()) - float(broke.mean())
                    return (f"Rules kept: avg {_fmt(float(kept.mean()))} over {len(kept)}. "
                            f"Rules broken: avg {_fmt(float(broke.mean()))} over {len(broke)}. "
                            f"Following your own rules is worth about {_fmt(gap)} per trade.")
                return "Not enough Rules Followed? tags yet (need 3+ on each side)."
            return "No Rules Followed? column in this journal."

        if has("pace", "on track", "this month", "month so far", "target"):
            dt = _local_dates(df)
            m_mask = dt.dt.to_period("M") == pd.Timestamp.now().to_period("M")
            m_rr = rr[rr.index.isin(dt[m_mask].index)]
            tgt = float(st.session_state.get("ea_m_tgt", 5.0))
            stp = float(st.session_state.get("ea_m_stop", -6.0))
            cap = int(st.session_state.get("ea_m_cap", 12))
            net_m = float(m_rr.sum())
            room = net_m - stp
            out = (f"This month: {_fmt(net_m)} over {len(m_rr)} trades. Target {tgt:+.1f}R "
                   f"({_fmt(tgt - net_m)} away), stop {stp:+.1f}R ({room:.1f}R of room). "
                   f"Trades: {len(m_rr)} of your {cap} cap")
            out += " — over it, pace discipline first." if len(m_rr) > cap else "."
            return out

        if has("breaker", "circuit", "stop trading", "max loss"):
            dt = _local_dates(df)
            m_rr = rr[rr.index.isin(dt[dt.dt.to_period("M") == pd.Timestamp.now().to_period("M")].index)]
            stp = float(st.session_state.get("ea_m_stop", -6.0))
            net_m = float(m_rr.sum())
            if net_m <= stp:
                return (f"Breaker is HIT: {_fmt(net_m)} this month vs the {stp:+.0f}R line. "
                        "The rule is flat until the 1st — no half risk, no exceptions.")
            return (f"Breaker is open: {_fmt(net_m)} this month, {net_m - stp:.1f}R above the "
                    f"{stp:+.0f}R line. It's a binary stop — hit it and the month is done.")

        if has("day", "weekday", "monday", "tuesday", "wednesday", "thursday", "friday"):
            col = "DayName" if "DayName" in df.columns else None
            if col is None and "Date" in df.columns:
                df = df.copy()
                df["__dayname"] = pd.to_datetime(df["Date"].astype(str).str.replace(
                    r"\s*\(GMT.*\)$", "", regex=True), errors="coerce").dt.day_name()
                col = "__dayname"
            rows = _rank_by(df, rr, col) if col else []
            if rows:
                b = rows[0]; w = rows[-1]
                return (f"Best weekday: {b[2]} — avg {_fmt(b[0])} over {b[3]} trades{_thin(b[3])}. "
                        f"Weakest: {w[2]} at avg {_fmt(w[0])} over {w[3]}.")

        if has("give back", "giveback", "gave back", "mfe", "left on the table", "partial"):
            if "MFE (R)" in df.columns:
                mfe = pd.to_numeric(df["MFE (R)"], errors="coerce")
                give = float((mfe - rr).clip(lower=0).sum())
                if give == give:
                    return (f"You've shown {give:.1f}R of favourable movement that wasn't banked "
                            "(MFE vs close). A pre-defined +1R action — partial or trail — is the fix. "
                            "Detail: Entry tab, Trade efficiency.")
            return "No MFE (R) column — give-back needs it (MT5 sync fills it)."

        if has("tilt", "after a loss", "revenge"):
            dcol = _local_dates(df)
            g = df.loc[rr.index].copy(); g["__rr"] = rr; g["__dt"] = dcol
            g = g[g["__dt"].notna()].sort_values("__dt")
            g["__prev_rr"] = g["__rr"].shift(1)
            al = g[g["__prev_rr"] < -0.15]["__rr"]; aw = g[g["__prev_rr"] > 0.15]["__rr"]
            if len(al) >= 3 and len(aw) >= 3:
                return (f"After a loss your next trade averages {_fmt(float(al.mean()))} "
                        f"({len(al)} samples) vs {_fmt(float(aw.mean()))} after a win ({len(aw)}). "
                        + ("Losses are echoing — a forced pause after a red trade would pay. "
                           if float(al.mean()) < float(aw.mean()) - 0.2 else "No strong tilt signal. ")
                        + "Detail: Psychology tab.")

        if has("long", "short", "direction"):
            if "Direction" in df.columns:
                dv = df["Direction"].astype(str).str.strip().str.lower()
                lo = rr[rr.index.isin(df[dv.str.startswith("l")].index)]
                sh = rr[rr.index.isin(df[dv.str.startswith("s")].index)]
                if len(lo) >= 3 and len(sh) >= 3:
                    return (f"Longs: avg {_fmt(float(lo.mean()))} over {len(lo)}. "
                            f"Shorts: avg {_fmt(float(sh.mean()))} over {len(sh)}."
                            f"{_thin(min(len(lo), len(sh)))}")

        if has("win rate", "winrate", "win %"):
            n = len(rr); wins = int((rr > 0.15).sum()); bes = int((rr.abs() <= 0.15).sum())
            return (f"Win rate: {wins / n * 100:.0f}% over {n} completed trades "
                    f"({wins}W / {bes}BE / {n - wins - bes}L). With your winners averaging "
                    f"{_fmt(float(rr[rr > 0.15].mean())) if wins else '—'}, a sub-30% win rate can still be a real edge.")

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
                if ans is None and llm_on and left > 0:
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
