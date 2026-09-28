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


# a lesson theme whose question IS a checklist box (plan_tabs._GATE_GROUP)
_THEME_GATE = {"Patience and rules": "aplus"}


def checklist_items(proven: list, recs: list, lesson_groups: list, mine: list,
                    beats=None, gate_beats=None, covered=frozenset()) -> list[dict]:
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
        if not q or _THEME_GATE.get(gp["theme"]) in (covered or ()):
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


# ----------------------------- the rundown -------------------------------------

def _slice_family(g: pd.DataFrame, cols: dict) -> dict:
    """p-values for every value of each column, both directions, Holm across
    all of them — so 'best session' is only 'beats chance' when picking the
    best out of several still clears the bar."""
    from edge_analysis.digest import _perm_p, _holm_pass
    keys, ps = [], []
    for name, ser in cols.items():
        for v in ser.dropna().unique():
            m = (ser == v).to_numpy()
            if m.sum() < 5 or m.sum() >= len(m) - 1:
                continue
            for d in ("good", "bad"):
                keys.append((name, v, d))
                ps.append(_perm_p(g["__rr"], m, lower=d == "bad"))
    passed = {keys[i] for i in _holm_pass(ps)}
    return {"keys": set(keys), "passed": passed}


def _res_series(g: pd.DataFrame) -> pd.Series:
    ocol = next((c for c in ("Outcome", "Outcome Canonical", "Result") if c in g.columns), None)
    band = g["__rr"].map(lambda r: "win" if r > 0.15 else ("loss" if r < -0.15 else "be"))
    if ocol is None:
        return band
    tag = g[ocol].astype(str).str.strip().str.lower().replace({"breakeven": "be"})
    return tag.where(tag.isin(["win", "be", "loss"]), band)


