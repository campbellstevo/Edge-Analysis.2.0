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
        dt = pd.to_datetime(
            df.get("Date", pd.Series(dtype=object)).astype(str)
            .str.replace(r"\s*\(GMT.*\)$", "", regex=True), errors="coerce")
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
    """Floating 'Ask your data' popover, pinned bottom-right by theme CSS."""
    if not chat_enabled():
        return
    hist = st.session_state.setdefault("ea_chat", [])
    used = int(st.session_state.get("ea_chat_used", 0))
    left = max(0, _DAILY_CAP - used)
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
            if left <= 0:
                st.caption("Daily question limit reached — back tomorrow.")
            else:
                with st.form("ea_chat_form", clear_on_submit=True, border=False):
                    q = st.text_input("Question", key="ea_chat_q",
                                      placeholder="Ask about your stats…",
                                      label_visibility="collapsed")
                    sent = st.form_submit_button("Ask", use_container_width=True)
                if sent and q and q.strip():
                    hist.append(("user", q.strip()))
                    with st.spinner("Reading your stats…"):
                        ans = _ask_llm(_stats_context(df), hist)
                    hist.append(("assistant", ans))
                    st.session_state["ea_chat_used"] = used + 1
                    st.rerun()
                st.caption(f"{left} questions left today · answers come from your data, "
                           "not the market · not financial advice")


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
