"""Your lessons: the notes you write on each trade, grouped so a lesson you
keep writing stands out (round-1 mockup M9).

Grouping is by the words traders actually use: each note goes to the first
theme it matches, in the order below. "BE" only counts in capitals, so the
word "be" in "don't be greedy" isn't a breakeven note.
"""
from __future__ import annotations

import html as _h
import re

import pandas as pd
import streamlit as st

from edge_analysis.ui import reshape as rx

LESSON_COLS = ("Teachings/Learning Curve", "Lessons Learned", "Lessons", "Lesson", "Takeaway", "Learning")

_I = re.I
THEMES: list[tuple[str, list[re.Pattern]]] = [
    ("Breakeven", [re.compile(r"\bBE\b"), re.compile(r"break[- ]?even", _I)]),
    ("Taking profit", [re.compile(r"\btp\d?\b|sl2tp|take profit|taking profit|\btargets?\b|ambit?ious|ambitous|greed"
                                  r"|early close|close(d)? early|lock(ed)? in|partials?|profits?", _I)]),
    ("Stop placement", [re.compile(r"\bsl\b|stop[- ]?loss|\bstops?\b", _I)]),
    ("Sweeps and liquidity", [re.compile(r"sweep|swept|liquidity|stop hunt", _I)]),
    ("Bias", [re.compile(r"\bbias\b", _I)]),
    ("Where you get in", [re.compile(r"opposing w\w* structure|weak (high|low|structure)|\brange\b|late entry"
                                     r"|chas(e|ed|ing)\b|fomo|miss(ed)? the entry|external (high|low)s?", _I)]),
    ("Patience and rules", [re.compile(r"patien|\bwait|overtrad|revenge|\brules?\b|discipline|a\+", _I)]),
    ("News", [re.compile(r"\bnews\b|\bcpi\b|\bnfp\b|fomc", _I)]),
]
MIN_LESSONS = 3   # fewer and there's nothing to group
MAX_CARDS = 4     # the rest get one line, not a wall of cards


def theme_of(text: str) -> str:
    for name, pats in THEMES:
        if any(p.search(text) for p in pats):
            return name
    return "Other"


def lesson_col(df: pd.DataFrame) -> str | None:
    return next((c for c in LESSON_COLS if c in df.columns), None)


def lessons_frame(df: pd.DataFrame) -> pd.DataFrame:
    """One row per trade with a real lesson: when, R, text, theme. Newest first."""
    col = lesson_col(df) if df is not None else None
    if col is None or df.empty:
        return pd.DataFrame(columns=["when", "r", "text", "theme"])
    out = pd.DataFrame(index=df.index)
    dcol = next((c for c in ("__Date", "Date", "Open Time", "Close Time") if c in df.columns), None)
    out["when"] = pd.to_datetime(df[dcol], errors="coerce") if dcol else pd.NaT
    if dcol and out["when"].isna().all():
        out["when"] = pd.NaT
    rcol = next((c for c in ("Closed RR", "PnL_from_RR", "R Multiple") if c in df.columns), None)
    out["r"] = pd.to_numeric(df[rcol], errors="coerce") if rcol else float("nan")
    out["text"] = df[col].map(rx._txt)
    out = out[out["text"].str.len() > 2]
    out["theme"] = out["text"].map(theme_of)
    return out.sort_values("when", ascending=False, na_position="last")


def summary(df: pd.DataFrame) -> dict:
    """Themes written 2+ times (most first), singles, and the headline counts."""
    lf = lessons_frame(df)
    groups = []
    for name, sub in lf.groupby("theme", sort=False):
        if name == "Other" or len(sub) < 2:
            continue
        groups.append({"theme": name, "n": len(sub), "r": float(sub["r"].sum(skipna=True)),
                       "rows": sub.to_dict("records"), "last": sub["when"].max()})
    groups.sort(key=lambda g: (-g["n"], -(g["last"].value if pd.notna(g["last"]) else 0)))
    grouped = {r["text"] for g in groups for r in g["rows"]}
    return {"n_trades": 0 if df is None else len(df), "n_lessons": len(lf), "groups": groups,
            "singles": lf[~lf["text"].isin(grouped)].to_dict("records"), "all": lf.to_dict("records")}


def _targets_line(df: pd.DataFrame) -> str:
    """When the top theme is taking profit and the journal has targets and MFE,
    say what the numbers show: how often price actually reached the target."""
    if not {"Planned R:R", "MFE (R)"} <= set(df.columns):
        return ""
    plan = pd.to_numeric(df["Planned R:R"], errors="coerce")
    mfe = pd.to_numeric(df["MFE (R)"], errors="coerce")
    ok = plan.gt(0) & mfe.notna()
    m = int(ok.sum())
    if m < 5:
        return ""
    hit = int((mfe[ok] >= plan[ok]).sum())
    if hit * 2 >= m:        # targets mostly get reached: the numbers don't back the lesson
        return ""
    return (f" Your numbers say the same: price reached your planned target on "
            f"<b>{hit} of {m}</b> trades.")


