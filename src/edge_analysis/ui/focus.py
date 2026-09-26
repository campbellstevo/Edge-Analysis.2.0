"""Focus: a briefing for the moment before a session, not a smaller dashboard.

His note (26 Sep): "with the focus mode as well, we need to make a better plan
for that and execute that a bit better." Focus answers four questions, top to
bottom, on one screen:

1. Right now — can I trade? The month against its stop and target, this
   week so far, the last trade. Same numbers as the circuit breaker and the
   month card (the main account only; rule 8).
2. Before you take a trade — the checklist items that have proven an edge
   in this journal, then the rules he wrote or added himself.
3. Lean into / stay away from — the strongest things he chooses (sessions,
   setup grade, how he enters), with the same noise floor as Plan.
4. After your last trade — how his next trade has gone after a result like it.

Every number is plain counting from the journal; nothing is a forecast.
"""
from __future__ import annotations

import html as _h

import pandas as pd
import streamlit as st
from edge_analysis.core.clock import local_now

from edge_analysis.ui import reshape as rx
from edge_analysis.ui.reshape import GREEN, RED, PURPLE, fmt_r

AMBER = "#b45309"


# ----------------------------- numbers ----------------------------------------

def dated(df: pd.DataFrame) -> pd.DataFrame | None:
    """__dt (the journal's clock, like the breaker) and __rr, oldest first."""
    if df is None or df.empty or "Date" not in df.columns:
        return None
    g = df.copy()
    g["__dt"] = pd.to_datetime(g["Date"], errors="coerce")
    try:
        from edge_analysis.ui.plan_tabs import get_tz_offset
        if getattr(g["__dt"].dt, "tz", None) is not None:
            g["__dt"] = g["__dt"].dt.tz_localize(None)
        g["__dt"] = g["__dt"] + pd.Timedelta(hours=get_tz_offset(g))
    except Exception:
        pass
    rr_col = next((c for c in ["Closed RR Num", "Closed RR", "RR", "Closed R"] if c in g.columns), None)
    if rr_col is None:
        return None
    g["__rr"] = pd.to_numeric(g[rr_col], errors="coerce")
    g = g[g["__dt"].notna() & g["__rr"].notna()].sort_values("__dt")
    return g if not g.empty else None


def right_now(g: pd.DataFrame, tgt: float, stop: float, now: pd.Timestamp | None = None) -> dict:
    """The month against its lines, this week, the last trade, and a state:
    stop (breaker hit), careful (under 2R above it), target, or clear."""
    now = now or local_now()
    month = g[g["__dt"].dt.to_period("M") == now.to_period("M")]
    week = g[g["__dt"].dt.to_period("W-SUN") == now.to_period("W-SUN")]
    mtd = float(month["__rr"].sum()) if not month.empty else 0.0
    room = mtd - stop
    if mtd <= stop:
        state = "stop"
    elif room < 2:
        state = "careful"
    elif mtd >= tgt:
        state = "target"
    else:
        state = "clear"
    last = g.iloc[-1] if len(g) else None
    return dict(state=state, mtd=mtd, room=room, tgt=tgt, stop=stop, n_month=len(month),
                week_r=float(week["__rr"].sum()) if not week.empty else 0.0, n_week=len(week),
                path=list(month["__rr"].cumsum()), last=last, month_name=now.strftime("%B"))


def _res(r: float) -> str:
    return "win" if r > 0.15 else ("loss" if r < -0.15 else "be")


def after_last(g: pd.DataFrame, min_n: int = 5) -> dict | None:
    """The streak the last trade is on, and how the next trade has gone after
    the same streak before (and after a win, for comparison)."""
    if g is None or len(g) < 2:
        return None
    res = [_res(r) for r in g["__rr"]]
    rr = list(g["__rr"])
    kind = res[-1]
    streak = 1
    for x in reversed(res[:-1]):
        if x != kind:
            break
        streak += 1
    k = min(streak, 2)          # "after a loss" and "after two or more in a row"

    def _after(pattern_kind, run):
        nxt = [rr[i + 1] for i in range(run - 1, len(res) - 1)
               if all(res[i - j] == pattern_kind for j in range(run))]
        return (sum(nxt) / len(nxt), len(nxt)) if nxt else (None, 0)

    same_avg, same_n = _after(kind, k)
    win_avg, win_n = _after("win", 1)
    return dict(kind=kind, streak=streak, run=k, last_r=rr[-1], last_dt=g["__dt"].iloc[-1],
                same_avg=same_avg if same_n >= min_n else None, same_n=same_n,
                win_avg=win_avg if win_n >= min_n else None, win_n=win_n)


# ----------------------------- drawing ----------------------------------------