def rundown(g: pd.DataFrame, verdicts: bool) -> list[dict]:
    """The most important thing each part of the site says, one line each:
    {area, html, tab, tone}. Counts are stated as counts; a best/worst pick is
    labelled 'beats chance' or 'early read', and early reads are left out for
    members (verdicts=False)."""
    from edge_analysis.ui import lessons as _ls
    items = []
    if g is None or g.empty:
        return items
    rr = g["__rr"]
    res = _res_series(g)
    n = len(g)
    w, b, l_ = int((res == "win").sum()), int((res == "be").sum()), int((res == "loss").sum())
    items.append({"area": "Your record", "tab": "Performance", "tone": "pos" if rr.sum() > 0 else "neg",
                  "html": f"<b>{fmt_r(rr.sum(), 1)}</b> over {n} trades \u00b7 <b>{fmt_r(rr.mean())}</b> a trade "
                          f"\u00b7 {w} win{'s' if w != 1 else ''}, {b} break-even{'s' if b != 1 else ''}, "
                          f"{l_} loss{'es' if l_ != 1 else ''}"})

    def _lab(ok):
        return ' <span class="ea-fo-ok">beats chance</span>' if ok else ' <span class="ea-fo-er">early read</span>'
    sc = next((c for c in ("Session Norm", "Session") if c in g.columns), None)
    e1 = next((c for c in ("Entry Model 1", "Entry Model") if c in g.columns), None)
    e2 = "Entry Model 2" if "Entry Model 2" in g.columns else None
    cols = {}
    if sc:
        from edge_analysis.ui.tabs import _clean_session_value
        cols["session"] = g[sc].map(rx._txt).map(lambda v: _clean_session_value(v) if v else None)
    if e1:
        a = g[e1].map(rx._txt).str.split(",").str[0].str.strip()
        bb = g[e2].map(rx._txt).str.split(",").str[0].str.strip() if e2 else pd.Series("", index=g.index)
        cols["setup"] = pd.Series([f"{x} \u2192 {y}" if (x and y) else (x or None) for x, y in zip(a, bb)],
                                  index=g.index).replace("", None)
    fam = _slice_family(g, cols) if cols else {"keys": set(), "passed": set()}

    if "session" in cols:
        stats = rr.groupby(cols["session"]).agg(["count", "sum"])
        stats = stats[stats["count"] >= 3]
        if len(stats) >= 2:
            bst, wst = stats["sum"].idxmax(), stats["sum"].idxmin()
            ok_b = ("session", bst, "good") in fam["passed"]
            ok_w = ("session", wst, "bad") in fam["passed"]
            parts = []
            if stats.loc[bst, "sum"] > 0 and (verdicts or ok_b):
                parts.append(f"<b>{_h.escape(str(bst))}</b> is where your R comes from "
                             f"({fmt_r(stats.loc[bst, 'sum'], 1)} over {int(stats.loc[bst, 'count'])}){_lab(ok_b)}")
            if stats.loc[wst, "sum"] < 0 and wst != bst and (verdicts or ok_w):
                parts.append(f"<b>{_h.escape(str(wst))}</b> has cost {fmt_r(stats.loc[wst, 'sum'], 1)} over "
                             f"{int(stats.loc[wst, 'count'])}{_lab(ok_w)}")
            if parts:
                items.append({"area": "When you trade", "tab": "Entry", "tone": "",
                              "html": "; ".join(parts) + "."})
    if "setup" in cols:
        stats = rr.groupby(cols["setup"]).agg(["count", "sum"])
        stats = stats[stats["count"] >= 3]
        if len(stats):
            bst = stats["sum"].idxmax()
            ok = ("setup", bst, "good") in fam["passed"]
            if stats.loc[bst, "sum"] > 0 and (verdicts or ok):
                items.append({"area": "Best setup", "tab": "Entry", "tone": "",
                              "html": f"<b>{_h.escape(str(bst))}</b>: {fmt_r(stats.loc[bst, 'sum'], 1)} over "
                                      f"{int(stats.loc[bst, 'count'])} trades{_lab(ok)}."})
    tg = rx.targets_frame(g.assign(**{"Closed RR": rr}) if "Closed RR" not in g.columns else g)
    if tg is not None:
        ts = rx.targets_summary(tg)
        items.append({"area": "Targets", "tab": "Entry", "tone": "neg" if ts["reached"] * 2 < ts["n"] else "pos",
                      "html": f"Price reached your target on <b>{ts['reached']} of {ts['n']}</b> trades: you plan "
                              f"{ts['plan']:.1f}R and it gives {ts['mfe']:.1f}R on average."})
    if "Breakeven Criteria" in g.columns:
        be = g["Breakeven Criteria"].map(rx._txt).str.split(",").str[0].str.strip()
        badm = be.str.contains(r"loss before|failed", case=False, regex=True, na=False)
        if int(badm.sum()) >= 2:
            items.append({"area": "Breakeven", "tab": "Entry", "tone": "neg",
                          "html": f"<b>{int(badm.sum())} trades lost before breakeven was set</b> "
                                  f"({fmt_r(rr[badm].sum(), 1)})."})
    if "Rules Followed?" in g.columns:
        # the adapter already turns an untagged trade's unticked box into
        # "unknown" (None), so tagged = answered either way
        rf = g["Rules Followed?"].map(rx._yes)
        followed, broke, untagged = int((rf == True).sum()), int((rf == False).sum()), int(rf.isna().sum())  # noqa: E712
        if followed + broke > 0:
            items.append({"area": "Discipline", "tab": "Psychology",
                          "html": f"<b>{followed} of {followed + broke}</b> tagged trades followed your rules"
                                  + (f"; {untagged} trade{'s' if untagged != 1 else ''} aren't tagged yet."
                                     if untagged else ".")})
    grp = _ls.summary(g)["groups"]
    if grp:
        items.append({"area": "Your lessons", "tab": "Psychology", "tone": "",
                      "html": f"The one you write most: <b>{_h.escape(grp[0]['theme'].lower())}</b> "
                              f"({grp[0]['n']}\u00d7)."})
    return items