def _fmt_r(v) -> str:
    return "" if v is None or pd.isna(v) else f"{v:+.2f}R".replace("-", "−")


def render_lessons(df: pd.DataFrame) -> bool:
    """Draw the card body. Returns False (and draws nothing) when the journal
    has too few lessons to group."""
    s = summary(df)
    if s["n_lessons"] < MIN_LESSONS:
        return False
    t = rx._tokens()
    head = f"You've written a lesson on <b>{s['n_lessons']} of {s['n_trades']}</b> trades."
    if s["groups"]:
        top = s["groups"][0]
        head += f" The one you come back to most: <b>{_h.escape(top['theme'].lower())}</b> ({top['n']}×)."
        if top["theme"] == "Taking profit":
            head += _targets_line(df)
    else:
        head += " None repeats yet; the ones you write twice will group here."
    cards = ""
    shown, rest = s["groups"][:MAX_CARDS], s["groups"][MAX_CARDS:]
    for g in shown:
        quotes = ""
        for r in g["rows"][:4]:
            d = r["when"].strftime("%-d %b") if pd.notna(r["when"]) else ""
            rv = r["r"]
            rc = t["ink"] if pd.isna(rv) else ("#16a34a" if rv > 0 else "#ef4444")
            txt = r["text"] if len(r["text"]) <= 110 else r["text"][:108].rstrip() + "…"
            quotes += (f'<div class="ea-ls-q"><b>{_h.escape(d)}</b> <span style="color:{rc}">{_fmt_r(rv)}</span>'
                       f' · “{_h.escape(txt)}”</div>')
        more = f'<div class="ea-ls-more">+{g["n"] - 4} more</div>' if g["n"] > 4 else ""
        gr = g["r"]
        gc = "#16a34a" if gr > 0 else ("#ef4444" if gr < 0 else t["muted"])
        cards += (f'<div class="ea-ls-card"><div class="ea-ls-h"><span class="ea-ls-t">{_h.escape(g["theme"])}</span>'
                  f'<span class="ea-ls-chip">written {g["n"]}×</span></div>'
                  f'<div class="ea-ls-sub">those trades: <b style="color:{gc}">{_fmt_r(gr)}</b></div>{quotes}{more}</div>')
    extra = f"""
.ea-ls-head{{font-size:15px;line-height:1.45;margin:0 0 12px;color:{t['ink']};}}
.ea-ls-grid{{display:grid;grid-template-columns:1fr 1fr;gap:12px;}}
@media (max-width:640px){{.ea-ls-grid{{grid-template-columns:1fr;}}}}
.ea-ls-card{{background:{t['soft']};border:1px solid {t['line']};border-radius:12px;padding:12px 14px;}}
.ea-ls-h{{display:flex;justify-content:space-between;align-items:baseline;gap:8px;}}
.ea-ls-t{{font-size:15px;font-weight:800;color:{t['ink']};}}
.ea-ls-chip{{font-size:11.5px;font-weight:700;border-radius:999px;padding:2px 9px;white-space:nowrap;
  background:rgba(72,0,255,.10);color:{'#c4bbff' if rx._dark() else '#4800ff'};}}
.ea-ls-sub{{font-size:12.5px;color:{t['muted']};margin:2px 0 6px;}}
.ea-ls-q{{font-size:13px;line-height:1.4;color:{t['muted']};margin-top:5px;overflow-wrap:anywhere;}}
.ea-ls-q b{{color:{t['ink']};}}
.ea-ls-more{{font-size:12px;color:{t['muted']};margin-top:6px;}}
"""
    body = f'<div class="ea-rx"><div class="ea-ls-head">{head}</div>'
    if cards:
        body += f'<div class="ea-ls-grid">{cards}</div>'
    if rest:
        also = ", ".join(f"{_h.escape(g['theme'].lower())} {g['n']}\u00d7" for g in rest)
        body += f'<div class="ea-ls-more" style="margin-top:10px">Also written more than once: {also}.</div>'
    st.markdown(rx.css(extra) + body + "</div>", unsafe_allow_html=True)
    if s["all"]:
        with st.expander(f"All {s['n_lessons']} lessons, newest first"):
            rows = ""
            for r in s["all"]:
                d = r["when"].strftime("%-d %b %Y") if pd.notna(r["when"]) else ""
                rows += (f'<div class="ea-ls-q" style="margin:0 0 8px"><b>{_h.escape(d)}</b> {_fmt_r(r["r"])}'
                         f' · <i>{_h.escape(r["theme"])}</i><br>{_h.escape(r["text"])}</div>')
            st.markdown(rx.css(extra) + f'<div class="ea-rx">{rows}</div>', unsafe_allow_html=True)
    st.caption("Grouped by the words you use, from your journal's lesson notes. "
               "Only the book you're viewing is counted.")
    return True
