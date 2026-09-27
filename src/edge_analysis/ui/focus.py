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
    ocol = next((c for c in ("Outcome", "Outcome Canonical", "Result") if c in g.columns), None)
    oc = g[ocol].astype(str).str.strip().str.lower() if ocol else None
    tags = {"win": "win", "loss": "loss", "be": "be", "breakeven": "be"}
    res = [tags.get(o, _res(r)) if oc is not None else _res(r)
           for o, r in zip(oc if oc is not None else [None] * len(g), g["__rr"])]
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

_CSS = """
.ea-fo{{display:flex;flex-direction:column;gap:12px;}}
.ea-fo-head{{display:flex;align-items:center;gap:12px;padding:12px 16px;border-radius:12px;
  background:{bg};border:1px solid {bc};}}
.ea-fo-dot{{flex:none;width:34px;height:34px;border-radius:50%;display:flex;align-items:center;justify-content:center;
  font-size:17px;font-weight:800;color:#fff;background:{c};}}
.ea-fo-head b{{display:block;font-size:17px;color:{c};}}
.ea-fo-head span{{display:block;font-size:13.5px;color:{ink};}}
.ea-fo-bar{{position:relative;height:12px;border-radius:6px;background:{soft};border:1px solid {line};margin:18px 2px 20px;}}
.ea-fo-bar i{{position:absolute;top:-1px;bottom:-1px;}}
.ea-fo-bar .z{{width:2px;background:{zero};}}
.ea-fo-bar i.m{{top:-6px;bottom:-6px;width:4px;margin-left:-2px;border-radius:2px;background:{ink};}}
.ea-fo-bar span{{position:absolute;top:15px;transform:translateX(-50%);font-size:11.5px;color:{muted};white-space:nowrap;}}
.ea-fo-bar span.l{{transform:none;}} .ea-fo-bar span.r{{transform:translateX(-100%);}}
.ea-fo-bar span.m{{top:-27px;font-weight:800;color:{ink};font-size:12.5px;}}
.ea-fo-line{{font-size:14px;color:{ink};line-height:1.45;}}
.ea-fo-line small{{color:{muted};font-size:13px;}}
.ea-fo-list{{display:flex;flex-direction:column;gap:6px;}}
.ea-fo-i{{display:flex;align-items:center;gap:10px;padding:9px 12px;border:1px solid {line};border-radius:10px;background:{base};}}
.ea-fo-i .n{{flex:none;width:22px;height:22px;border-radius:6px;border:2px solid {zero};}}
.ea-fo-i .t{{flex:1;min-width:0;font-size:14px;font-weight:650;color:{ink};line-height:1.3;}}
.ea-fo-i .t small{{display:block;font-size:12px;font-weight:500;color:{muted};margin-top:2px;overflow-wrap:anywhere;}}
.ea-fo-i .e{{flex:none;font-size:12px;font-weight:800;border-radius:999px;padding:2px 9px;white-space:nowrap;}}
"""

_STATES = {
    "clear": ("\u2713", GREEN, "Clear to trade"),
    "target": ("\u2605", PURPLE, "Target reached \u2014 protect it"),
    "careful": ("!", AMBER, "Careful \u2014 close to your stop"),
    "stop": ("\u25a0", RED, "Stopped for the month"),
}


def _month_bar(s: dict) -> str:
    """Where the month sits between its stop and its target."""
    lo = min(s["stop"], s["mtd"])
    hi = max(s["tgt"], s["mtd"])
    span = (hi - lo) or 1.0

    def X(v):
        return (v - lo) / span * 100
    tone = RED if s["state"] == "stop" else (AMBER if s["state"] == "careful" else
                                            (GREEN if s["mtd"] >= 0 else RED))
    mx = X(s["mtd"])
    fill = (f'<i style="left:{min(X(0), mx):.1f}%;width:{abs(mx - X(0)):.1f}%;background:{tone};'
            f'opacity:.55;border-radius:6px;"></i>')
    return (f'<div class="ea-fo-bar">{fill}<i class="z" style="left:{X(0):.1f}%"></i>'
            f'<i class="m" style="left:{mx:.1f}%"></i>'
            f'<span class="m" style="left:{mx:.1f}%">{fmt_r(s["mtd"], 1)}</span>'
            f'<span class="l" style="left:0;color:{RED};">stop {fmt_r(s["stop"], 1)}</span>'
            f'<span class="r" style="left:100%;color:{GREEN};">target {fmt_r(s["tgt"], 1)}</span></div>')


def _right_now_html(s: dict, label: str | None, t: dict, after: str = "") -> str:
    icon, c, head = _STATES[s["state"]]
    to_tgt = s["tgt"] - s["mtd"]
    if s["state"] == "stop":
        sub = f"Past your {fmt_r(s['stop'], 1)} max loss. Flat until the 1st \u2014 that's the rule that keeps the account."
    elif s["state"] == "careful":
        sub = f"{s['room']:.1f}R above your {fmt_r(s['stop'], 1)} stop. Half size, A+ only, or sit this one out."
    elif s["state"] == "target":
        sub = f"{fmt_r(s['mtd'], 1)} against a {fmt_r(s['tgt'], 1)} target. Anything more is a bonus; a giveback isn't."
    else:
        sub = (f"{s['month_name']} {fmt_r(s['mtd'], 1)} \u00b7 {s['room']:.1f}R of room to your stop"
               + (f" \u00b7 {to_tgt:.1f}R to target" if to_tgt > 0 else ""))
    if label:
        sub += f" \u00b7 {_h.escape(label)}"
    bg = c + ("22" if rx._dark() else "12")
    css = _CSS.format(bg=bg, bc=c + "55", c=c, **t)
    last = s["last"]
    bits = [f"This week {fmt_r(s['week_r'], 1)} over {s['n_week']} trade{'s' if s['n_week'] != 1 else ''}"]
    if last is not None and not after:           # the after-line already names the last trade
        bits.append(f"last trade {last['__dt'].strftime('%a %d %b')}")
    joined = " \u00b7 ".join(bits)
    line = f'<div class="ea-fo-line">{joined}.' + (f" {after}" if after else "") + "</div>"
    return (rx.css(css) + f'<div class="ea-rx ea-fo"><div class="ea-fo-head"><div class="ea-fo-dot">{icon}</div>'
            f'<div><b>{head}</b><span>{sub}</span></div></div>{_month_bar(s)}{line}</div>')


