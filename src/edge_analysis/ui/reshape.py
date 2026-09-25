"""Reshaped views (25 Sep 2026 launch review, mockups V2–V9): the same numbers
the site already computes, drawn as one picture instead of several tables.

House rules kept here:
- a thin sample never passes for an edge: under-threshold cells are hatched and
  hour bars under 8 trades are grey, with the count always printed;
- win rate is wins over every counted trade (Win, BE, Loss), as everywhere else;
- expectancy is the mean Closed RR, as `_rr_stats` computes it.
"""
from __future__ import annotations

import html as _h
import re

import pandas as pd
import streamlit as st

GREEN, RED, PURPLE = "#16a34a", "#dc2626", "#4800ff"
DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
BLOCKS = [(0, 4), (4, 8), (8, 12), (12, 16), (16, 20), (20, 24)]
METRICS = ["Expectancy", "Net R", "Win rate"]


def _dark() -> bool:
    return st.session_state.get("ea_theme_pref") == "dark"


def _tokens() -> dict:
    if _dark():
        return dict(ink="#e8ebf1", muted="#9aa4b4", line="#2a3040", soft="#1a1f2b",
                    base="#161b27", h1="#1f2533", h2="#262d3d", zero="#3a4356",
                    grey="#3a4256", few="#6b7280", pos_fg="#dcfce7", neg_fg="#fee2e2")
    return dict(ink="#0f172a", muted="#64748b", line="#e6e8f0", soft="#f8fafc",
                base="#ffffff", h1="#f1f5f9", h2="#e8edf3", zero="#cbd5e1",
                grey="#cbd5e1", few="#94a3b8", pos_fg="#14532d", neg_fg="#7f1d1d")


def css(extra: str = "") -> str:
    """The reshape components' stylesheet for the current theme, plus any
    `extra` rules, as ONE <style> block. Blank lines are stripped (a Markdown
    <style> block ends at the first one), and two blocks must never share a
    line: the HTML block ends at the line holding the first </style>, so the
    second block's rules leaked out as page text and hid what followed."""
    t = _tokens()
    s = f"""<style>
.ea-rx{{color:{t['ink']};}}
.ea-rx-scroll{{overflow-x:auto;-webkit-overflow-scrolling:touch;padding-bottom:4px;}}
.ea-rx-cap{{font-size:12.5px;color:{t['muted']};margin:6px 0 2px;display:flex;gap:14px;flex-wrap:wrap;align-items:center;}}
.ea-rx-cap i{{display:inline-block;width:11px;height:11px;border-radius:3px;margin-right:5px;vertical-align:-1px;}}
.ea-hb{{display:flex;min-width:760px;gap:3px;}}
.ea-hb-col{{flex:1 1 0;display:flex;flex-direction:column;align-items:stretch;min-width:0;}}
.ea-hb-up,.ea-hb-dn{{height:92px;display:flex;flex-direction:column;align-items:center;}}
.ea-hb-up{{justify-content:flex-end;border-bottom:1.5px dashed {t['zero']};}}
.ea-hb-dn{{justify-content:flex-start;}}
.ea-hb-bar{{width:72%;max-width:34px;}}
.ea-hb-up .ea-hb-bar{{border-radius:4px 4px 0 0;}}
.ea-hb-dn .ea-hb-bar{{border-radius:0 0 4px 4px;}}
.ea-hb-v{{font-size:11px;font-weight:700;line-height:1.35;white-space:nowrap;color:{t['ink']};}}
.ea-hb-v.few{{color:{t['few']};font-weight:600;}}
.ea-hb-h{{text-align:center;font-size:11.5px;color:{t['muted']};margin-top:4px;font-variant-numeric:tabular-nums;}}
.ea-hb-n{{text-align:center;font-size:10.5px;color:{t['few']};font-variant-numeric:tabular-nums;}}
.ea-hm{{border-collapse:separate !important;border-spacing:4px;width:100%;min-width:460px;table-layout:fixed;border:0 !important;margin:0 !important;background:none !important;}}
.ea-hm tr,.ea-hm th,.ea-hm td{{border:0 !important;}}
.ea-hm tr{{background:none !important;}}
.ea-hm th{{background:none !important;}}
.ea-hm th.l{{width:var(--nw,72px);}}
@media (max-width:640px){{.ea-hm th.l{{width:min(var(--nw,72px),116px);}}
  .ea-hm td{{font-size:13.5px;padding:7px 3px;}} .ea-hm td.name{{font-size:12px;}}}}
.ea-hm td.name{{padding-right:10px !important;}}
.ea-hm th{{font-size:12px;font-weight:700;color:{t['muted']};text-align:center;padding:2px 4px;white-space:nowrap;}}
.ea-hm th.l{{text-align:left;}}
.ea-hm td{{border-radius:8px;text-align:center;padding:8px 4px;font-size:15px;font-weight:800;
  font-variant-numeric:tabular-nums;background:{t['h1']};color:{t['ink']};}}
.ea-hm td small{{display:block;font-size:11px;font-weight:600;opacity:.8;}}
.ea-hm td.name{{text-align:left;background:none;font-size:13.5px;font-weight:700;padding-left:0;line-height:1.25;overflow-wrap:anywhere;color:{t['ink']};}}
.ea-hm td.few{{background:repeating-linear-gradient(135deg,{t['h1']} 0 6px,{t['h2']} 6px 12px);color:{t['few']};font-weight:700;}}
.ea-hm td.none{{background:{t['soft']};color:{t['few']};font-weight:600;font-size:12px;}}
.ea-hm td.tot{{box-shadow:inset 0 0 0 2px {t['base']};}}
.ea-hm tr.tot td.name{{color:{t['muted']};}}
{extra}
</style>"""
    return re.sub(r"\n\s*\n", "\n", s)


def heat(v, cap: float = 1.0) -> tuple[str, str]:
    """Diverging cell colour (background, text) for a value around zero."""
    t = _tokens()
    if v is None or pd.isna(v):
        return t["h1"], t["muted"]
    x = max(-1.0, min(1.0, float(v) / (cap or 1.0)))
    a = 0.14 + 0.6 * abs(x)
    strong = a > 0.5
    if x >= 0:
        return f"rgba(22,163,74,{a:.2f})", ("#ffffff" if strong else t["pos_fg"])
    return f"rgba(220,38,38,{a:.2f})", ("#ffffff" if strong else t["neg_fg"])