def _spark(path: list, tgt: float, stop: float, t: dict) -> str:
    """The month so far as a line between its stop and target."""
    w, h, pad = 260, 64, 6
    pts = [0.0] + [float(v) for v in path]
    lo, hi = min(min(pts), stop), max(max(pts), tgt)
    span = (hi - lo) or 1.0

    def y(v):
        return pad + (hi - v) / span * (h - 2 * pad)
    n = max(1, len(pts) - 1)
    line = " ".join(f"{pad + i / n * (w - 2 * pad):.1f},{y(v):.1f}" for i, v in enumerate(pts))
    return (f'<svg viewBox="0 0 {w} {h}" width="100%" height="{h}" preserveAspectRatio="none" '
            f'role="img" aria-label="This month so far">'
            f'<line x1="0" x2="{w}" y1="{y(tgt):.1f}" y2="{y(tgt):.1f}" stroke="{GREEN}" stroke-dasharray="4 4" stroke-width="1.2"/>'
            f'<line x1="0" x2="{w}" y1="{y(stop):.1f}" y2="{y(stop):.1f}" stroke="{RED}" stroke-dasharray="4 4" stroke-width="1.2"/>'
            f'<line x1="0" x2="{w}" y1="{y(0):.1f}" y2="{y(0):.1f}" stroke="{t["zero"]}" stroke-width="1"/>'
            f'<polyline points="{line}" fill="none" stroke="{PURPLE if not rx._dark() else "#a78bfa"}" stroke-width="2.2" '
            f'stroke-linejoin="round" stroke-linecap="round" vector-effect="non-scaling-stroke"/></svg>')


_CSS = """
.ea-fo{{display:flex;flex-direction:column;gap:14px;}}
.ea-fo-head{{display:flex;align-items:center;gap:12px;padding:12px 16px;border-radius:12px;
  background:{bg};border:1px solid {bc};}}
.ea-fo-dot{{flex:none;width:34px;height:34px;border-radius:50%;display:flex;align-items:center;justify-content:center;
  font-size:17px;font-weight:800;color:#fff;background:{c};}}
.ea-fo-head b{{display:block;font-size:17px;color:{c};}}
.ea-fo-head span{{display:block;font-size:13px;color:{muted};}}
.ea-fo-grid{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;}}
.ea-fo-k{{background:{soft};border:1px solid {line};border-radius:10px;padding:10px 12px;min-width:0;}}
.ea-fo-k .l{{font-size:10.5px;font-weight:700;letter-spacing:.07em;color:{muted};text-transform:uppercase;}}
.ea-fo-k .v{{font-size:20px;font-weight:800;line-height:1.25;}}
.ea-fo-k .s{{font-size:12px;color:{muted};white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}}
.ea-fo-spark{{display:flex;align-items:center;gap:12px;}}
.ea-fo-spark .lg{{font-size:11.5px;color:{muted};line-height:1.6;white-space:nowrap;}}
.ea-fo-list{{display:flex;flex-direction:column;gap:6px;}}
.ea-fo-i{{display:flex;align-items:center;gap:10px;padding:8px 12px;border:1px solid {line};border-radius:10px;background:{base};}}
.ea-fo-i .n{{flex:none;width:22px;height:22px;border-radius:6px;border:2px solid {zero};}}
.ea-fo-i .t{{flex:1;min-width:0;font-size:14px;font-weight:600;color:{ink};}}
.ea-fo-i .e{{flex:none;font-size:12px;font-weight:800;border-radius:999px;padding:2px 9px;}}
.ea-fo-sub{{font-size:11px;font-weight:700;letter-spacing:.07em;color:{muted};margin:4px 0 0;}}
.ea-fo-two{{display:grid;grid-template-columns:1fr 1fr;gap:12px;}}
.ea-fo-col{{border:1px solid {line};border-radius:12px;padding:12px 14px;background:{base};}}
.ea-fo-col .h{{margin:0 0 6px;font-size:12px;font-weight:800;letter-spacing:.07em;}}
.ea-fo-col p{{margin:6px 0 0;font-size:14px;color:{ink};line-height:1.35;}}
.ea-fo-col small{{display:block;font-size:12px;color:{muted};}}
.ea-fo-note{{font-size:14.5px;color:{ink};line-height:1.45;}}
@media (max-width:640px){{.ea-fo-grid{{grid-template-columns:1fr 1fr;}} .ea-fo-two{{grid-template-columns:1fr;}}
  .ea-fo-spark{{flex-direction:column;align-items:stretch;}}}}
"""

_STATES = {
    "clear": ("✓", GREEN, "Clear to trade"),
    "target": ("★", PURPLE, "Target reached — protect it"),
    "careful": ("!", AMBER, "Careful — close to your stop"),
    "stop": ("■", RED, "Stopped for the month"),
}