def _checklist_html(items: list[dict], t: dict) -> str:
    rows = ""
    for it in items:
        chip = ""
        if it.get("chip"):
            cc = it.get("color", PURPLE)
            chip = f'<span class="e" style="color:{cc};background:{cc}1f;">{_h.escape(it["chip"])}</span>'
        sub = f'<small>{_h.escape(it["sub"])}</small>' if it.get("sub") else ""
        rows += (f'<div class="ea-fo-i"><span class="n"></span><span class="t">{_h.escape(it["text"])}{sub}</span>'
                 f'{chip}</div>')
    return f'<div class="ea-rx ea-fo-list">{rows}</div>'


def _proven_label(rule: str) -> str:
    rule = rule.replace(" (from your data)", "")
    if rule.startswith("Your proven "):
        rule = rule[len("Your proven "):]
        rule = rule[:1].upper() + rule[1:]
    return rule


def checklist_items(proven: list, recs: list, lesson_groups: list, mine: list,
                    beats=None, gate_beats=None) -> list[dict]:
    """One list of pre-trade gates: what your numbers back, the lessons you
    keep writing, then your own rules. Numbers say 'beats chance' or 'early read'."""
    import re as _re
    from edge_analysis.ui.lessons import THEME_CHECK
    items, seen = [], set()

    def _add(it):
        k = it["text"].lower()
        if k not in seen:
            seen.add(k)
            items.append(it)
    for e in proven[:3]:
        early = gate_beats is not None and e[0] not in gate_beats
        _add({"text": _proven_label(e[0]), "sub": "your numbers \u00b7 " + ("early read" if early else "beats chance"),
              "chip": f"+{e[1]:.2f}R".replace("+-", "\u2212"), "color": GREEN})
    keep = [r for r in recs if r[3]][:1] + [r for r in recs if not r[3]][:1]
    for rid, rule, ev, k in keep:
        m = _re.search(r"[+\-\u2212]\d+(\.\d+)?R", ev)
        n = _re.search(r"over (\d+) trades", ev)
        early = beats is not None and rid.split(":", 1)[-1] not in beats
        _add({"text": rule, "sub": (f"{n.group(1)} trades" if n else ev) + " \u00b7 "
              + ("early read" if early else "beats chance"),
              "chip": m.group(0) if m else "", "color": GREEN if k else RED})
    for gp in lesson_groups[:3]:
        q = THEME_CHECK.get(gp["theme"])
        if not q:
            continue
        note = min((r["text"] for r in gp["rows"]), key=len)
        note = note if len(note) <= 80 else note[:78].rstrip() + "\u2026"
        _add({"text": q, "sub": f"\u201c{note}\u201d \u00b7 your note, {gp['n']}\u00d7",
              "chip": f"{gp['n']}\u00d7", "color": PURPLE if not rx._dark() else "#a78bfa"})
    for rule in mine[:8]:
        _add({"text": rule, "sub": "your rule"})
    return items


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
    from edge_analysis.ui import lessons as _ls
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
        T._card_header("Right now", "Can you trade today: the month between its stop and target.")
        if g is None:
            st.caption("Your briefing starts once trades carry a date and a result.")
            return
        a = after_last(g)
        st.markdown(_right_now_html(right_now(g, tgt, stop), label, t, _after_text(a) if a else ""),
                    unsafe_allow_html=True)

    # 2. Before you take a trade: numbers, your notes, your rules in one list
    m = plan_model(df_all)
    state = _rules_state()
    texts = state.get("texts") or {}
    mine = list(state.get("custom") or []) + [texts.get(rid, rid.split(":", 1)[-1])
                                              for rid in (state.get("accepted") or [])]
    recs = rule_recommendations(m["good"], m["bad"]) if m else []
    groups = _ls.summary(track)["groups"]
    items = checklist_items((m or {}).get("proven") or [], recs, groups, mine,
                            (m or {}).get("beats"), (m or {}).get("gate_beats"))
    with st.container(border=True):
        st.markdown('<div class="ea-card-anchor"></div>', unsafe_allow_html=True)
        T._card_header("Before you take a trade",
                       "Every box yes, or pass. From your numbers, the lessons you keep writing, and your rules.")
        if items:
            st.markdown(rx.css(_CSS.format(bg="", bc="", c="", **t)) + _checklist_html(items, t),
                        unsafe_allow_html=True)
        else:
            st.caption("No checklist yet: a tag earns a place here once it has 5+ trades at a positive "
                       "average, a lesson once you've written it twice, and you can add your own rules on Plan.")
    st.caption("Everything else is one switch away: turn Focus off in the header.")