_RUN_CSS = """
.ea-fo-run{{display:flex;flex-direction:column;}}
.ea-fo-rr{{display:flex;gap:14px;align-items:baseline;padding:10px 2px;border-bottom:1px solid {line};}}
.ea-fo-rr:last-child{{border-bottom:0;}}
.ea-fo-rr .a{{flex:0 0 118px;font-size:11.5px;font-weight:800;letter-spacing:.06em;text-transform:uppercase;color:{muted};}}
.ea-fo-rr .x{{flex:1;min-width:0;font-size:14.5px;line-height:1.45;color:{ink};}}
.ea-fo-rr .x b{{font-weight:800;}}
.ea-fo-rr .x b.pos{{color:#16a34a;}} .ea-fo-rr .x b.neg{{color:#ef4444;}}
.ea-fo-rr .t{{flex:none;font-size:12px;color:{muted};white-space:nowrap;}}
.ea-fo-ok{{font-size:11px;font-weight:800;color:#16a34a;white-space:nowrap;}}
.ea-fo-er{{font-size:11px;font-weight:700;color:{few};white-space:nowrap;}}
@media (max-width:640px){{.ea-fo-rr{{flex-wrap:wrap;gap:2px 10px;}} .ea-fo-rr .a{{flex-basis:100%;}}
  .ea-fo-rr .t{{display:none;}}}}
"""


def _rundown_html(items: list[dict], t: dict) -> str:
    rows = "".join(f'<div class="ea-fo-rr"><div class="a">{_h.escape(it["area"])}</div>'
                   f'<div class="x">{it["html"]}</div><div class="t">{_h.escape(it["tab"])} \u203a</div></div>'
                   for it in items)
    return rx.css(_RUN_CSS.format(**t)) + f'<div class="ea-rx ea-fo-run">{rows}</div>'


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

    # 2. The rundown: the most important line from every part of the site
    from edge_analysis.ui.tabs import _verdicts_on
    items = rundown(g, _verdicts_on())
    if items:
        with st.container(border=True):
            st.markdown('<div class="ea-card-anchor"></div>', unsafe_allow_html=True)
            T._card_header("The rundown", "The most important thing each part of the site is telling you.")
            st.markdown(_rundown_html(items, t), unsafe_allow_html=True)

    # 3. The top of the checklist; the whole list lives on Plan
    m = plan_model(df_all)
    state = _rules_state()
    texts = state.get("texts") or {}
    mine = list(state.get("custom") or []) + [texts.get(rid, rid.split(":", 1)[-1])
                                              for rid in (state.get("accepted") or [])]
    # a suggestion that repeats a checklist box is not a second item (28 Sep:
    # "It's a genuine A+ setup" and "Only take A+ setups" both made the four)
    from edge_analysis.ui.plan_tabs import _REC_RULES
    _cov = set((m or {}).get("covered") or ())
    recs = ([r for r in rule_recommendations(m["good"], m["bad"])
             if _REC_RULES.get(r[0].split(":", 1)[-1], ("",))[0] not in _cov]
            if (m and _verdicts_on()) else [])
    groups = _ls.summary(track)["groups"]
    chk = checklist_items((m or {}).get("proven") or [] if _verdicts_on() else [], recs, groups, mine,
                          (m or {}).get("beats"), (m or {}).get("gate_beats"), covered=_cov)
    if chk:
        with st.container(border=True):
            st.markdown('<div class="ea-card-anchor"></div>', unsafe_allow_html=True)
            T._card_header("Before your next trade", "The top of your checklist. The whole list is on Plan.")
            st.markdown(rx.css(_CSS.format(bg="", bc="", c="", **t)) + _checklist_html(chk[:4], t),
                        unsafe_allow_html=True)
    st.caption("Everything else is one switch away: turn Focus off in the header.")