def _right_now_html(s: dict, label: str | None, t: dict) -> str:
    icon, c, head = _STATES[s["state"]]
    if s["state"] == "stop":
        sub = f"Past your {fmt_r(s['stop'], 1)} max loss. Flat until the 1st — that's the rule that keeps the account."
    elif s["state"] == "careful":
        sub = f"{s['room']:.1f}R above your {fmt_r(s['stop'], 1)} stop. Half size, A+ only, or sit this one out."
    elif s["state"] == "target":
        sub = f"{fmt_r(s['mtd'], 1)} against a {fmt_r(s['tgt'], 1)} target. Anything more is a bonus; a giveback isn't."
    else:
        sub = f"{s['room']:.1f}R of room above your {fmt_r(s['stop'], 1)} stop."
    if label:
        sub += f" · {_h.escape(label)}"
    bg = c + ("22" if rx._dark() else "12")
    head_css = _CSS.format(bg=bg, bc=c + "55", c=c, **t)
    last = s["last"]
    if last is not None:
        lr = float(last["__rr"])
        last_v = (f'<div class="v" style="color:{GREEN if lr > 0.15 else (RED if lr < -0.15 else t["muted"])};">'
                  f'{fmt_r(lr)}</div><div class="s">{last["__dt"].strftime("%a %d %b")}</div>')
    else:
        last_v = '<div class="v">—</div><div class="s">no trades yet</div>'
    mc = GREEN if s["mtd"] >= 0 else RED
    wc = GREEN if s["week_r"] > 0.05 else (RED if s["week_r"] < -0.05 else t["muted"])
    rc = RED if s["state"] == "stop" else (AMBER if s["state"] == "careful" else t["ink"])
    tiles = (
        f'<div class="ea-fo-k"><div class="l">{s["month_name"]}</div><div class="v" style="color:{mc};">{fmt_r(s["mtd"], 1)}</div>'
        f'<div class="s">{s["n_month"]} trades · target {fmt_r(s["tgt"], 1)}</div></div>'
        f'<div class="ea-fo-k"><div class="l">Room to stop</div><div class="v" style="color:{rc};">'
        f'{max(0.0, s["room"]):.1f}R</div><div class="s">stop at {fmt_r(s["stop"], 1)}</div></div>'
        f'<div class="ea-fo-k"><div class="l">This week</div><div class="v" style="color:{wc};">{fmt_r(s["week_r"], 1)}</div>'
        f'<div class="s">{s["n_week"]} trade{"s" if s["n_week"] != 1 else ""}</div></div>'
        f'<div class="ea-fo-k"><div class="l">Last trade</div>{last_v}</div>')
    spark = ""
    if s["path"]:
        spark = (f'<div class="ea-fo-spark"><div style="flex:1;min-width:0;">{_spark(s["path"], s["tgt"], s["stop"], t)}</div>'
                 f'<div class="lg"><span style="color:{GREEN};">- - target {fmt_r(s["tgt"], 1)}</span><br>'
                 f'<span style="color:{RED};">- - stop {fmt_r(s["stop"], 1)}</span></div></div>')
    return (rx.css(head_css) + f'<div class="ea-rx ea-fo"><div class="ea-fo-head"><div class="ea-fo-dot">{icon}</div>'
            f'<div><b>{head}</b><span>{sub}</span></div></div><div class="ea-fo-grid">{tiles}</div>{spark}</div>')


def _checklist_html(proven: list, mine: list, t: dict) -> str:
    rows = ""
    for e in proven[:5]:
        rule, edge = e[0], e[1]
        rule = rule.replace(" (from your data)", "")
        rows += (f'<div class="ea-fo-i"><span class="n"></span><span class="t">{_h.escape(rule)}</span>'
                 f'<span class="e" style="color:{GREEN};background:{GREEN}1a;">+{edge:.2f}R</span></div>')
    if mine:
        rows += '<div class="ea-fo-sub">YOUR OWN RULES</div>'
        for rule in mine[:8]:
            rows += (f'<div class="ea-fo-i"><span class="n"></span><span class="t">{_h.escape(rule)}</span></div>')
    return f'<div class="ea-rx ea-fo-list">{rows}</div>'


def _lean_html(lean: list, stay: list, t: dict) -> str:
    def col(title, c, items, empty):
        body = "".join(f"<p><b>{_h.escape(r)}</b><small>{_h.escape(ev)}</small></p>" for _rid, r, ev, _k in items)
        return (f'<div class="ea-fo-col" style="border-top:3px solid {c};"><div class="h" style="color:{c};">{title}</div>'
                f'{body or f"<small>{empty}</small>"}</div>')
    return ('<div class="ea-rx ea-fo-two">'
            + col("LEAN INTO", GREEN, lean, "Nothing clears the bar yet.")
            + col("STAY AWAY FROM", RED, stay, "Nothing clears the bar yet.")
            + "</div>")