def fmt_r(v, d: int = 2) -> str:
    if v is None or pd.isna(v):
        return "—"
    v = float(v)
    if abs(v) < 0.5 * 10 ** -d:
        return f"{0:.{d}f}R"          # never "−0.00R"
    return f"{v:+.{d}f}R".replace("-", "−")


# ── data helpers ─────────────────────────────────────────────────────────────
def _parse_hour(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    s = str(v).strip()
    m = re.search(r"(\d{1,2}):(\d{2})\s*(AM|PM)", s, re.IGNORECASE)
    if m:
        h, ampm = int(m.group(1)), m.group(3).upper()
        if ampm == "PM" and h != 12:
            h += 12
        if ampm == "AM" and h == 12:
            h = 0
        return h
    m = re.search(r"(\d{1,2}):(\d{2})(?!\s*[AP]M)", s, re.IGNORECASE)
    if m:
        return int(m.group(1)) % 24
    return None


def trade_hours(df: pd.DataFrame) -> pd.Series | None:
    """Entry hour per trade, on the journal's own clock. Same source order as
    the old hour wheel: a datetime text column, Salty's Time of Trade, the MT5
    Hour (Melb), Open Time, then Date when it carries real times."""
    if df is None or df.empty:
        return None
    for c in ("Day/Time/Date of Trade", "Date & Time", "Datetime"):
        if c in df.columns:
            return df[c].map(_parse_hour)
    if "Time of Trade" in df.columns:
        return df["Time of Trade"].map(_parse_hour)
    if "Hour (Melb)" in df.columns:
        return pd.to_numeric(df["Hour (Melb)"], errors="coerce")
    if "Open Time" in df.columns:
        return pd.to_datetime(df["Open Time"], errors="coerce").dt.hour
    if "Date" in df.columns:
        d = pd.to_datetime(df["Date"], errors="coerce")
        if d.dt.hour.fillna(0).nunique() > 1:
            return d.dt.hour
    return None


def _counted(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["__r"] = pd.to_numeric(out.get("Closed RR"), errors="coerce")
    if "Outcome" in out.columns:
        out = out[out["Outcome"].isin(["Win", "BE", "Loss"])]
    return out[out["__r"].notna()]


def _stats(g: pd.DataFrame) -> dict:
    n = int(len(g))
    if not n:
        return dict(n=0, exp=None, net=None, win=None)
    win = (float(g["Outcome"].eq("Win").mean()) * 100.0) if "Outcome" in g.columns else None
    return dict(n=n, exp=float(g["__r"].mean()), net=float(g["__r"].sum()), win=win)


def _metric_val(s: dict, metric: str):
    return {"Expectancy": s["exp"], "Net R": s["net"], "Win rate": s["win"]}[metric]


def _metric_txt(v, metric: str) -> str:
    if v is None or pd.isna(v):
        return "—"
    if metric == "Win rate":
        return f"{float(v):.0f}%"
    return fmt_r(v, 2 if metric == "Expectancy" else 1)


def metric_picker(key: str) -> str:
    """One switch drives every grid in a card (mockup V2/V3)."""
    return st.radio("Show", METRICS, horizontal=True, key=key,
                    label_visibility="collapsed") or METRICS[0]


# ── hour bars (replaces the 24-hour wheel) ──────────────────────────────────
def hour_bars(df: pd.DataFrame, metric: str = "Expectancy", min_n: int = 8) -> bool:
    """Diverging bar per entry hour with its value on the bar and the trade
    count under it. Returns False when the journal carries no entry times."""
    hrs = trade_hours(df)
    if hrs is None:
        return False
    g = _counted(df.assign(__hr=hrs))
    g = g[g["__hr"].notna()]
    if g.empty:
        return False
    g["__hr"] = g["__hr"].astype(int) % 24
    by = {int(h): _stats(x) for h, x in g.groupby("__hr")}
    base_win = float(g["Outcome"].eq("Win").mean()) * 100.0 if "Outcome" in g.columns else 0.0
    vals = []
    for h, s in by.items():
        v = _metric_val(s, metric)
        if v is not None and s["n"] >= min_n:
            vals.append(abs(v - base_win) if metric == "Win rate" else abs(v))
    mx = max(vals) if vals else max([abs((_metric_val(s, metric) or 0) - (base_win if metric == "Win rate" else 0))
                                     for s in by.values()] or [1.0])
    mx = mx or 1.0
    t = _tokens()
    cols = []
    for h in range(24):
        s = by.get(h)
        up = dn = ""
        if s and s["n"]:
            v = _metric_val(s, metric)
            few = s["n"] < min_n
            # win rate reads against your overall rate, so the bar still diverges
            d = (v - base_win) if metric == "Win rate" else v
            pct = max(3.0, min(100.0, abs(d) / mx * 100.0)) if d else 3.0
            col = t["grey"] if few else (GREEN if d >= 0 else RED)
            # bar labels drop the R: 24 columns must fit a phone
            lab = f'<span class="ea-hb-v{" few" if few else ""}">{_h.escape(_metric_txt(v, metric).rstrip("R"))}</span>'
            bar = f'<div class="ea-hb-bar" style="height:{pct * 0.8:.0f}%;background:{col};"></div>'
            if d >= 0:
                up = lab + bar
            else:
                dn = bar + lab
        n_txt = str(s["n"]) if s and s["n"] else ""
        cols.append(f'<div class="ea-hb-col"><div class="ea-hb-up">{up}</div><div class="ea-hb-dn">{dn}</div>'
                    f'<div class="ea-hb-h">{h:02d}</div><div class="ea-hb-n">{n_txt}</div></div>')
    wr_note = (f"bars measured against your overall {base_win:.0f}%" if metric == "Win rate" else "")
    cap = (f'<div class="ea-rx-cap"><span><i style="background:{GREEN}"></i>earns</span>'
           f'<span><i style="background:{RED}"></i>costs</span>'
           f'<span><i style="background:{t["grey"]}"></i>under {min_n} trades</span>'
           f'<span>{"R per trade" if metric == "Expectancy" else ("net R" if metric == "Net R" else "win rate")} on each bar · '
           f'hour, then trades, underneath{(" · " + wr_note) if wr_note else ""}</span></div>')
    st.markdown(css() + f'<div class="ea-rx ea-rx-scroll"><div class="ea-hb">{"".join(cols)}</div></div>' + cap,
                unsafe_allow_html=True)
    return True


# ── generic heat grid ────────────────────────────────────────────────────────
def heat_grid(g: pd.DataFrame, row_col: str, col_col: str, rows: list, cols: list,
              metric: str = "Expectancy", min_n: int = 5, row_head: str = "",
              col_labels: dict | None = None, row_labels: dict | None = None, totals: bool = True,
              total_row_label: str = "All", total_col_label: str = "All",
              name_w: str = "72px", col_order_by_n: bool = False) -> None:
    """Rows × columns of `metric`, coloured around zero (win rate around your
    overall rate). Cells under `min_n` trades are hatched and never coloured;
    empty cells say so. With `totals`, the last column and row are the old
    single-dimension tables."""
    base_win = float(g["Outcome"].eq("Win").mean()) * 100.0 if ("Outcome" in g.columns and len(g)) else 0.0

    def _cap():
        if metric == "Expectancy":
            return 1.0
        if metric == "Win rate":
            return 25.0
        nets = [abs(float(x["__r"].sum())) for _, x in g.groupby([row_col, col_col]) if len(x) >= min_n]
        return max(nets) if nets else 1.0
    cap = _cap()

    def _cell(sub: pd.DataFrame, is_tot: bool = False) -> str:
        s = _stats(sub)
        v = _metric_val(s, metric)
        n = s["n"]
        tcls = " tot" if is_tot else ""
        if not n:
            return f'<td class="none{tcls}">·</td>'
        if n < min_n:
            return (f'<td class="few{tcls}">{_h.escape(_metric_txt(v, metric))}'
                    f'<small>{n} trade{"s" if n != 1 else ""}</small></td>')
        d = (v - base_win) if metric == "Win rate" else v
        bg, fg = heat(d, cap)
        return (f'<td class="{tcls.strip()}" style="background:{bg};color:{fg};">{_h.escape(_metric_txt(v, metric))}'
                f'<small>{n} trades</small></td>')

    # a column nobody trades in is noise (a 04–08 block for a London trader)
    cols = [c for c in cols if (g[col_col] == c).any()] or cols
    if col_order_by_n:
        cols = sorted(cols, key=lambda c: -int((g[col_col] == c).sum()))
    labels = col_labels or {}
    head = "".join(f"<th>{_h.escape(str(labels.get(c, c)))}</th>" for c in cols)
    if totals:
        head += f"<th>{_h.escape(total_col_label)}</th>"
    body = ""
    for r in rows:
        rg = g[g[row_col] == r]
        tds = "".join(_cell(rg[rg[col_col] == c]) for c in cols)
        if totals:
            tds += _cell(rg[rg[col_col].isin(cols)], True)
        body += f'<tr><td class="name">{_h.escape(str((row_labels or {}).get(r, r)))}</td>{tds}</tr>'
    if totals:
        tds = "".join(_cell(g[(g[col_col] == c) & g[row_col].isin(rows)], True) for c in cols)
        body += f'<tr class="tot"><td class="name">{_h.escape(total_row_label)}</td>{tds}<td class="name"></td></tr>'
    st.markdown(css() + f'<div class="ea-rx ea-rx-scroll"><table class="ea-hm"><tr><th class="l" style="--nw:{name_w};">{_h.escape(row_head)}</th>'
                f'{head}</tr>{body}</table></div>', unsafe_allow_html=True)


def day_time_grid(df: pd.DataFrame, metric: str = "Expectancy", min_n: int = 5) -> bool:
    """Weekday × four-hour block (mockup V3). The All column is the old
    day-of-week table; the All row is the time-of-day totals."""
    hrs = trade_hours(df)
    day_col = "DayName" if "DayName" in df.columns else ("Day" if "Day" in df.columns else None)
    if hrs is None or day_col is None:
        return False
    g = _counted(df.assign(__hr=hrs))
    g = g[g["__hr"].notna()].copy()
    if g.empty:
        return False
    g["__hr"] = g["__hr"].astype(int) % 24
    full = {d[:3].lower(): d for d in DAYS}
    g["__day"] = g[day_col].astype(str).str.strip().str[:3].str.lower().map(full)
    g = g[g["__day"].notna()]
    if g.empty:
        return False
    g["__blk"] = g["__hr"].map(lambda h: next(f"{a:02d}–{b:02d}" for a, b in BLOCKS if a <= h < b))
    days = [d for d in DAYS if d in set(g["__day"])]
    if not any(d in days for d in DAYS[5:]):
        days = [d for d in DAYS[:5] if d in days] or days
    blocks = [f"{a:02d}–{b:02d}" for a, b in BLOCKS]
    heat_grid(g, "__day", "__blk", days, blocks, metric=metric, min_n=min_n,
              row_labels={d: d[:3] for d in days},
              total_row_label="All days", total_col_label="All day")
    return True


SESSION_ORDER = ["Asia", "London", "New York"]


def setup_grid(counted: pd.DataFrame, model_col: str, session_col: str, models: list,
               metric: str = "Expectancy", min_n: int = 8) -> bool:
    """Entry model × session (mockup V2): does this setup work in this
    session? The All sessions column is the old entry-model table, the All
    models row the old session table."""
    if session_col not in counted.columns:
        return False
    g = _counted(counted)
    g = g.assign(__m=g[model_col].astype(str).str.strip(),
                 __s=g[session_col].astype(str).str.strip())
    g = g[~g["__s"].str.lower().isin(["", "nan", "none", "other"]) & g["__m"].isin(models)]
    sessions = [s for s in SESSION_ORDER if (g["__s"] == s).any()]
    sessions += sorted(s for s in g["__s"].unique() if s not in sessions)
    if g.empty or len(sessions) < 1:
        return False
    heat_grid(g, "__m", "__s", models, sessions, metric=metric, min_n=min_n,
              row_head="Entry model", total_row_label="All models",
              total_col_label="All sessions", name_w="210px")
    return True


def pair_grid(counted: pd.DataFrame, m1: pd.Series, m2: pd.Series,
              metric: str = "Expectancy", min_n: int = 5) -> bool:
    """Model 1 × Model 2 for double-confirmation journals: which pairs pay."""
    g = _counted(counted.assign(__m1=m1.values, __m2=m2.values))
    g = g[(g["__m1"] != "") & (g["__m2"] != "")]
    if g.empty:
        return False
    rows = list(g["__m1"].value_counts().index)
    cols = list(g["__m2"].value_counts().index)
    heat_grid(g, "__m1", "__m2", rows, cols, metric=metric, min_n=min_n,
              row_head="Model 1 ↓  ·  Model 2 →", total_row_label="Any model 1",
              total_col_label="Any model 2", name_w="210px")
    return True


# ── discipline hero (mockup V4) ──────────────────────────────────────────────
def _ring(score: int, size: int = 132) -> str:
    import math
    t = _tokens()
    r = size / 2 - 11
    c = 2 * math.pi * r
    col = GREEN if score >= 80 else ("#f59e0b" if score >= 60 else RED)
    return (f'<svg width="{size}" height="{size}" viewBox="0 0 {size} {size}" role="img" '
            f'aria-label="Discipline score {score}%">'
            f'<circle cx="{size/2}" cy="{size/2}" r="{r:.1f}" fill="none" stroke="{t["h1"]}" stroke-width="12"/>'
            f'<circle cx="{size/2}" cy="{size/2}" r="{r:.1f}" fill="none" stroke="{col}" stroke-width="12" '
            f'stroke-linecap="round" stroke-dasharray="{c * score / 100:.1f} {c:.1f}" '
            f'transform="rotate(-90 {size/2} {size/2})"/>'
            f'<text x="{size/2}" y="{size/2 + 5}" font-size="30" font-weight="800" fill="{t["ink"]}" '
            f'text-anchor="middle">{score}%</text>'
            f'<text x="{size/2}" y="{size/2 + 24}" font-size="11.5" fill="{t["muted"]}" '
            f'text-anchor="middle">clean trades</text></svg>')


def discipline_hero(score: int, n_clean: int, n_total: int, causes: list, checked: str,
                    clean_r=None, flag_r=None, days: list | None = None, facts: list | None = None) -> None:
    """Score ring, one sentence on what discipline is worth in R, the causes as
    pills and a strip of the last 90 trading days (green = nothing broke)."""
    t = _tokens()
    if n_clean == n_total:
        head = f"All {n_total} trades broke nothing"
    else:
        head = f"{n_clean} of {n_total} trades broke nothing"
    worth = ""
    if clean_r is not None and flag_r is not None:
        _cc = GREEN if clean_r >= 0 else RED
        _fc = GREEN if flag_r >= 0 else RED
        # say what the numbers say: in some journals the rule-breakers still
        # average more, and claiming a "gap" there would be false
        _end = ("That gap is what discipline is worth." if clean_r > flag_r + 0.05 else
                "So far, trades that broke something have done no worse on average; "
                "the rules guard the bad days more than the average.")
        worth = (f'<div class="ea-dh-s">Clean trades average <b style="color:{_cc}">{_h.escape(fmt_r(clean_r))}</b>; '
                 f'trades that broke something average <b style="color:{_fc}">{_h.escape(fmt_r(flag_r))}</b>. '
                 f'{_end}</div>')
    pills = "".join(f'<span class="ea-dh-p bad">{n} {_h.escape(lab)}</span>' for n, lab in causes)
    pills += "".join(f'<span class="ea-dh-p">{_h.escape(x)}</span>' for x in (facts or []))
    strip = ""
    if days:
        sq = "".join(f'<i title="{_h.escape(d)}" style="background:{GREEN if ok else "#f4a3a3"};"></i>'
                     for d, ok in days[-90:])
        strip = (f'<div class="ea-dh-strip"><div class="ea-dh-k">LAST {min(90, len(days))} TRADING DAYS</div>'
                 f'<div class="ea-dh-sq">{sq}</div>'
                 f'<div class="ea-rx-cap"><span><i style="background:{GREEN}"></i>nothing broke</span>'
                 f'<span><i style="background:#f4a3a3"></i>something broke</span></div></div>')
    s = f"""
.ea-dh{{display:flex;gap:26px;align-items:center;flex-wrap:wrap;margin:4px 0 8px;}}
.ea-dh-m{{flex:1 1 320px;min-width:0;}}
.ea-dh-h{{font-size:20px;font-weight:800;color:{t['ink']};}}
.ea-dh-s{{font-size:14.5px;color:{t['muted']};margin:4px 0 10px;line-height:1.5;}}
.ea-dh-s b{{font-weight:800;}}
.ea-dh-p{{display:inline-block;font-size:12.5px;font-weight:700;border-radius:999px;padding:3px 10px;margin:0 6px 6px 0;
  background:{t['h1']};color:{t['muted']};}}
.ea-dh-p.bad{{background:{'#3a1d22' if _dark() else '#fde8e8'};color:{'#fca5a5' if _dark() else '#7f1d1d'};}}
.ea-dh-c{{font-size:12.5px;color:{t['muted']};margin-top:4px;}}
.ea-dh-strip{{flex:0 1 330px;}}
.ea-dh-k{{font-size:11.5px;font-weight:700;letter-spacing:.07em;color:{t['muted']};margin-bottom:6px;}}
.ea-dh-sq{{display:grid;grid-template-columns:repeat(15,14px);gap:4px;}}
.ea-dh-sq i{{display:block;width:14px;height:14px;border-radius:3px;}}
"""
    body = (f'<div class="ea-rx ea-dh">{_ring(int(score))}<div class="ea-dh-m"><div class="ea-dh-h">{_h.escape(head)}</div>'
            f'{worth}<div>{pills}</div><div class="ea-dh-c">Checked on every trade: {_h.escape(checked)}</div></div>'
            f'{strip}</div>')
    st.markdown(css(s) + body, unsafe_allow_html=True)


# ── trade management (mockup V6) ─────────────────────────────────────────────
def _mgmt_frame(df: pd.DataFrame) -> pd.DataFrame | None:
    if df is None or df.empty or "MFE (R)" not in df.columns or "Closed RR" not in df.columns:
        return None
    g = pd.DataFrame({
        "mfe": pd.to_numeric(df["MFE (R)"], errors="coerce"),
        "r": pd.to_numeric(df["Closed RR"], errors="coerce"),
        "mae": (pd.to_numeric(df["MAE (R)"], errors="coerce") if "MAE (R)" in df.columns
                else pd.Series(float("nan"), index=df.index)),
    }, index=df.index)
    if "Date" in df.columns:
        g["when"] = pd.to_datetime(df["Date"], errors="coerce").dt.strftime("%a %d %b %Y")
    g = g[g["mfe"].notna() & g["r"].notna()]
    return g if len(g) >= 10 else None


def exit_whatif(g: pd.DataFrame) -> tuple[pd.DataFrame, float]:
    """The exit simulator's own model (pro_tabs._exit_optimizer): a target
    fills when MFE reached it, else a −1R stop if MAE got there, else the
    real exit. Returns (targets, actual net R)."""
    import numpy as np
    top = float(min(6.0, max(2.0, np.nanpercentile(g["mfe"], 95))))
    rows = []
    for T in np.round(np.arange(1.0, top + 0.01, 0.5), 2):
        sim = np.where(g["mfe"] >= T, T, np.where(g["mae"].fillna(0) <= -1, -1.0, g["r"]))
        rows.append({"T": float(T), "net": float(np.sum(sim)), "exp": float(np.mean(sim)),
                     "hit": float((g["mfe"] >= T).mean() * 100)})
    return pd.DataFrame(rows), float(g["r"].sum())


def management_overview(df: pd.DataFrame, styler) -> bool:
    """Four numbers, every trade as a dot (best price reached vs exit), and the
    exit simulator as bars against what you actually did. False when the
    journal has no MFE."""
    import altair as alt
    from edge_analysis.ui.mt5_tabs import _kpi
    g = _mgmt_frame(df)
    if g is None:
        return False
    t = _tokens()
    wins = g[g["r"] > 0.15]
    wpos = wins[wins["mfe"] > 0]
    cap = float((wpos["r"] / wpos["mfe"]).clip(0, 1).mean() * 100) if len(wpos) else float("nan")
    left = float((wins["mfe"] - wins["r"]).clip(lower=0).sum()) if len(wins) else 0.0
    gave = g[(g["mfe"] >= 1) & (g["r"] <= 0.15)]
    gave_r = float((gave["mfe"] - gave["r"]).sum())
    heat = float(wins["mae"].median()) if wins["mae"].notna().any() else float("nan")
    deep = int((wins["mae"] <= -0.8).sum())

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        _kpi("Captured on winners", "—" if cap != cap else f"{cap:.0f}%", "of the best price, on average")
    with c2:
        _kpi("Left on winners", f"{left:.1f}R", f"across {len(wins)} winners", "#b45309")
    with c3:
        _kpi("Gave it back", f"{len(gave)} trade{'s' if len(gave) != 1 else ''}",
             f"hit +1R, closed at BE or worse · {gave_r:.1f}R", RED if len(gave) else PURPLE)
    with c4:
        _kpi("Heat on winners", "—" if heat != heat else fmt_r(heat),
             f"median dip first · {deep} went past −0.8R")

    left_col, right_col = st.columns([1.35, 1])
    with left_col:
        st.markdown("#### Best price reached vs where you got out")
        xmax = float(max(2.0, min(g["mfe"].quantile(0.99) * 1.05, 12.0)))
        ymin = float(min(-1.3, g["r"].min() - 0.1))
        ymax = float(max(xmax, g["r"].max() + 0.2))
        pts = g.assign(x=g["mfe"].clip(upper=xmax),
                       kind=pd.cut(g["r"], [-1e9, -0.15, 0.15, 1e9], labels=["Loss", "BE", "Win"]).astype(str))
        vals = [dict(x=round(float(a), 2), y=round(float(b), 2), k=k, w=str(w))
                for a, b, k, w in zip(pts["x"], pts["r"], pts["kind"], pts.get("when", pd.Series("", index=pts.index)))]
        base = alt.Chart(alt.Data(values=vals))
        X = alt.X("x:Q", title="Best point the trade reached (MFE, R)", scale=alt.Scale(domain=[0, xmax]),
                  axis=alt.Axis(values=list(range(0, int(xmax) + 1)), format="d"))
        Y = alt.Y("y:Q", title="Closed (R)", scale=alt.Scale(domain=[ymin, ymax]),
                  axis=alt.Axis(values=list(range(int(ymin), int(ymax) + 1)), format="d"))
        zone = alt.Chart(alt.Data(values=[dict(x=1.0, x2=xmax, y=ymin, y2=0.15)])).mark_rect(
            color=RED, opacity=0.08).encode(x=X, x2="x2:Q", y=Y, y2="y2:Q")
        diag = alt.Chart(alt.Data(values=[dict(x=0.0, y=0.0), dict(x=xmax, y=xmax)])).mark_line(
            color=PURPLE, strokeDash=[5, 4], opacity=0.6).encode(x=X, y=Y)
        dots = base.mark_circle(size=46, opacity=0.62).encode(
            x=X, y=Y,
            color=alt.Color("k:N", legend=None, scale=alt.Scale(domain=["Win", "BE", "Loss"],
                                                                range=[GREEN, "#94a3b8", RED])),
            tooltip=[alt.Tooltip("w:N", title="Trade"), alt.Tooltip("x:Q", title="Best (R)"),
                     alt.Tooltip("y:Q", title="Closed (R)")])
        # between the scratch row (0R) and the stop row (−1R), clear of both
        lab = alt.Chart(alt.Data(values=[dict(x=xmax * 0.98, y=-0.5,
                                              t="went +1R, then closed at BE or worse")])).mark_text(
            align="right", fontSize=12, fontWeight="bold", color=RED).encode(x=X, y=Y, text="t:N")
        st.altair_chart(styler(alt.layer(zone, diag, dots, lab).properties(height=330)),
                        use_container_width=True)
        st.caption("One dot per trade. On the dashed line you got out at the best price; "
                   "the red zone is every trade that reached +1R and still closed at break-even or worse.")
    with right_col:
        st.markdown("#### What if you'd used a fixed target?")
        wf, actual = exit_whatif(g)
        mx = max([abs(x) for x in wf["net"]] + [abs(actual), 1e-9])
        rows = ""
        for _, w in wf.iterrows():
            pct = abs(w["net"]) / mx * 100
            rows += (f'<div class="ea-wf-r"><div class="ea-wf-l">Fixed {w["T"]:g}R</div>'
                     f'<div class="ea-wf-t"><div style="width:{pct:.0f}%;background:{"#94a3b8" if w["net"] >= 0 else RED};"></div></div>'
                     f'<div class="ea-wf-v"><b>{_h.escape(fmt_r(w["net"], 1))}</b> <span>hits {w["hit"]:.0f}%</span></div></div>')
        rows += (f'<div class="ea-wf-r you"><div class="ea-wf-l">What you did</div>'
                 f'<div class="ea-wf-t"><div style="width:{abs(actual) / mx * 100:.0f}%;background:{PURPLE};"></div></div>'
                 f'<div class="ea-wf-v"><b>{_h.escape(fmt_r(actual, 1))}</b></div></div>')
        best = wf.loc[wf["net"].idxmax()]
        if best["net"] > actual + 0.5:
            verdict = (f"A flat <b>{best['T']:g}R</b> target would have made <b>{_h.escape(fmt_r(best['net'], 1))}</b> "
                       f"on these trades, against your <b>{_h.escape(fmt_r(actual, 1))}</b>.")
        else:
            verdict = (f"No fixed target beats your own exits on these trades; the closest, "
                       f"<b>{best['T']:g}R</b>, fills on {best['hit']:.0f}% of them."
                       + (f" The leak is the <b>{len(gave)}</b> give-backs, not the target." if len(gave) else ""))
        extra = f"""
.ea-wf-r{{display:flex;align-items:center;gap:10px;margin:7px 0;}}
.ea-wf-r.you{{border-top:1px dashed {t['line']};padding-top:9px;margin-top:10px;}}
.ea-wf-l{{flex:0 0 92px;font-size:13.5px;font-weight:700;color:{t['ink']};}}
.ea-wf-r.you .ea-wf-l,.ea-wf-r.you .ea-wf-v b{{color:{PURPLE if not _dark() else '#a78bfa'};}}
.ea-wf-t{{flex:1;background:{t['h1']};border-radius:6px;height:16px;overflow:hidden;}}
.ea-wf-t div{{height:16px;border-radius:6px;}}
.ea-wf-v{{flex:0 0 118px;text-align:right;font-size:13.5px;color:{t['ink']};}}
.ea-wf-v span{{color:{t['muted']};font-size:12px;}}
.ea-wf-s{{font-size:13.5px;color:{t['muted']};margin-top:12px;line-height:1.5;}}
.ea-wf-s b{{color:{t['ink']};}}
"""
        st.markdown(css(extra) + f'<div class="ea-rx">{rows}<div class="ea-wf-s">{verdict}</div></div>',
                    unsafe_allow_html=True)
        st.caption("Same trades, same model as the exit simulator: a target fills if the trade "
                   "reached it before it closed, otherwise a −1R stop if it went there first.")
    return True


# ── weekly report card (mockup V7) ───────────────────────────────────────────
def week_report(label: str, headline: str, sub: str, grade: str | None, stats: list,
                days: list, keep: list, fix: list) -> None:
    """One card for the week: the conclusion as a sentence, four numbers,
    the week day by day, and what to keep and what to fix.
    stats: [(label, value, sub, colour)]; days: [(Mon, net R or None, n)];
    keep: [html]; fix: [(title, sub)]."""
    t = _tokens()
    tiles = "".join(f'<div class="ea-wk-k"><div class="l">{_h.escape(a)}</div>'
                    f'<div class="v" style="color:{c};">{_h.escape(str(v))}</div>'
                    f'<div class="s">{_h.escape(s)}</div></div>' for a, v, s, c in stats)
    mx = max([abs(r) for _, r, _ in days if r is not None] + [1e-9])
    cols = ""
    for d, r, n in days:
        up = dn = ""
        if r is not None:
            hgt = max(3.0, abs(r) / mx * 100)
            bar = f'<div class="b" style="height:{hgt:.0f}%;background:{GREEN if r >= 0 else RED};"></div>'
            if r >= 0:
                up = bar
            else:
                dn = bar
        val = "—" if r is None else fmt_r(r, 1)
        vc = t["few"] if r is None else (GREEN if r >= 0 else RED)
        cols += (f'<div class="ea-wk-d"><div class="u">{up}</div><div class="w">{dn}</div>'
                 f'<div class="x" style="color:{vc};">{_h.escape(val)}</div>'
                 f'<div class="y">{d} · {n}</div></div>')
    keep_html = "".join(f"<li>{k}</li>" for k in keep) or "<li>Nothing stood out either way.</li>"
    fix_html = "".join(f"<li><b>{_h.escape(a)}</b>{(' — ' + _h.escape(b)) if b else ''}</li>"
                       for a, b in fix) or "<li>Nothing to fix from this week's tags.</li>"
    badge = (f'<div class="ea-wk-g"><div class="l">PROCESS</div><div class="v">{_h.escape(grade)}</div></div>'
             if grade else "")
    extra = f"""
.ea-wk-top{{display:flex;justify-content:space-between;gap:16px;align-items:flex-start;}}
.ea-wk-e{{font-size:11.5px;font-weight:700;letter-spacing:.08em;color:{t['muted']};}}
.ea-wk-h{{font-size:23px;font-weight:800;color:{t['ink']};margin-top:3px;line-height:1.2;}}
.ea-wk-sub{{font-size:14.5px;color:{t['muted']};margin-top:4px;}}
.ea-wk-g{{text-align:center;background:{'#3a2a0c' if _dark() else '#fef3c7'};border-radius:14px;padding:8px 16px;flex:none;}}
.ea-wk-g .l{{font-size:10.5px;font-weight:800;letter-spacing:.08em;color:{'#fbbf24' if _dark() else '#92400e'};}}
.ea-wk-g .v{{font-size:30px;font-weight:800;line-height:1.1;color:{'#fbbf24' if _dark() else '#92400e'};}}
.ea-wk-ks{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin:14px 0 10px;}}
.ea-wk-k{{background:{t['soft']};border:1px solid {t['line']};border-radius:12px;padding:11px 14px;}}
.ea-wk-k .l{{font-size:11px;font-weight:700;letter-spacing:.06em;color:{t['muted']};text-transform:uppercase;}}
.ea-wk-k .v{{font-size:23px;font-weight:800;margin-top:1px;}}
.ea-wk-k .s{{font-size:12px;color:{t['muted']};}}
.ea-wk-ds{{display:flex;gap:6px;margin-top:4px;}}
.ea-wk-d{{flex:1;text-align:center;min-width:0;}}
.ea-wk-d .u,.ea-wk-d .w{{height:58px;display:flex;justify-content:center;}}
.ea-wk-d .u{{align-items:flex-end;border-bottom:1px solid {t['zero']};}}
.ea-wk-d .w{{align-items:flex-start;}}
.ea-wk-d .b{{width:38%;max-width:38px;border-radius:5px;}}
.ea-wk-d .x{{font-size:13px;font-weight:800;margin-top:2px;}}
.ea-wk-d .y{{font-size:11.5px;color:{t['muted']};}}
.ea-wk-kf{{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:12px;margin-top:14px;}}
.ea-wk-kf>div{{border:1px solid {t['line']};border-radius:12px;padding:12px 16px;background:{t['base']};}}
.ea-wk-kf h5{{margin:0 0 6px;font-size:15px;font-weight:800;color:{t['ink']};}}
.ea-wk-kf ul{{margin:0;padding-left:18px;font-size:14px;line-height:1.5;color:{t['ink']};}}
.ea-wk-kf li{{margin:2px 0;}}
.ea-wk-kf li b{{font-weight:700;}}
"""
    eyebrow = (" \u00b7 " + _h.escape(label.upper())) if label else ""
    html = (f'<div class="ea-rx"><div class="ea-wk-top"><div><div class="ea-wk-e">YOUR WEEK{eyebrow}</div>'
            f'<div class="ea-wk-h">{_h.escape(headline)}</div><div class="ea-wk-sub">{sub}</div></div>{badge}</div>'
            f'<div class="ea-wk-ks">{tiles}</div><div class="ea-wk-ds">{cols}</div>'
            f'<div class="ea-wk-kf"><div><h5 style="color:{GREEN};">✓ Keep doing</h5><ul>{keep_html}</ul></div>'
            f'<div><h5 style="color:{RED};">✗ Fix next week</h5><ul>{fix_html}</ul></div></div></div>')
    st.markdown(css(extra) + html, unsafe_allow_html=True)


# ── the whole record (mockup V1, added under Performance's own cards) ───────
def tiles(stats: list) -> None:
    """A row of number tiles that wraps on phones. stats: [(label, value, sub, colour)]."""
    t = _tokens()
    extra = f"""
.ea-tl{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin:4px 0 14px;}}
.ea-tl>div{{background:{t['soft']};border:1px solid {t['line']};border-radius:12px;padding:11px 14px;}}
.ea-tl .l{{font-size:11px;font-weight:700;letter-spacing:.06em;color:{t['muted']};text-transform:uppercase;}}
.ea-tl .v{{font-size:22px;font-weight:800;margin-top:1px;}}
.ea-tl .s{{font-size:12px;color:{t['muted']};line-height:1.35;}}
"""
    body = "".join(f'<div><div class="l">{_h.escape(a)}</div><div class="v" style="color:{c};">{_h.escape(str(v))}</div>'
                   f'<div class="s">{_h.escape(s)}</div></div>' for a, v, s, c in stats)
    st.markdown(css(extra) + f'<div class="ea-rx ea-tl">{body}</div>', unsafe_allow_html=True)


def record_stats(r: pd.Series, dates: pd.Series) -> dict:
    """Headline numbers over every trade, in order. Wins are > +0.15R and
    losses < −0.15R; a scratch breaks no streak."""
    r = pd.to_numeric(r, errors="coerce").reset_index(drop=True)
    dates = pd.to_datetime(dates).reset_index(drop=True)
    ok = r.notna()
    r, dates = r[ok].reset_index(drop=True), dates[ok].reset_index(drop=True)
    wins, losses = r[r > 0.15], r[r < -0.15]
    n = len(r)
    cum = r.cumsum()
    dd = cum - cum.cummax()
    out = dict(n=n, net=float(r.sum()), exp=float(r.mean()) if n else 0.0,
               win=100.0 * len(wins) / n if n else 0.0, be=100.0 * (n - len(wins) - len(losses)) / n if n else 0.0,
               pf=(float(wins.sum() / -losses.sum()) if len(losses) and losses.sum() else None),
               avg_w=float(wins.mean()) if len(wins) else None, avg_l=float(losses.mean()) if len(losses) else None,
               maxdd=float(dd.min()) if n else 0.0, dd_from=None, dd_to=None, dd_back=None)
    if n and out["maxdd"] < 0:
        i_to = int(dd.idxmin())
        i_from = int(cum.iloc[: i_to + 1].idxmax())
        back = cum.iloc[i_to:][cum.iloc[i_to:] >= cum.iloc[i_from]]
        out.update(dd_from=dates[i_from], dd_to=dates[i_to],
                   dd_back=(dates[int(back.index[0])] if len(back) else None))
    seq = [1 if x > 0.15 else (-1 if x < -0.15 else 0) for x in r]
    bw = bl = cw = cl = 0
    for s in seq:
        if s == 1:
            cw, cl = cw + 1, 0
        elif s == -1:
            cl, cw = cl + 1, 0
        bw, bl = max(bw, cw), max(bl, cl)
    cur = 0
    for s in reversed(seq):
        if s == 0:
            continue
        if cur == 0 or (s > 0) == (cur > 0):
            cur += s
        else:
            break
    out.update(best_w=bw, best_l=bl, cur=cur)
    return out


def _calendar(g: pd.DataFrame, month: pd.Period) -> str:
    t = _tokens()
    day = g.groupby(g["__d"].dt.normalize())["__r"].agg(["sum", "size"])
    start = month.start_time.normalize()
    days = pd.date_range(start, month.end_time.normalize())
    today = pd.Timestamp.now().normalize()
    head = "".join(f'<div class="h">{d}</div>' for d in ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"])
    cells = '<div></div>' * int(start.weekday())
    for x in days:
        if x in day.index:
            s, k = float(day.loc[x, "sum"]), int(day.loc[x, "size"])
            bg, fg = heat(s, 3.0)
            inner = f'<div class="v">{_h.escape(fmt_r(s, 1))}</div><div class="n">{k} trade{"s" if k != 1 else ""}</div>'
            cells += f'<div class="c" style="background:{bg};color:{fg};"><div class="d">{x.day}</div>{inner}</div>'
        else:
            quiet = x.weekday() >= 5 or x > today
            cells += (f'<div class="c e{" q" if quiet else ""}"><div class="d">{x.day}</div></div>')
    extra = f"""
.ea-cal{{display:grid;grid-template-columns:repeat(7,minmax(0,1fr));gap:5px;}}
.ea-cal .h{{font-size:11.5px;font-weight:700;color:{t['muted']};text-align:center;}}
.ea-cal .c{{border-radius:9px;min-height:62px;padding:5px 7px;border:1px solid {t['line']};}}
.ea-cal .c.e{{background:{t['base']};color:{t['few']};}}
.ea-cal .c.e.q{{background:{t['soft']};}}
.ea-cal .d{{font-size:11.5px;font-weight:700;opacity:.8;}}
.ea-cal .v{{font-size:15px;font-weight:800;margin-top:2px;white-space:nowrap;}}
.ea-cal .n{{font-size:10.5px;opacity:.85;}}
@media (max-width:640px){{.ea-cal .c{{min-height:46px;padding:3px 4px;}} .ea-cal .v{{font-size:11.5px;}} .ea-cal .n{{display:none;}}}}
"""
    return css(extra) + f'<div class="ea-rx ea-cal">{head}{cells}</div>'


def record_card(g: pd.DataFrame, styler) -> None:
    """Mockup V1 as one card under the month and all-time cards: six numbers,
    the whole equity curve with its drawdown, the month as a calendar, and
    where trades land. R only."""
    import altair as alt
    g = g.copy()
    g["__r"] = pd.to_numeric(g["Closed RR"] if "Closed RR" in g.columns else g.get("PnL_from_RR"), errors="coerce")
    g["__d"] = pd.to_datetime(g["__Date"])
    g = g[g["__r"].notna()].sort_values("__d").reset_index(drop=True)
    if len(g) < 5:
        return
    s = record_stats(g["__r"], g["__d"])
    f = lambda d: d.strftime("%d %b") if d is not None else ""
    dd_sub = ("no drawdown yet" if s["maxdd"] >= 0 else
              f"{f(s['dd_from'])} → {f(s['dd_to'])}, " + (f"back by {f(s['dd_back'])}" if s["dd_back"] is not None
                                                             else "not yet recovered"))
    cur = s["cur"]
    streak_v = ("none" if cur == 0 else f"{abs(cur)} {'win' if cur > 0 else 'loss'}{'' if abs(cur) == 1 else ('s' if cur > 0 else 'es')}")
    tiles([
        ("Net", fmt_r(s["net"], 1), f"{s['n']} trades", GREEN if s["net"] >= 0 else RED),
        ("Expectancy", fmt_r(s["exp"]), "per trade", GREEN if s["exp"] >= 0 else RED),
        ("Win rate", f"{s['win']:.0f}%", f"of all trades · {s['be']:.0f}% break-even", "#4800ff"),
        ("Profit factor", "—" if s["pf"] is None else f"{s['pf']:.2f}",
         (f"avg win {fmt_r(s['avg_w'], 1)} · loss {fmt_r(s['avg_l'], 1)}" if s["avg_w"] is not None and s["avg_l"] is not None else ""),
         "#4800ff"),
        ("Max drawdown", fmt_r(s["maxdd"], 1), dd_sub, RED if s["maxdd"] < 0 else GREEN),
        ("Streak", streak_v, f"longest: {s['best_w']} wins · {s['best_l']} losses",
         GREEN if cur > 0 else (RED if cur < 0 else "#64748b")),
    ])
    # equity curve + drawdown, one trade per point, shared time axis
    cum = g["__r"].cumsum()
    eq = pd.DataFrame({"Date": g["__d"].dt.strftime("%Y-%m-%dT%H:%M:%S"), "R": cum.round(2),
                       "DD": (cum - cum.cummax()).round(2), "Trade": g["__r"].round(2)})
    vals = eq.to_dict("records")
    x = alt.X("Date:T", title=None, axis=alt.Axis(format="%b %y", labelOverlap=True, tickCount="month"))
    area = alt.Chart(alt.Data(values=vals)).mark_area(color=PURPLE, opacity=0.08).encode(x=x, y=alt.Y("R:Q", title="Running R"))
    line = alt.Chart(alt.Data(values=vals)).mark_line(color=PURPLE, strokeWidth=2).encode(
        x=x, y=alt.Y("R:Q", title="Running R"),
        tooltip=[alt.Tooltip("Date:T", format="%a %d %b %Y"), alt.Tooltip("Trade:Q", title="This trade (R)"),
                 alt.Tooltip("R:Q", title="Running R")])
    ddc = alt.Chart(alt.Data(values=vals)).mark_area(color=RED, opacity=0.25, line={"color": RED, "strokeWidth": 1}).encode(
        x=alt.X("Date:T", title=None, axis=alt.Axis(format="%b %y", labelOverlap=True, tickCount="month")),
        y=alt.Y("DD:Q", title="Drawdown"), tooltip=[alt.Tooltip("Date:T", format="%a %d %b %Y"),
                                                     alt.Tooltip("DD:Q", title="Below peak (R)")])
    st.markdown("#### The whole record")
    st.caption("Running R across every trade, with how far below its last peak it sat underneath.")
    chart = alt.vconcat(alt.layer(area, line).properties(height=230), ddc.properties(height=80),
                        spacing=6).resolve_scale(x="shared")
    st.altair_chart(styler(chart), use_container_width=True)

    c1, c2 = st.columns(2)
    with c1:
        months = sorted(g["__d"].dt.to_period("M").unique())[::-1]
        lab = {m.strftime("%B %Y"): m for m in months}
        st.markdown("#### Calendar")
        pick = st.selectbox("Month", list(lab), index=0, key="ea_cal_month", label_visibility="collapsed")
        st.markdown(_calendar(g, lab[pick]), unsafe_allow_html=True)
        _dsum = g.groupby(g["__d"].dt.normalize())["__r"].sum()
        st.caption(f"Green days {int((_dsum > 0).sum())} of {len(_dsum)} traded, all time.")
    with c2:
        import numpy as np
        st.markdown("#### Where your trades land")
        top = float(max(1.25, np.ceil((g["__r"].quantile(0.99) + 0.25) * 2) / 2))
        edges = np.arange(-1.25, top + 0.26, 0.5)
        clipped = g["__r"].clip(edges[0] + 0.01, edges[-1] - 0.01)
        cnt, _ = np.histogram(clipped, bins=edges)
        hv = [dict(c=float(edges[i] + 0.25), lab=("0" if abs(edges[i] + 0.25) < 0.01 else f"{edges[i] + 0.25:+.1f}"),
                   n=int(cnt[i]), k=("Stops" if edges[i] + 0.25 <= -0.5 else ("Winners" if edges[i] + 0.25 >= 0.5 else "Scratch")))
              for i in range(len(cnt))]
        order = [h["lab"] for h in hv]
        hx = alt.X("lab:N", sort=order, title="R per trade", axis=alt.Axis(labelAngle=0))
        bars = alt.Chart(alt.Data(values=hv)).mark_bar(cornerRadiusTopLeft=4, cornerRadiusTopRight=4).encode(
            x=hx, y=alt.Y("n:Q", title="Trades"),
            color=alt.Color("k:N", legend=None, scale=alt.Scale(domain=["Stops", "Scratch", "Winners"],
                                                                range=[RED, "#94a3b8", GREEN])),
            tooltip=[alt.Tooltip("lab:N", title="Around (R)"), alt.Tooltip("n:Q", title="Trades")])
        txt = alt.Chart(alt.Data(values=[h for h in hv if h["n"]])).mark_text(dy=-7, fontSize=11, fontWeight="bold", color="#64748b").encode(
            x=hx, y="n:Q", text="n:Q")
        st.altair_chart(styler(alt.layer(bars, txt).properties(height=250)), use_container_width=True)
        st.caption(f"Median trade {fmt_r(float(g['__r'].median()))}. Most trades are a stop or a scratch; "
                   "the edge lives in the right-hand tail.")