def _after_text(a: dict) -> str:
    kinds = {"win": "a win", "loss": "a loss", "be": "a break-even"}
    if a["streak"] >= 2:
        opener = (f"{a['streak']} {'losses' if a['kind'] == 'loss' else 'wins' if a['kind'] == 'win' else 'break-evens'} "
                  f"in a row, the last {fmt_r(a['last_r'])} on {a['last_dt'].strftime('%a %d %b')}.")
        after = f"after {'two or more ' + ('losses' if a['kind'] == 'loss' else 'wins' if a['kind'] == 'win' else 'break-evens') + ' in a row'}"
    else:
        opener = f"Your last trade was {kinds[a['kind']]}: {fmt_r(a['last_r'])} on {a['last_dt'].strftime('%a %d %b')}."
        after = f"after {kinds[a['kind']]}"
    if a["same_avg"] is None:
        return (opener + f" There are only {a['same_n']} trades {after} so far — too few to say how "
                "the next one tends to go.")
    col = GREEN if a["same_avg"] >= 0 else RED
    txt = (opener + f" Your next trade {after} has averaged "
           f"<b style='color:{col};'>{fmt_r(a['same_avg'])}</b> over {a['same_n']} trades")
    if a["kind"] != "win" and a["win_avg"] is not None:
        txt += f", against {fmt_r(a['win_avg'])} after a win"
    txt += "."
    if a["kind"] == "loss" and a["win_avg"] is not None and a["same_avg"] < a["win_avg"] - 0.2:
        txt += " That gap is the tilt tax — the checklist above is the gate."
    return txt


def render_focus(f_perf: pd.DataFrame, df_all: pd.DataFrame, styler) -> None:
    from edge_analysis.ui import tabs as T
    from edge_analysis.ui.plan_tabs import plan_model, rule_recommendations, _rules_state
    t = rx._tokens()

    # 1. Right now — the main account only, like the month card and breaker
    track, label, _others = T._track_only(df_all)
    gp = T._perf_prep(track)
    tgt, stop = 5.0, -6.0
    if gp is not None and "PnL_from_RR" in gp.columns:
        try:
            tgt, stop, _auto = T._perf_settings(gp)
        except Exception:
            pass
    g = dated(track)
    with st.container(border=True):
        st.markdown('<div class="ea-card-anchor"></div>', unsafe_allow_html=True)
        T._card_header("Right now", "Can you trade today — the month against its lines, "
                                     "this week, and your last trade.")
        if g is None:
            st.caption("Your briefing starts once trades carry a date and a result.")
            return
        st.markdown(_right_now_html(right_now(g, tgt, stop), label, t), unsafe_allow_html=True)

    # 2. Before you take a trade
    m = plan_model(df_all)
    state = _rules_state()
    texts = state.get("texts") or {}
    mine = list(state.get("custom") or []) + [texts.get(rid, rid.split(":", 1)[-1])
                                              for rid in (state.get("accepted") or [])]
    proven = (m or {}).get("proven") or []
    with st.container(border=True):
        st.markdown('<div class="ea-card-anchor"></div>', unsafe_allow_html=True)
        T._card_header("Before you take a trade",
                       "Every box yes, or pass. The first ones have earned their place in your journal "
                       "(their edge in R a trade); the rest are yours.")
        if proven or mine:
            st.markdown(rx.css(_CSS.format(bg="", bc="", c="", **t)) + _checklist_html(proven, mine, t),
                        unsafe_allow_html=True)
        else:
            st.caption("No checklist yet — a tag earns a place here once it has 5+ trades at a positive "
                       "average, and you can write your own rules on Plan.")

    # 3. Lean into / stay away from
    if m:
        recs = rule_recommendations(m["good"], m["bad"])
        lean = [r for r in recs if r[3]][:2]
        stay = [r for r in recs if not r[3]][:2]
        if lean or stay:
            with st.container(border=True):
                st.markdown('<div class="ea-card-anchor"></div>', unsafe_allow_html=True)
                T._card_header("Lean into, stay away from",
                               "The things you choose, with 5+ trades and a real gap behind them.")
                st.markdown(rx.css(_CSS.format(bg="", bc="", c="", **t)) + _lean_html(lean, stay, t),
                            unsafe_allow_html=True)

    # 4. After your last trade
    a = after_last(g)
    if a:
        with st.container(border=True):
            st.markdown('<div class="ea-card-anchor"></div>', unsafe_allow_html=True)
            T._card_header("After your last trade", "How your next trade has gone after a result like it.")
            st.markdown(rx.css(_CSS.format(bg="", bc="", c="", **t))
                        + f'<div class="ea-rx ea-fo-note">{_after_text(a)}</div>', unsafe_allow_html=True)
    st.caption("Everything else is one switch away: turn Focus off in the header.")
