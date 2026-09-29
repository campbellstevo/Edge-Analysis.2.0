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
import math
import re

import pandas as pd
import streamlit as st
from edge_analysis.core.clock import local_now

GREEN, RED, PURPLE = "#16a34a", "#dc2626", "#4800ff"
# break-even dots and their legend: 3.6:1 on white (the old #94a3b8 was 2.6:1)
BE_GREY = "#7c8799"
DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
BLOCKS = [(0, 4), (4, 8), (8, 12), (12, 16), (16, 20), (20, 24)]
METRICS = ["Expectancy", "Net R", "Win rate"]


def _dark() -> bool:
    return st.session_state.get("ea_theme_pref") == "dark"


def _tokens() -> dict:
    if _dark():
        return dict(ink="#e8ebf1", muted="#9aa4b4", line="#2a3040", soft="#1a1f2b",
                    base="#161b27", h1="#1f2533", h2="#262d3d", zero="#3a4356",
                    grey="#3a4256", few="#8c95a6", pos_fg="#dcfce7", neg_fg="#fee2e2")
    # "few" marks a thin sample; it stays readable (4.5:1+), just quieter
    return dict(ink="#0f172a", muted="#64748b", line="#e6e8f0", soft="#f8fafc",
                base="#ffffff", h1="#f1f5f9", h2="#e8edf3", zero="#cbd5e1",
                grey="#cbd5e1", few="#687184", pos_fg="#14532d", neg_fg="#7f1d1d")


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
.ea-hb{{display:flex;min-width:calc(var(--hbn,24) * 32px);gap:3px;}}
@media (max-width:640px){{.ea-hb{{min-width:0;gap:1px;}}
  .ea-hb-v{{writing-mode:vertical-rl;transform:rotate(180deg);font-size:9px;line-height:1;margin:2px 0;}}
  .ea-hb-h{{font-size:9.5px;}} .ea-hb-n{{font-size:9px;}}
  .ea-hm{{min-width:0 !important;border-spacing:2px;}} .ea-hm td{{font-size:12px !important;padding:6px 1px !important;}}
  .ea-hm td small{{font-size:9.5px;}} .ea-hm th{{font-size:10.5px;padding:2px 1px;}}}}
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


def _rgb(h: str) -> tuple:
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _lum(c: tuple) -> float:
    def ch(v):
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = c
    return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)


def contrast(a: str, b: str) -> float:
    la, lb = _lum(_rgb(a)), _lum(_rgb(b))
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def heat(v, cap: float = 1.0) -> tuple[str, str]:
    """Diverging cell colour (background, text) for a value around zero.
    Solid colours blended from a pale tint to a deep shade, and the text is
    whichever of white or ink reads better on that cell: white on a
    half-transparent red measured 2.3:1 (26 Sep sweep)."""
    t = _tokens()
    if v is None or pd.isna(v):
        return t["h1"], t["muted"]
    x = max(-1.0, min(1.0, float(v) / (cap or 1.0)))
    k = 0.12 + 0.88 * abs(x)
    if _dark():
        lo, hi = ("#17271f", "#15803d") if x >= 0 else ("#2a1a1f", "#b91c1c")
    else:
        lo, hi = ("#e8f7ee", "#15803d") if x >= 0 else ("#fdecec", "#b91c1c")
    a, b = _rgb(lo), _rgb(hi)
    bg = "#" + "".join(f"{round(a[i] + (b[i] - a[i]) * k):02x}" for i in range(3))
    dark_ink = "#0f172a" if not _dark() else "#0b1020"
    light_ink = "#ffffff"
    fg = light_ink if contrast(light_ink, bg) >= contrast(dark_ink, bg) else dark_ink
    return bg, fg


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
def trade_window(hours: set, pad: int = 1) -> list:
    """The hours worth drawing: the shortest run around the clock that holds
    every traded hour, an hour either side. An evening trader got a phone
    chart opening on 00–10, empty (26 Sep). All 24 only when the gap is under
    three hours."""
    hs = sorted(int(h) % 24 for h in hours)
    if not hs:
        return list(range(24))
    # the longest empty stretch between traded hours (wrapping) is left out
    gaps = [((hs[(i + 1) % len(hs)] - hs[i]) % 24 or 24, hs[i]) for i in range(len(hs))]
    gap, before = max(gaps)
    start = (before + gap) % 24          # first traded hour after the gap
    span = 24 - gap + 1
    if span + 2 * pad >= 22:
        return list(range(24))
    return [(start - pad + i) % 24 for i in range(span + 2 * pad)]


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
    # (29 Sep) one readable hour set the scale on a young journal, so every
    # thin hour hit full height: a 1-trade -0.26R bar stood as tall as the
    # best. Readable hours set it once there are three of them
    mx = max(vals) if len(vals) >= 3 else max([abs((_metric_val(s, metric) or 0) - (base_win if metric == "Win rate" else 0))
                                               for s in by.values()] or [1.0])
    mx = mx or 1.0
    t = _tokens()
    cols = []
    _hours = trade_window(set(by))
    for h in _hours:
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
            bar = f'<div class="ea-hb-bar" style="height:{pct * 0.72:.0f}%;background:{col};"></div>'
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
    st.markdown(css() + f'<div class="ea-rx ea-rx-scroll"><div class="ea-hb" style="--hbn:{len(_hours)};">'
                f'{"".join(cols)}</div></div>' + cap, unsafe_allow_html=True)
    return True


# ── generic heat grid ────────────────────────────────────────────────────────
def heat_grid(g: pd.DataFrame, row_col: str, col_col: str, rows: list, cols: list,
              metric: str = "Expectancy", min_n: int = 5, row_head: str = "",
              col_labels: dict | None = None, row_labels: dict | None = None, totals: bool = True,
              total_row_label: str = "All", total_col_label: str = "All",
              name_w: str = "72px", col_order_by_n: bool = False, total_col: bool = True) -> None:
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
    if totals and total_col:
        head += f"<th>{_h.escape(total_col_label)}</th>"
    body = ""
    for r in rows:
        rg = g[g[row_col] == r]
        tds = "".join(_cell(rg[rg[col_col] == c]) for c in cols)
        if totals and total_col:
            tds += _cell(rg[rg[col_col].isin(cols)], True)
        body += f'<tr><td class="name">{_h.escape(str((row_labels or {}).get(r, r)))}</td>{tds}</tr>'
    if totals:
        tds = "".join(_cell(g[(g[col_col] == c) & g[row_col].isin(rows)], True) for c in cols)
        body += (f'<tr class="tot"><td class="name">{_h.escape(total_row_label)}</td>{tds}'
                 + ('<td class="name"></td>' if total_col else '') + '</tr>')
    st.markdown(css() + f'<div class="ea-rx ea-rx-scroll"><table class="ea-hm"><tr><th class="l" style="--nw:{name_w};">{_h.escape(row_head)}</th>'
                f'{head}</tr>{body}</table></div>', unsafe_allow_html=True)


def day_time_grid(df: pd.DataFrame, metric: str = "Expectancy", min_n: int = 5,
                  day_totals: bool = True) -> bool:
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
              total_row_label="All days", total_col_label="All day", total_col=day_totals)
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


PAIR_FEW = 5          # under this many trades a pair is shown faded: too few to read


def pair_rows(counted: pd.DataFrame, m1: pd.Series, m2: pd.Series) -> list[dict]:
    """Every structure → trigger pair with its trades, best R a trade first."""
    g = _counted(counted.assign(__m1=m1.values, __m2=m2.values))
    g = g[(g["__m1"] != "") & (g["__m2"] != "")]
    out = []
    for (a, b), grp in g.groupby(["__m1", "__m2"]):
        out.append(dict(m1=str(a), m2=str(b), n=int(len(grp)), exp=float(grp["__r"].mean()),
                        net=float(grp["__r"].sum()),
                        won=int(grp["Outcome"].eq("Win").sum()) if "Outcome" in grp.columns else None,
                        idx=grp.index))
    out.sort(key=lambda d: (-d["exp"], -d["n"]))
    return out


def pair_tests(counted: pd.DataFrame, m1: pd.Series, m2: pd.Series, rows: list | None = None) -> set:
    """The (m1, m2, "good"|"bad") pairs that beat chance, Holm across every
    readable pair both ways. Entry's pair rows and Focus's best setup read the
    same family, so they name the same pair (28 Sep: Focus ranked by total,
    Entry by R a trade, and named two different bests)."""
    rows = pair_rows(counted, m1, m2) if rows is None else rows
    from edge_analysis.digest import _perm_p, _holm_pass
    g = _counted(counted.assign(__m1=m1.values, __m2=m2.values))
    g = g[(g["__m1"] != "") & (g["__m2"] != "")]
    x, total = g["__r"], int(len(g))
    keys, ps = [], []
    for r in rows:
        if PAIR_FEW <= r["n"] < total - 1:
            mask = x.index.isin(r["idx"])
            for d in ("good", "bad"):
                keys.append((r["m1"], r["m2"], d))
                ps.append(_perm_p(x, pd.Series(mask, index=x.index), lower=d == "bad"))
    return {keys[i] for i in _holm_pass(ps)} if ps else set()


def ranked_rows(rows: list[dict], names: list[str], head: str, col_head: str,
                cap: bool = True) -> None:
    """The plain ranked rows (27 Sep): a sentence, then one row per group —
    its name (already escaped HTML), R a trade as a bar from break-even,
    trades, wins and total in words. Rows under PAIR_FEW trades are dashed."""
    t = _tokens()
    pos, neg = ("#4ade80", "#f87171") if _dark() else (GREEN, RED)
    span = max(0.25, max(abs(r["exp"]) for r in rows))
    body = ""
    for r, name in zip(rows, names):
        w = min(50.0, abs(r["exp"]) / span * 50.0)
        col = pos if r["exp"] > 0.005 else (neg if r["exp"] < -0.005 else t["grey"])
        left = 50.0 if r["exp"] >= 0 else 50.0 - w
        won = "" if r.get("won") is None else f" · {r['won']} won"
        few = " few" if r["n"] < PAIR_FEW else ""
        body += (f'<div class="ea-pl-row{few}">'
                 f'<div class="ea-pl-n">{name}</div>'
                 f'<div class="ea-pl-bar" aria-hidden="true"><s></s>'
                 f'<i style="left:{left:.1f}%;width:{max(w, 0.8):.1f}%;background:{col}"></i></div>'
                 f'<div class="ea-pl-v"><b style="color:{col if col != t["grey"] else t["ink"]}">'
                 f'{_h.escape(fmt_r(r["exp"]))}</b> a trade'
                 f'<div>{r["n"]} trade{"s" if r["n"] != 1 else ""}{won} · {_h.escape(fmt_r(r["net"], 1))} total</div></div>'
                 f'</div>')
    extra = f"""
.ea-pl-head{{font-size:15px;line-height:1.5;margin:0 0 12px;color:{t['ink']};}}
.ea-pl-l{{font-size:11px;font-weight:700;color:{t['few']};white-space:nowrap;}}
.ea-pl-cols,.ea-pl-row{{display:grid;grid-template-columns:minmax(0,1.25fr) minmax(0,1fr) 170px;gap:14px;align-items:center;}}
.ea-pl-cols{{font-size:11px;font-weight:800;letter-spacing:.06em;text-transform:uppercase;color:{t['muted']};
  padding:0 12px 6px;}}
.ea-pl-row{{background:{t['soft']};border:1px solid {t['line']};border-radius:10px;padding:10px 12px;margin:0 0 6px;}}
.ea-pl-row.few{{background:transparent;border-style:dashed;}}
.ea-pl-row.few .ea-pl-n span{{color:{t['few']};}}
.ea-pl-row.few .ea-pl-bar i{{opacity:.5;}}
.ea-pl-n{{font-size:14.5px;font-weight:700;color:{t['ink']};min-width:0;}}
.ea-pl-n em{{font-style:normal;font-weight:600;font-size:12.5px;color:{t['muted']};margin:0 7px;}}
.ea-pl-n small.ea-pl-tf{{display:block;font-size:12px;font-weight:600;color:{t['muted']};margin-top:3px;}}
.ea-pl-bar{{position:relative;height:12px;border-radius:6px;background:{t['h1']};}}
.ea-pl-bar s{{position:absolute;left:50%;top:-3px;bottom:-3px;width:2px;margin-left:-1px;background:{t['zero']};}}
.ea-pl-bar i{{position:absolute;top:0;bottom:0;border-radius:6px;}}
.ea-pl-v{{font-size:13px;color:{t['muted']};text-align:right;white-space:nowrap;}}
.ea-pl-v b{{font-size:16px;font-weight:800;}}
.ea-pl-v div{{font-size:12.5px;margin-top:1px;}}
@media (max-width:640px){{
 .ea-pl-cols{{display:none;}}
 .ea-pl-row{{grid-template-columns:minmax(0,1fr) auto;gap:6px 12px;}}
 .ea-pl-n{{grid-column:1 / -1;}}
 .ea-pl-v{{text-align:right;}}
}}
"""
    top = f'<div class="ea-pl-head">{head}</div>' if head else ""
    foot = (f'<div class="ea-rx-cap">Best first. Dashed rows have under {PAIR_FEW} trades — too few to read yet. '
            f'The centre line is break-even.</div>') if cap else '<div style="height:10px"></div>'
    st.markdown(css(extra) + f'<div class="ea-rx">{top}'
                f'<div class="ea-pl-cols"><span>{_h.escape(col_head)}</span><span>R per trade</span>'
                f'<span style="text-align:right">Result</span></div>{body}{foot}</div>',
                unsafe_allow_html=True)


def group_rows(g: pd.DataFrame, labels: pd.Series) -> list[dict]:
    """One row per label of a _counted frame, best R a trade first."""
    out = []
    for v, grp in g.groupby(labels):
        out.append(dict(m=str(v), n=int(len(grp)), exp=float(grp["__r"].mean()), net=float(grp["__r"].sum()),
                        won=int(grp["Outcome"].eq("Win").sum()) if "Outcome" in grp.columns else None,
                        idx=grp.index))
    out.sort(key=lambda r: (-r["exp"], -r["n"]))
    return out


TIMING_RICH = 60      # below this many trades the hour and day × time charts are mostly empty cells


def when_board(df: pd.DataFrame, sessions: bool = True, verdicts: bool = True,
               days: bool = True) -> bool:
    """Round 14 ("When you trade", 5/10): one sentence, then sessions and
    weekdays as the plain ranked rows. On a young journal the hour bars were
    all grey and the day × time grid mostly hatched; those charts now wait
    in an expander (tabs._timing_reshaped). Claims are Holm-tested across
    every session and day, both directions. False when there's nothing to
    group by."""
    if df is None or df.empty:
        return False
    g = _counted(df)
    total = int(len(g))
    blocks = []
    if sessions:
        sc = next((c for c in ("Session Norm", "Session") if c in g.columns), None)
        if sc:
            lab = g[sc].map(_txt)
            if (lab != "").sum() >= 3 and lab[lab != ""].nunique() >= 2:
                blocks.append(("Session", "sessions", group_rows(g[lab != ""], lab[lab != ""])))
    day_col = "DayName" if "DayName" in g.columns else ("Day" if "Day" in g.columns else None)
    if day_col and days:
        full = {d[:3].lower(): d for d in DAYS}
        dl = g[day_col].map(_txt).str[:3].str.lower().map(full)
        if dl.notna().sum() >= 3 and dl.dropna().nunique() >= 2:
            blocks.append(("Day", "days", group_rows(g[dl.notna()], dl[dl.notna()])))
    if not blocks:
        return False
    from edge_analysis.digest import _perm_p, _holm_pass
    x = g["__r"]
    keys, ps = [], []
    for kind, _w, rows in blocks:
        for r in rows:
            if PAIR_FEW <= r["n"] < total - 1:
                m = pd.Series(x.index.isin(r["idx"]), index=x.index)
                for d in ("good", "bad"):
                    keys.append((kind, r["m"], d))
                    ps.append(_perm_p(x, m, lower=d == "bad"))
    passed = {keys[i] for i in _holm_pass(ps)} if ps else set()

    def lab_(kind, r, d):
        return "beats chance" if (kind, r["m"], d) in passed else "early read"

    def said(kind, r, d):
        return verdicts or (kind, r["m"], d) in passed

    bits = []
    for kind, word, rows in blocks:
        ok = [r for r in rows if r["n"] >= 3]
        if not ok:
            continue
        best, worst = ok[0], ok[-1]
        part = []
        if best["exp"] > 0 and said(kind, best, "good"):
            part.append(f"<b>{_h.escape(best['m'])}</b> leads at {_h.escape(fmt_r(best['exp']))} a trade over "
                        f"{best['n']} <span class='ea-pl-l'>{lab_(kind, best, 'good')}</span>")
        if worst is not best and worst["exp"] < 0 and said(kind, worst, "bad"):
            part.append(f"<b>{_h.escape(worst['m'])}</b> costs {_h.escape(fmt_r(worst['exp']))} a trade over "
                        f"{worst['n']} <span class='ea-pl-l'>{lab_(kind, worst, 'bad')}</span>")
        if part:
            bits.append(("By session: " if kind == "Session" else "By day: ") + "; ".join(part))
    head = (". ".join(bits) + ".") if bits else "Each row is what trades in that slot paid, best first."
    for i, (kind, _w, rows) in enumerate(blocks):
        ranked_rows(rows, [f"<span>{_h.escape(r['m'])}</span>" for r in rows], head if i == 0 else "", kind,
                    cap=i == len(blocks) - 1)
    return True


STATE_MIN = 3         # a second state needs this many trades before states are compared


def state_board(df: pd.DataFrame, col: str = "Mental State", verdicts: bool = True,
                title: str = "Mental state", relabel=None,
                thin: str = "keep logging the off days honestly and this becomes a comparison",
                noun: str = "state") -> bool:
    """Round 13: how you felt against what the trade paid, for whatever words
    the journal uses. The old gate only knew Good / Okay / Bad; his journal
    and the demo say "Clear & Calm", so it drew nothing for anyone. With one
    state and no real alternative the honest read is one line, not a
    comparison. False when under 3 trades carry a state."""
    if df is None or df.empty or col not in df.columns:
        return False
    g = _counted(df)
    lab = g[col].map(_txt)
    if relabel:
        # a Yes/No tag reads as words ("A+" / "Not A+"), whatever the journal stores
        lab = lab.map(lambda v: relabel.get(v.lower(), v) if v else v)
    untagged = int((lab == "").sum())
    g, lab = g[lab != ""], lab[lab != ""]
    total = int(len(g))
    if total < 3:
        return False
    rows = group_rows(g, lab)
    by_n = sorted(rows, key=lambda r: -r["n"])
    t = _tokens()
    st.markdown(f"### {title}")
    tail = f" {untagged} trade{'s have' if untagged != 1 else ' has'} no {noun} logged." if untagged else ""
    if len(by_n) == 1 or by_n[1]["n"] < STATE_MIN:
        top, rest = by_n[0], by_n[1:]
        s = (f"<b>{top['n']} of {total}</b> tagged trades were <b>{_h.escape(top['m'])}</b>, "
             f"averaging {_h.escape(fmt_r(top['exp']))} a trade.")
        if rest:
            s += " The rest: " + "; ".join(
                f"<b>{_h.escape(r['m'])}</b>, {r['n']} trade{'s' if r['n'] != 1 else ''} at "
                f"{_h.escape(fmt_r(r['exp']))}" for r in rest) + "."
        s += (f" No other {noun} has {STATE_MIN} trades yet, so there's nothing to compare — "
              f"{thin}." + tail)
        st.markdown(css(f".ea-ms1{{font-size:15px;line-height:1.55;color:{t['ink']};background:{t['soft']};"
                        f"border:1px solid {t['line']};border-radius:10px;padding:12px 14px;margin:2px 0 6px;}}")
                    + f'<div class="ea-rx"><div class="ea-ms1">{s}</div></div>', unsafe_allow_html=True)
        return True
    from edge_analysis.digest import _perm_p, _holm_pass
    x = g["__r"]
    keys, ps = [], []
    for r in rows:
        if PAIR_FEW <= r["n"] < total - 1:
            m = pd.Series(x.index.isin(r["idx"]), index=x.index)
            for d in ("good", "bad"):
                keys.append((r["m"], d))
                ps.append(_perm_p(x, m, lower=d == "bad"))
    passed = {keys[i] for i in _holm_pass(ps)} if ps else set()
    rows.sort(key=lambda r: (-r["exp"], -r["n"]))
    ok = [r for r in rows if r["n"] >= STATE_MIN]
    bits = []
    best, worst = ok[0], ok[-1]
    lab_ = lambda r, d: "beats chance" if (r["m"], d) in passed else "early read"  # noqa: E731
    if best["exp"] > 0 and (verdicts or (best["m"], "good") in passed):
        bits.append(f"<b>{_h.escape(best['m'])}</b> trades average {_h.escape(fmt_r(best['exp']))} over "
                    f"{best['n']} <span class='ea-pl-l'>{lab_(best, 'good')}</span>")
    if worst is not best and worst["exp"] < best["exp"] and (verdicts or (worst["m"], "bad") in passed):
        bits.append(f"<b>{_h.escape(worst['m'])}</b> {_h.escape(fmt_r(worst['exp']))} over {worst['n']} "
                    f"<span class='ea-pl-l'>{lab_(worst, 'bad')}</span>")
    if bits:
        head = "; ".join(bits) + "."
    else:
        _gap_r = ok[0]["exp"] - ok[-1]["exp"]
        head = (f"{total} tagged trades. " + ("So far they pay about the same." if abs(_gap_r) < 0.1 else
                                             "The gap between them isn't past chance yet."))
    head += tail
    ranked_rows(rows, [f"<span>{_h.escape(r['m'])}</span>" for r in rows], head, noun.capitalize())
    return True


def pair_list(counted: pd.DataFrame, m1: pd.Series, m2: pd.Series, verdicts: bool = True,
              col_head: str = "Structure, then trigger", tfpair: pd.Series | None = None) -> bool:
    """His note on the Model 1 × Model 2 grid (27 Sep): "this is hard to
    understand". One sentence saying what the pairs show, then every pair as
    one plain row — structure, then trigger, R a trade as a bar, trades and
    wins in words — best first. False when no trade carries both models."""
    rows = pair_rows(counted, m1, m2)
    if not rows:
        return False
    g = _counted(counted.assign(__m1=m1.values, __m2=m2.values))
    g = g[(g["__m1"] != "") & (g["__m2"] != "")]
    total = int(len(g))
    passed = pair_tests(counted, m1, m2, rows)

    def lab(r, d):
        return "beats chance" if (r["m1"], r["m2"], d) in passed else "early read"

    def said(r, d):
        return verdicts or (r["m1"], r["m2"], d) in passed

    def pair_html(r):
        return f"<b>{_h.escape(r['m1'])}</b> then <b>{_h.escape(r['m2'])}</b>"

    bits = []
    top2 = g["__m2"].value_counts()
    top1 = g["__m1"].value_counts()
    if len(top2) and top2.iloc[0] / total >= 0.75 and total >= 4:
        k = int(top2.iloc[0])
        bits.append((f"Every paired trade triggered on <b>{_h.escape(top2.index[0])}</b>" if k == total else
                     f"You trigger on <b>{_h.escape(top2.index[0])}</b> in {k} of {total} paired trades")
                    + (", so the structure is what changes" if len(top1) > 1 else ""))
    elif len(top1) and top1.iloc[0] / total >= 0.75 and total >= 4 and len(top2) > 1:
        k = int(top1.iloc[0])
        bits.append(f"Your structure is <b>{_h.escape(top1.index[0])}</b> in {k} of {total} paired trades, "
                    f"so the trigger is what changes")
    readable = [r for r in rows if r["n"] >= 3]
    if readable:
        best, worst = readable[0], readable[-1]
        if best["exp"] > 0 and said(best, "good"):
            bits.append(f"Best so far: {pair_html(best)}, {_h.escape(fmt_r(best['exp']))} a trade over "
                        f"{best['n']} <span class='ea-pl-l'>{lab(best, 'good')}</span>")
        if worst is not best and worst["exp"] < 0 and said(worst, "bad"):
            bits.append(f"Weakest: {pair_html(worst)}, {_h.escape(fmt_r(worst['exp']))} a trade over "
                        f"{worst['n']} <span class='ea-pl-l'>{lab(worst, 'bad')}</span>")
    else:
        bits.append("Every pair has under 3 trades so far, so none is a read yet")
    # the model pair and the timeframe pair are one setup (28 Sep check: the
    # cross was one sentence, "Most taken in full", with no rows): each pair's
    # row names the timeframes it was taken on, with their trades and R
    tf_line = {}
    if tfpair is not None:
        tp = tfpair.reindex(g.index).fillna("").astype(str)
        if (tp != "").any():
            for r in rows:
                x = g.loc[g.index.isin(r["idx"]), "__r"]
                by = x.groupby(tp.reindex(x.index).replace("", "no timeframes")).agg(["size", "mean"])
                by = by.sort_values(["size", "mean"], ascending=False)
                tf_line[(r["m1"], r["m2"])] = " \u00b7 ".join(
                    f"{_h.escape(str(k))}: {int(v['size'])} at {_h.escape(fmt_r(float(v['mean'])))}"
                    for k, v in by.iterrows())
    head = ". ".join(bits) + "."

    names = [f'<span>{_h.escape(r["m1"])}</span><em>then</em><span>{_h.escape(r["m2"])}</span>'
             + (f'<small class="ea-pl-tf">{tf_line[(r["m1"], r["m2"])]}</small>'
                if (r["m1"], r["m2"]) in tf_line else "")
             for r in rows]
    ranked_rows(rows, names, head, col_head)
    return True


# ── discipline hero (mockup V4) ──────────────────────────────────────────────
def _ring(score: int, size: int = 132, what: str = "clean trades", name: str = "Discipline score") -> str:
    import math
    t = _tokens()
    r = size / 2 - 11
    c = 2 * math.pi * r
    col = GREEN if score >= 80 else ("#f59e0b" if score >= 60 else RED)
    return (f'<svg width="{size}" height="{size}" viewBox="0 0 {size} {size}" role="img" '
            f'aria-label="{name} {score}%">'
            f'<circle cx="{size/2}" cy="{size/2}" r="{r:.1f}" fill="none" stroke="{t["h1"]}" stroke-width="12"/>'
            f'<circle cx="{size/2}" cy="{size/2}" r="{r:.1f}" fill="none" stroke="{col}" stroke-width="12" '
            f'stroke-linecap="round" stroke-dasharray="{c * score / 100:.1f} {c:.1f}" '
            f'transform="rotate(-90 {size/2} {size/2})"/>'
            f'<text x="{size/2}" y="{size/2 + size * 0.04:.1f}" font-size="{size * (0.2 if score >= 100 else 0.23):.1f}" '
            f'font-weight="800" fill="{t["ink"]}" text-anchor="middle">{score}%</text>'
            f'<text x="{size/2}" y="{size/2 + size * 0.18:.1f}" font-size="{max(10.0, size * 0.087):.1f}" fill="{t["muted"]}" '
            f'text-anchor="middle">{what}</text></svg>')


def discipline_hero(score: int, n_clean: int, n_total: int, causes: list, checked: str,
                    clean_r=None, flag_r=None, days: list | None = None, facts: list | None = None,
                    tested: str | None = None, verdicts: bool = True) -> None:
    """Score ring, one sentence on what discipline is worth in R, the causes as
    pills and a strip of the last 90 trading days (green = no rule broken).
    The headline counts the breaks, not the clean trades (his note, 28 Sep:
    "wording how many broke, not didn't break")."""
    t = _tokens()
    n_broke = n_total - n_clean
    if n_broke == 0:
        head = f"No trade broke a rule \u2014 all {n_total} clean"
    elif n_broke == n_total:
        head = f"All {n_total} trades broke a rule"
    else:
        head = f"{n_broke} of {n_total} trades broke a rule"
    worth = ""
    if clean_r is not None and flag_r is not None:
        _cc = GREEN if clean_r >= 0 else RED
        _fc = GREEN if flag_r >= 0 else RED
        # say what the numbers say: in some journals the rule-breakers still
        # average more, and claiming a "gap" there would be false
        _end = ("That gap is what discipline is worth." if clean_r > flag_r + 0.05 else
                "So far, trades that broke a rule have done no worse on average; "
                "the rules guard the bad days more than the average.")
        if clean_r > flag_r + 0.05 and tested:
            # owner: labelled; member: only a gap that beats chance is called one
            if not verdicts and tested != "beats chance":
                _end = ""
            else:
                _end += (f' <span style="font-size:11px;font-weight:700;color:{t["few"]};'
                         f'white-space:nowrap;">{tested}</span>')
        worth = (f'<div class="ea-dh-s">Clean trades average <b style="color:{_cc}">{_h.escape(fmt_r(clean_r))}</b>; '
                 f'trades that broke a rule average <b style="color:{_fc}">{_h.escape(fmt_r(flag_r))}</b>. '
                 f'{_end}</div>')
    pills = "".join(f'<span class="ea-dh-p bad">{n} {_h.escape(lab)}</span>' for n, lab in causes)
    pills += "".join(f'<span class="ea-dh-p">{_h.escape(x)}</span>' for x in (facts or []))
    strip = ""
    if days:
        sq = "".join(f'<i title="{_h.escape(d)}" style="background:{GREEN if ok else "#f4a3a3"};"></i>'
                     for d, ok in days[-90:])
        strip = (f'<div class="ea-dh-strip"><div class="ea-dh-k">LAST {min(90, len(days))} TRADING DAYS</div>'
                 f'<div class="ea-dh-sq">{sq}</div>'
                 f'<div class="ea-rx-cap"><span><i style="background:{GREEN}"></i>no rule broken</span>'
                 f'<span><i style="background:#f4a3a3"></i>a rule broken</span></div></div>')
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


def targets_frame(df: pd.DataFrame) -> pd.DataFrame | None:
    """Trades with a planned target and an MFE: plan, how far price went,
    what was banked. Newest first. None under 5 such trades."""
    if df is None or df.empty or not {"Planned R:R", "MFE (R)", "Closed RR"} <= set(df.columns):
        return None
    dcol = next((c for c in ("__Date", "Date") if c in df.columns), None)
    g = pd.DataFrame({"plan": pd.to_numeric(df["Planned R:R"], errors="coerce"),
                      "mfe": pd.to_numeric(df["MFE (R)"], errors="coerce"),
                      "r": pd.to_numeric(df["Closed RR"], errors="coerce"),
                      "when": pd.to_datetime(df[dcol], errors="coerce") if dcol else pd.NaT}, index=df.index)
    g = g[g["plan"].gt(0) & g["mfe"].notna() & g["r"].notna()]
    if len(g) < 5:
        return None
    return g.sort_values("when", ascending=False, na_position="last")


def targets_summary(g: pd.DataFrame) -> dict:
    reached = g["mfe"] >= g["plan"]
    half = g["mfe"] >= g["plan"] / 2
    return {"n": len(g), "plan": float(g["plan"].mean()), "mfe": float(g["mfe"].mean()),
            "mfe_med": float(g["mfe"].median()), "bank": float(g["r"].mean()),
            "reached": int(reached.sum()), "half": int(half.sum())}


TARGET_ROWS = 12
MINUS = "\u2212"


def targets_ladder(df: pd.DataFrame) -> bool:
    """Round-2 mockup M3: one row per trade with the target you planned (ring),
    how far price went (bar) and what you banked (dot). False when the journal
    has fewer than 5 trades with both a planned R:R and an MFE."""
    g = targets_frame(df)
    if g is None:
        return False
    t = _tokens()
    sm = targets_summary(g)
    amber = "#f5b544" if _dark() else "#b45309"
    bar = "rgba(139,123,255,.55)" if _dark() else "rgba(72,0,255,.28)"
    rows = g.head(TARGET_ROWS)
    lo = float(max(-3.0, min(-1.2, rows["r"].min() - 0.2)))
    hi = float(min(10.0, max(2.0, rows["plan"].max(), rows["mfe"].max()) + 0.3))

    def X(v: float) -> float:
        return (min(max(v, lo), hi) - lo) / (hi - lo) * 100

    steps = range(math.ceil(lo), math.floor(hi) + 1)
    ticks = "".join(f'<span class="ea-tl-tk" style="left:{X(v):.2f}%">{("0R" if v == 0 else f"{v:+d}R".replace("-", MINUS))}</span>'
                    for v in steps)
    grid = "".join(f'<i class="ea-tl-g{" z" if v == 0 else ""}" style="left:{X(v):.2f}%"></i>' for v in steps)
    body = ""
    for _, q in rows.iterrows():
        d = q["when"].strftime("%d %b").lstrip("0") if pd.notna(q["when"]) else ""
        x0, xm = X(0), X(q["mfe"])
        dot = GREEN if q["r"] > 0.15 else (RED if q["r"] < -0.15 else BE_GREY)
        tip = (f'{d}: planned {q["plan"]:.1f}R, price went {q["mfe"]:.1f}R, banked {fmt_r(q["r"])}')
        body += (f'<div class="ea-tl-r" title="{_h.escape(tip)}"><div class="ea-tl-d">{_h.escape(d)}</div>'
                 f'<div class="ea-tl-t">{grid}'
                 f'<i class="ea-tl-b" style="left:{min(x0, xm):.2f}%;width:{abs(xm - x0):.2f}%"></i>'
                 f'<i class="ea-tl-p" style="left:{X(q["plan"]):.2f}%"></i>'
                 f'<i class="ea-tl-k" style="left:{X(q["r"]):.2f}%;background:{dot}"></i></div></div>')
    head = (f'You plan <b>{sm["plan"]:.1f}R</b>. Price gave you <b>{sm["mfe"]:.1f}R</b> on average '
            f'(median {sm["mfe_med"]:.1f}R) and reached your target on <b>{sm["reached"]} of {sm["n"]}</b> trades. '
            f'You banked <b>{_h.escape(fmt_r(sm["bank"]))}</b> a trade.')
    if sm["reached"] * 2 < sm["n"] and sm["half"] > sm["reached"]:
        head += f' Half your target was there on {sm["half"]} of {sm["n"]}.'
    extra = f"""
.ea-tl-head{{font-size:15px;line-height:1.45;margin:0 0 10px;color:{t['ink']};}}
.ea-tl-ax,.ea-tl-r{{display:flex;align-items:center;gap:10px;}}
.ea-tl-ax{{height:18px;}}
.ea-tl-d{{flex:0 0 52px;font-size:12.5px;color:{t['muted']};font-variant-numeric:tabular-nums;white-space:nowrap;}}
.ea-tl-t,.ea-tl-at{{flex:1;position:relative;height:24px;min-width:0;}}
.ea-tl-at{{height:18px;}}
.ea-tl-tk{{position:absolute;transform:translateX(-50%);font-size:11px;color:{t['muted']};white-space:nowrap;}}
.ea-tl-g{{position:absolute;top:0;bottom:0;width:1px;background:{t['line']};}}
.ea-tl-g.z{{background:{t['zero']};}}
.ea-tl-b{{position:absolute;top:7px;height:10px;border-radius:4px;background:{bar};}}
.ea-tl-p{{position:absolute;top:5px;width:14px;height:14px;margin-left:-7px;border-radius:50%;
  border:2.5px solid {amber};box-sizing:border-box;}}
.ea-tl-k{{position:absolute;top:6px;width:12px;height:12px;margin-left:-6px;border-radius:50%;}}
.ea-tl-lg{{display:flex;gap:16px;flex-wrap:wrap;font-size:12.5px;color:{t['muted']};margin-top:8px;align-items:center;}}
.ea-tl-lg i{{display:inline-block;vertical-align:-2px;margin-right:5px;}}
@media (max-width:640px){{.ea-tl-d{{flex-basis:42px;font-size:11.5px;}} .ea-tl-tk{{font-size:10px;}}}}
"""
    legend = (f'<div class="ea-tl-lg"><span><i style="width:12px;height:12px;border-radius:50%;border:2.5px solid {amber};box-sizing:border-box"></i>your target</span>'
              f'<span><i style="width:20px;height:10px;border-radius:4px;background:{bar}"></i>how far price went (MFE)</span>'
              f'<span><i style="width:11px;height:11px;border-radius:50%;background:{GREEN}"></i>what you banked</span></div>')
    more = (f'<div class="ea-rx-cap">Your last {TARGET_ROWS} trades with a target; the sentence above counts all {sm["n"]}.</div>'
            if sm["n"] > TARGET_ROWS else "")
    st.markdown(css(extra) + f'<div class="ea-rx"><div class="ea-tl-head">{head}</div>'
                f'<div class="ea-tl-ax"><div class="ea-tl-d"></div><div class="ea-tl-at">{ticks}</div></div>'
                f'{body}{legend}{more}</div>', unsafe_allow_html=True)
    return True


def _res_of(df: pd.DataFrame, r: pd.Series) -> pd.Series:
    """Win / BE / Loss from the journal's own tag when it has one, else R bands."""
    ocol = next((c for c in ("Outcome", "Outcome Canonical", "Result") if c in df.columns), None)
    band = pd.Series(["Win" if v > 0.15 else ("Loss" if v < -0.15 else "BE") for v in r], index=r.index)
    if ocol is None:
        return band
    tag = df[ocol].astype(str).str.strip().str.title().replace({"Breakeven": "BE", "Be": "BE"})
    return tag.where(tag.isin(["Win", "BE", "Loss"]), band)


def hold_strip(df: pd.DataFrame) -> bool:
    """Round-6 mockup M3: every trade as a dot on a log time axis, coloured by
    result, with one sentence on how long winners and losses live. Replaces a
    line drawn through three hold-time buckets. False under 8 trades."""
    if df is None or df.empty or "Hold Time (min)" not in df.columns:
        return False
    rcol = next((c for c in ("Closed RR", "PnL_from_RR") if c in df.columns), None)
    if rcol is None:
        return False
    g = pd.DataFrame({"h": pd.to_numeric(df["Hold Time (min)"], errors="coerce"),
                      "r": pd.to_numeric(df[rcol], errors="coerce")}, index=df.index)
    g = g[g["h"].gt(0) & g["r"].notna()]
    if len(g) < 8:
        return False
    g["res"] = _res_of(df.loc[g.index], g["r"])
    t = _tokens()
    lo, hi = 0.5, float(max(60.0, g["h"].max() * 1.15))

    def X(m):
        return (math.log10(max(m, lo)) - math.log10(lo)) / (math.log10(hi) - math.log10(lo)) * 100
    col = {"Win": GREEN, "Loss": RED, "BE": BE_GREY}
    ticks = "".join(f'<span class="ea-hs-tk" style="left:{X(m):.2f}%">{lab}</span><i class="ea-hs-g" style="left:{X(m):.2f}%"></i>'
                    for m, lab in ((1, "1m"), (5, "5m"), (15, "15m"), (60, "1h"), (240, "4h"), (1440, "1d"), (10080, "1w"))
                    if lo < m < hi)
    dots = ""
    for j, (_, q) in enumerate(g.sort_values("h").iterrows()):
        tip = f'{q["h"]:.0f} min \u00b7 {fmt_r(q["r"])}'
        dots += (f'<i class="ea-hs-d" title="{_h.escape(tip)}" style="left:{X(q["h"]):.2f}%;'
                 f'top:{8 + (j % 3) * 14}px;background:{col[q["res"]]}"></i>')

    def _fmt(m):
        return f"{m:.0f} min" if m < 90 else (f"{m / 60:.1f} h".replace(".0 h", " h") if m < 2880 else f"{m / 1440:.0f} days")
    wins, losses = g[g["res"] == "Win"], g[g["res"] == "Loss"]
    if len(wins) >= 2 and len(losses) >= 2:
        head = (f"Your winners held a median <b>{_fmt(wins['h'].median())}</b>; your losses closed after a median "
                f"<b>{_fmt(losses['h'].median())}</b>.")
        if losses["h"].median() < wins["h"].median() / 2:
            head += " Most losses are quick stop-outs, not slow bleeds."
    else:
        head = f"Your trades lived a median <b>{_fmt(g['h'].median())}</b>."
    extra = f"""
.ea-hs-head{{font-size:15px;line-height:1.45;margin:0 0 8px;color:{t['ink']};}}
.ea-hs{{position:relative;height:72px;margin:0 6px;}}
.ea-hs-g{{position:absolute;top:0;height:50px;width:1px;background:{t['line']};}}
.ea-hs-tk{{position:absolute;top:54px;transform:translateX(-50%);font-size:11px;color:{t['muted']};}}
.ea-hs-d{{position:absolute;width:12px;height:12px;margin-left:-6px;border-radius:50%;opacity:.9;}}
.ea-hs-lg{{display:flex;gap:14px;font-size:12.5px;color:{t['muted']};margin-top:4px;}}
"""
    lg = "".join(f'<span><b style="color:{c}">\u25cf</b> {n}</span>' for n, c in
                 (("won", GREEN), ("lost", RED), ("break-even", BE_GREY)))
    st.markdown(css(extra) + f'<div class="ea-rx"><div class="ea-hs-head">{head}</div>'
                f'<div class="ea-hs">{ticks}{dots}</div><div class="ea-hs-lg">{lg}</div></div>',
                unsafe_allow_html=True)
    return True


def breakeven_rows(df: pd.DataFrame) -> bool:
    """Round-6 mockup M3: net R by the journal's breakeven rule, with one
    sentence on the trades that lost before breakeven was set. False without
    a Breakeven Criteria tag on 5+ trades."""
    if df is None or df.empty or "Breakeven Criteria" not in df.columns:
        return False
    rcol = next((c for c in ("Closed RR", "PnL_from_RR") if c in df.columns), None)
    if rcol is None:
        return False
    g = pd.DataFrame({"be": df["Breakeven Criteria"].map(_txt).str.split(",").str[0].str.strip(),
                      "r": pd.to_numeric(df[rcol], errors="coerce")}, index=df.index)
    g = g[(g["be"].str.len() > 0) & g["r"].notna()]
    if len(g) < 5:
        return False
    rows = g.groupby("be")["r"].agg(["count", "sum", "mean"]).sort_values("sum", ascending=False)
    t = _tokens()
    vmax = float(rows["sum"].abs().max()) or 1.0
    body = ""
    for name, q in rows.iterrows():
        w = abs(q["sum"]) / vmax * 50
        left = 50 if q["sum"] >= 0 else 50 - w
        c = GREEN if q["sum"] > 0 else RED
        body += (f'<div class="ea-be-r"><div class="ea-be-l">{_h.escape(str(name))}</div>'
                 f'<div class="ea-be-n">{int(q["count"])}</div>'
                 f'<div class="ea-be-t"><i style="left:{left:.1f}%;width:{w:.1f}%;background:{c}"></i><b></b></div>'
                 f'<div class="ea-be-v" style="color:{c}">{_h.escape(fmt_r(q["sum"], 1))}</div></div>')
    bad = rows[rows.index.str.contains(r"loss before|failed", case=False, regex=True)]
    good = rows[~rows.index.isin(bad.index)]
    if len(bad):
        n_b, r_b = int(bad["count"].sum()), float(bad["sum"].sum())
        head = (f"<b>{n_b} trade{'s' if n_b != 1 else ''} lost before breakeven was set</b> "
                f"({_h.escape(fmt_r(r_b, 1))}).")
        if len(good) and good["sum"].iloc[0] > 0:
            head += (f" Moving to breakeven <b>{_h.escape(str(good.index[0]).lower())}</b> kept "
                     f"{_h.escape(fmt_r(good['sum'].iloc[0], 1))} over {int(good['count'].iloc[0])}.")
    else:
        head = (f"Your best breakeven rule: <b>{_h.escape(str(rows.index[0]))}</b> "
                f"({_h.escape(fmt_r(rows['sum'].iloc[0], 1))} over {int(rows['count'].iloc[0])}).")
    extra = f"""
.ea-be-head{{font-size:15px;line-height:1.45;margin:0 0 10px;color:{t['ink']};}}
.ea-be-r{{display:flex;align-items:center;gap:10px;padding:6px 0;border-bottom:1px solid {t['line']};}}
.ea-be-r:last-child{{border-bottom:0;}}
.ea-be-l{{flex:0 0 42%;font-size:13.5px;color:{t['ink']};min-width:0;overflow-wrap:anywhere;}}
.ea-be-n{{flex:0 0 22px;font-size:12.5px;color:{t['muted']};text-align:right;}}
.ea-be-t{{flex:1;position:relative;height:10px;border-radius:5px;background:{t['soft']};}}
.ea-be-t i{{position:absolute;top:0;bottom:0;border-radius:4px;}}
.ea-be-t b{{position:absolute;left:50%;top:-3px;bottom:-3px;width:1px;background:{t['zero']};}}
.ea-be-v{{flex:0 0 52px;text-align:right;font-size:13.5px;font-weight:800;font-variant-numeric:tabular-nums;}}
"""
    st.markdown(css(extra) + f'<div class="ea-rx"><div class="ea-be-head">{head}</div>{body}</div>',
                unsafe_allow_html=True)
    return True


_CONTEXT_ROWS = [
    ("Conditions MTF", "Conditions (MTF)"), ("Conditions HTF", "Conditions (HTF)"),
    ("Conditions ETF", "Conditions (ETF)"), ("Tiers in pricing MTF", "Tier in pricing (MTF)"),
    ("Tiers in pricing HTF", "Tier in pricing (HTF)"), ("Opposing Weak Structure?", "Opposing weak structure"),
    ("Oversold or Overbought?", "Overbought / oversold"), ("News Aspect", "News"),
    ("Volatility", "Volatility"), ("GAP Alignment", "Gap"), ("GAP Alignment?", "Gap"),
]


def _news_bucket(v: str) -> str:
    s = v.lower()
    if s.startswith("closed before"):
        return "Closed before news"
    if s.startswith("traded through"):
        return "Held through news"
    return {"no news": "No news", "post news": "After news"}.get(s, v)


def context_frame(df: pd.DataFrame) -> list[dict]:
    """[{label, parts: [(value, n, net R, mask)]}] for each market-context
    column the journal fills, 2+ values with 3+ trades between them."""
    rcol = next((c for c in ("Closed RR", "PnL_from_RR") if c in df.columns), None)
    if df is None or df.empty or rcol is None:
        return []
    r = pd.to_numeric(df[rcol], errors="coerce")
    rows, seen = [], set()
    for col, label in _CONTEXT_ROWS:
        if col not in df.columns or label in seen:
            continue
        if col.endswith("?"):
            yn = df[col].map(_yes)
            if not (yn == True).any():      # noqa: E712  never ticked: no row
                continue
            vals = yn.map({True: "Yes", False: "No"})
            if col == "Opposing Weak Structure?":
                vals = vals.map({"Yes": "Against it", "No": "Clear"})
        else:
            vals = df[col].map(_txt).str.split(",").str[0].str.strip()
            if col == "News Aspect":
                vals = vals.map(lambda v: _news_bucket(v) if v else v)
        vals = vals.where(r.notna(), None)
        parts = []
        for v, sub in r.groupby(vals):
            if v in (None, "") or str(v).lower() in ("nan", "none", "na"):
                continue
            parts.append((str(v), int(sub.count()), float(sub.sum()), (vals == v).to_numpy()))
        parts = [p for p in parts if p[1] >= 1]
        if len(parts) >= 2 and sum(p[1] for p in parts) >= 5:
            seen.add(label)
            rows.append({"label": label, "parts": sorted(parts, key=lambda p: -p[1])})
    return rows


def context_board(df: pd.DataFrame, verdicts: bool = True) -> bool:
    """Round-11 mockup M6: every market-context tag as one row, segments sized
    by trades and coloured by net R, one sentence on top. Best/worst values are
    tested with Holm across every value on the board. False under 2 rows."""
    rows = context_frame(df)
    if len(rows) < 2:
        return False
    from edge_analysis.digest import _perm_p, _holm_pass
    rcol = next(c for c in ("Closed RR", "PnL_from_RR") if c in df.columns)
    x = pd.to_numeric(df[rcol], errors="coerce")
    keys, ps = [], []
    for row in rows:
        for v, n, net, m in row["parts"]:
            if n >= 5 and n < int(x.notna().sum()) - 1:
                for d in ("good", "bad"):
                    keys.append((row["label"], v, d))
                    ps.append(_perm_p(x, m, lower=d == "bad"))
    passed = {keys[i] for i in _holm_pass(ps)}
    t = _tokens()
    cand = [(row["label"], v, n, net) for row in rows for v, n, net, _ in row["parts"] if n >= 3]
    head = ""
    if cand:
        best = max(cand, key=lambda c: c[3])
        worst = min(cand, key=lambda c: c[3])

        def lab(c, d):
            return ("beats chance" if (c[0], c[1], d) in passed else "early read")
        bits = []
        if best[3] > 0 and (verdicts or (best[0], best[1], "good") in passed):
            bits.append(f"You've made the most in <b>{_h.escape(best[1].lower())}</b> ({_h.escape(best[0].lower())}): "
                        f"{_h.escape(fmt_r(best[3], 1))} over {best[2]} <span class='ea-cx-l'>{lab(best, 'good')}</span>")
        if worst[3] < 0 and worst != best and (verdicts or (worst[0], worst[1], "bad") in passed):
            bits.append(f"<b>{_h.escape(worst[1].lower())}</b> ({_h.escape(worst[0].lower())}) cost "
                        f"{_h.escape(fmt_r(worst[3], 1))} over {worst[2]} <span class='ea-cx-l'>{lab(worst, 'bad')}</span>")
        head = ". ".join(bits) + ("." if bits else "")
    body = ""
    for row in rows:
        segs = ""
        for v, n, net, _ in row["parts"]:
            bg = ("rgba(22,163,74,.26)" if net > 0 else "rgba(220,38,38,.24)") if abs(net) >= 0.05 else t["soft"]
            segs += (f'<div class="ea-cx-s" style="flex:{n};background:{bg}" title="{_h.escape(v)}: {n} trades, {_h.escape(fmt_r(net, 1))}">'
                     f'<div class="v">{_h.escape(v)}</div><div class="r">{_h.escape(fmt_r(net, 1))} '
                     f'<span>\u00b7 {n}</span></div></div>')
        tot = sum(p[1] for p in row["parts"])
        body += (f'<div class="ea-cx-row"><div class="ea-cx-h"><span>{_h.escape(row["label"])}</span>'
                 f'<span class="n">{tot} tagged</span></div><div class="ea-cx-b">{segs}</div></div>')
    extra = f"""
.ea-cx-head{{font-size:15px;line-height:1.45;margin:0 0 12px;color:{t['ink']};}}
.ea-cx-l{{font-size:11px;font-weight:700;color:{t['few']};white-space:nowrap;}}
.ea-cx-row{{margin:0 0 12px;}}
.ea-cx-h{{display:flex;justify-content:space-between;font-size:11.5px;font-weight:800;letter-spacing:.06em;
  text-transform:uppercase;color:{t['muted']};margin-bottom:5px;}}
.ea-cx-h .n{{font-weight:600;letter-spacing:0;text-transform:none;}}
.ea-cx-b{{display:flex;gap:4px;}}
.ea-cx-s{{min-width:0;border-radius:8px;padding:7px 9px;color:{t['ink']};}}
.ea-cx-s .v{{font-size:12.5px;font-weight:700;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}}
.ea-cx-s .r{{font-size:14.5px;font-weight:800;white-space:nowrap;}}
.ea-cx-s .r span{{font-size:12px;font-weight:600;color:{t['muted']};}}
@media (max-width:640px){{.ea-cx-b{{flex-wrap:wrap;}} .ea-cx-s{{flex:1 1 45% !important;}}}}
"""
    st.markdown(css(extra) + f'<div class="ea-rx"><div class="ea-cx-head">{head}</div>{body}'
                f'<div class="ea-rx-cap">Width = trades, colour = net R. Replaces the conditions grid, the '
                f'factors board and the hour/instrument lists that repeated your sessions.</div></div>',
                unsafe_allow_html=True)
    return True


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

    # (28 Sep) what was left on winners and given back is said once, in
    # "What got away" under this chart (got_away.py), not as two more tiles
    c1, c2 = st.columns(2)
    with c1:
        _kpi("Captured on winners", "—" if cap != cap else f"{cap:.0f}%", "of the best price, on average")
    with c2:
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
                                                                range=[GREEN, BE_GREY, RED])),
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


def outcome_class(r, outcome=None) -> pd.Series:
    """1 win, 0 break-even, -1 loss per trade: his Outcome tag where it says
    Win, BE or Loss, as on every card; the R band (over +0.15R a win, under
    -0.15R a loss) only where there is no tag. Record's "avg loss -0.8R" sat
    beside Projections' "average loss 1.1R" because they used one each (28 Sep)."""
    r = pd.to_numeric(pd.Series(r), errors="coerce")
    band = r.gt(0.15).astype(int) - r.lt(-0.15).astype(int)
    if outcome is None or len(outcome) != len(r):
        return band
    tag = pd.Series(list(outcome), index=r.index, dtype=object).map(
        lambda v: {"win": 1, "loss": -1, "be": 0}.get(str(v).strip().lower()))
    return tag.where(tag.notna(), band).astype(int)


def record_stats(r: pd.Series, dates: pd.Series, outcome=None) -> dict:
    """Headline numbers over every trade, in order. Wins, losses and
    break-evens by outcome_class; a break-even breaks no streak."""
    r = pd.to_numeric(r, errors="coerce").reset_index(drop=True)
    dates = pd.to_datetime(dates).reset_index(drop=True)
    cls = outcome_class(r, outcome)
    ok = r.notna()
    r, dates, cls = (r[ok].reset_index(drop=True), dates[ok].reset_index(drop=True),
                     cls[ok].reset_index(drop=True))
    wins, losses = r[cls == 1], r[cls == -1]
    n = len(r)
    cum = r.cumsum()
    dd = cum - cum.cummax()
    out = dict(n=n, net=float(r.sum()), exp=float(r.mean()) if n else 0.0,
               win=100.0 * len(wins) / n if n else 0.0, be=100.0 * (n - len(wins) - len(losses)) / n if n else 0.0,
               # every gain over every loss, scratches included: the All time
               # card's definition (they read 1.36 and 1.37 side by side)
               pf=(float(r[r > 0].sum() / -r[r < 0].sum()) if (r < 0).any() else None),
               avg_w=float(wins.mean()) if len(wins) else None, avg_l=float(losses.mean()) if len(losses) else None,
               maxdd=float(dd.min()) if n else 0.0, dd_from=None, dd_to=None, dd_back=None)
    if n and out["maxdd"] < 0:
        i_to = int(dd.idxmin())
        i_from = int(cum.iloc[: i_to + 1].idxmax())
        back = cum.iloc[i_to:][cum.iloc[i_to:] >= cum.iloc[i_from]]
        out.update(dd_from=dates[i_from], dd_to=dates[i_to],
                   dd_back=(dates[int(back.index[0])] if len(back) else None))
    seq = [int(c) for c in cls]
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
    today = local_now().normalize()
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


def _date_axis(dates):
    """Weeks as "07 Sep" on a record under four months, months as "Sep 2026"
    after. The old "%b %y" put one tick, "Sep 26", under a five-week record,
    which reads as 26 September (28 Sep check)."""
    import altair as alt
    d = pd.to_datetime(pd.Series(dates), errors="coerce").dropna()
    short = d.empty or (d.max() - d.min()).days <= 120
    return alt.Axis(format="%d %b" if short else "%b %Y", labelOverlap=True,
                    tickCount="week" if short else "month")


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
    s = record_stats(g["__r"], g["__d"], g["Outcome"] if "Outcome" in g.columns else None)
    f = lambda d: d.strftime("%d %b") if d is not None else ""
    dd_sub = ("no drawdown yet" if s["maxdd"] >= 0 else
              f"{f(s['dd_from'])} → {f(s['dd_to'])}, " + (f"back by {f(s['dd_back'])}" if s["dd_back"] is not None
                                                             else "not yet recovered"))
    cur = s["cur"]
    streak_v = ("none" if cur == 0 else f"{abs(cur)} {'win' if cur > 0 else 'loss'}{'' if abs(cur) == 1 else ('s' if cur > 0 else 'es')}")
    # Net, expectancy, win rate and profit factor sit in the All time card
    # right above; this card carries only what that one doesn't (one stat once)
    size = ("—" if not (s["avg_w"] and s["avg_l"]) else f"{s['avg_w'] / -s['avg_l']:.1f}×")
    tiles([
        ("Max drawdown", fmt_r(s["maxdd"], 1), dd_sub, RED if s["maxdd"] < 0 else GREEN),
        ("Streak", streak_v, f"longest: {s['best_w']} wins · {s['best_l']} losses",
         GREEN if cur > 0 else (RED if cur < 0 else "#64748b")),
        ("Win vs loss size", size,
         (f"avg win {fmt_r(s['avg_w'], 1)} · avg loss {fmt_r(s['avg_l'], 1)} · {s['be']:.0f}% break-even"
          if s["avg_w"] is not None and s["avg_l"] is not None else f"{s['be']:.0f}% break-even"),
         "#4800ff"),
    ])
    # equity curve + drawdown, one trade per point, shared time axis
    cum = g["__r"].cumsum()
    eq = pd.DataFrame({"Date": g["__d"].dt.strftime("%Y-%m-%dT%H:%M:%S"), "R": cum.round(2),
                       "DD": (cum - cum.cummax()).round(2), "Trade": g["__r"].round(2)})
    vals = eq.to_dict("records")
    x = alt.X("Date:T", title=None, axis=_date_axis(g["__d"]))
    area = alt.Chart(alt.Data(values=vals)).mark_area(color=PURPLE, opacity=0.08).encode(x=x, y=alt.Y("R:Q", title="Running R"))
    line = alt.Chart(alt.Data(values=vals)).mark_line(color=PURPLE, strokeWidth=2).encode(
        x=x, y=alt.Y("R:Q", title="Running R"),
        tooltip=[alt.Tooltip("Date:T", format="%a %d %b %Y"), alt.Tooltip("Trade:Q", title="This trade (R)"),
                 alt.Tooltip("R:Q", title="Running R")])
    ddc = alt.Chart(alt.Data(values=vals)).mark_area(color=RED, opacity=0.25, line={"color": RED, "strokeWidth": 1}).encode(
        x=alt.X("Date:T", title=None, axis=_date_axis(g["__d"])),
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
                                                                range=[RED, BE_GREY, GREEN])),
            tooltip=[alt.Tooltip("lab:N", title="Around (R)"), alt.Tooltip("n:Q", title="Trades")])
        txt = alt.Chart(alt.Data(values=[h for h in hv if h["n"]])).mark_text(dy=-7, fontSize=11, fontWeight="bold", color="#64748b").encode(
            x=hx, y="n:Q", text="n:Q")
        st.altair_chart(styler(alt.layer(bars, txt).properties(height=250)), use_container_width=True)
        st.caption(f"Median trade {fmt_r(float(g['__r'].median()))}. Most trades are a stop or a scratch; "
                   "the edge lives in the right-hand tail.")
    if len(g) >= 20:
        edge_check(g, styler, s["exp"])
        before_after(g)


def edge_check(g: pd.DataFrame, styler, all_exp: float, window: int = 30) -> None:
    """Launch-review P2 #10: the average of the last 30 trades at every point,
    against the all-time average, so a fading setup shows up early."""
    import altair as alt
    st.markdown("#### Is the edge holding up?")
    w = min(window, max(10, len(g) // 3))
    roll = g["__r"].rolling(w, min_periods=w).mean()
    d = pd.DataFrame({"Date": g["__d"].dt.strftime("%Y-%m-%dT%H:%M:%S"), "Roll": roll.round(3)}).dropna()
    if d.empty:
        return
    vals = d.to_dict("records")
    x = alt.X("Date:T", title=None, axis=_date_axis(g["__d"]))
    line = alt.Chart(alt.Data(values=vals)).mark_line(color=PURPLE, strokeWidth=2.2).encode(
        x=x, y=alt.Y("Roll:Q", title=f"Last {w} trades (R)"),
        tooltip=[alt.Tooltip("Date:T", format="%a %d %b %Y"), alt.Tooltip("Roll:Q", title=f"Last {w} avg", format="+.2f")])
    ref = alt.Chart(alt.Data(values=[{"y": round(all_exp, 3)}])).mark_rule(
        color=GREEN, strokeDash=[6, 4], strokeWidth=1.8).encode(y=alt.Y("y:Q", title=f"Last {w} trades (R)"))
    zero = alt.Chart(alt.Data(values=[{"y": 0}])).mark_rule(color="#cbd5e1", strokeWidth=1.2).encode(y="y:Q")
    st.altair_chart(styler(alt.layer(zero, ref, line).properties(height=200)), use_container_width=True)
    now = float(roll.dropna().iloc[-1])
    if now < all_exp - 0.15:
        how = f"below your all-time {fmt_r(all_exp)}"
    elif now > all_exp + 0.15:
        how = f"above your all-time {fmt_r(all_exp)}"
    else:
        how = f"in line with your all-time {fmt_r(all_exp)}"
    st.caption(f"Your last {w} trades average {fmt_r(now)}, {how} (dashed line). "
               f"Each point is the average of the {w} trades up to that day.")


def before_after(g: pd.DataFrame) -> None:
    """Launch-review P2 #9: pick the day a rule changed and compare the two
    sides. Descriptive only: both sides are the trader's own trades, and a
    side under 20 trades is marked as too small to read."""
    import datetime as _dt
    st.markdown("#### Before and after a change")
    first, last = g["__d"].min().date(), g["__d"].max().date()
    key = "ea_ba_date"
    default = st.session_state.get(key) or (g["__d"].iloc[int(len(g) * 2 / 3)].date())
    c1, c2 = st.columns([1, 2.4])
    with c1:
        st.caption("The day your rules changed")
        day = st.date_input("The day your rules changed", value=default, min_value=first,
                            max_value=last, key=key, format="DD/MM/YYYY",
                            label_visibility="collapsed")
    cut = pd.Timestamp(day if isinstance(day, _dt.date) else default)
    b, a = g[g["__d"] < cut], g[g["__d"] >= cut]

    def side(x):
        if not len(x):
            return None
        wins = (x["__r"] > 0.15).mean() * 100
        weeks = max(1.0, (x["__d"].max() - x["__d"].min()).days / 7.0)
        return dict(n=len(x), exp=float(x["__r"].mean()), win=float(wins), net=float(x["__r"].sum()),
                    pw=len(x) / weeks)
    sb, sa = side(b), side(a)
    with c2:
        if not sb or not sa:
            st.caption("Pick a day with trades on both sides.")
            return
        t = _tokens()
        rows = [("Trades", f"{sb['n']}", f"{sa['n']}", None),
                ("Expectancy", fmt_r(sb["exp"]), fmt_r(sa["exp"]), sa["exp"] - sb["exp"]),
                ("Win rate", f"{sb['win']:.0f}%", f"{sa['win']:.0f}%", (sa["win"] - sb["win"]) / 100),
                ("Net", fmt_r(sb["net"], 1), fmt_r(sa["net"], 1), None),
                ("Trades a week", f"{sb['pw']:.1f}", f"{sa['pw']:.1f}", None)]
        body = ""
        for lab, vb, va, dlt in rows:
            arrow = ""
            if dlt is not None and abs(dlt) >= 0.005:
                _tri = "\u25b2" if dlt > 0 else "\u25bc"
                arrow = (f' <span style="color:{GREEN if dlt > 0 else RED};font-weight:800;">'
                         f'{_tri}</span>')
            body += f'<tr><td class="l">{lab}</td><td>{_h.escape(vb)}</td><td>{_h.escape(va)}{arrow}</td></tr>'
        small = [nm for nm, sd in (("before", sb), ("after", sa)) if sd["n"] < 20]
        extra = f"""
.ea-ba{{border-collapse:collapse !important;width:100%;border:0 !important;font-variant-numeric:tabular-nums;}}
.ea-ba th,.ea-ba td{{border:0 !important;border-bottom:1px solid {t['line']} !important;padding:7px 10px !important;
  text-align:right;background:none !important;color:{t['ink']};font-size:14px;}}
.ea-ba th{{font-size:11px;font-weight:700;letter-spacing:.06em;color:{t['muted']};text-transform:uppercase;}}
.ea-ba td.l,.ea-ba th.l{{text-align:left;color:{t['muted']};font-weight:600;}}
.ea-ba tr{{background:none !important;}}
"""
        st.markdown(css(extra) + f'<div class="ea-rx"><table class="ea-ba"><tr><th class="l"></th>'
                    f'<th>Before {cut.strftime("%d %b")}</th><th>Since</th></tr>{body}</table></div>',
                    unsafe_allow_html=True)
        st.caption("Both sides are your own trades, nothing re-scored. "
                   + (f"The {' and '.join(small)} side has under 20 trades, too few to read much into."
                      if small else "Arrows show which way the after side moved."))


# ── trade explorer + trade card (mockup V5) ──────────────────────────────────
_NOTE_COLS = ("Teachings/Learning Curve", "Reason of loss", "Notes", "Comment")
# What a broker sync writes into Comment: "[sl 4387.90]" / "[tp 4601.19]" from
# MT5, "CON.F.US.GCE.Z26 (GCZ6) · 1 fill(s) in / 1 out · gross …, fees …" from
# Topstep. Not the trader's words, and the Topstep one carries dollar figures.
_SYNC_NOTE = re.compile(r"^\[?\s*(sl|tp)\s+[\d.]+\s*\]?$|fill\(s\)|\bgross\s+-?[\d,.]+|\bfees\s+[\d,.]+", re.I)


def _note_text(v) -> str:
    s = _txt(v)
    return "" if _SYNC_NOTE.search(s) else s


def _txt(v) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    if isinstance(v, (list, tuple)):
        return ", ".join(_txt(x) for x in v if _txt(x))
    s = str(v).strip()
    if s.startswith("[") and s.endswith("]"):
        s = s.strip("[]").replace('"', "").replace("'", "")
    return "" if s.lower() in ("nan", "none", "null", "nat", "na") else s


def _first_col(df: pd.DataFrame, *names):
    return next((c for c in names if c in df.columns), None)


def _yes(v) -> bool | None:
    if isinstance(v, bool):
        return v
    s = _txt(v).lower()
    if s in ("yes", "true", "__yes__", "1"):
        return True
    if s in ("no", "false", "__no__", "0"):
        return False
    return None


def _notion_link(v) -> str:
    """The row's own Notion page, or "" — only Notion's own hosts are linked."""
    u = str(v or "").strip()
    return u if re.match(r"^https://(www\.)?notion\.(so|site)/[\w\-./?=&#%]+$", u) else ""


def explorer_frame(g: pd.DataFrame) -> pd.DataFrame:
    """One tidy row per trade for the explorer, newest first."""
    em2 = _first_col(g, "Entry Model 2")
    # a double-confirmation journal also carries a combined "Entry Model" list
    # (both models); read as the structure it printed "A, B → B"
    em1 = (_first_col(g, "Entry Model 1", "Entry Model") if em2 else _first_col(g, "Entry Model", "Entry Model 1"))
    tf2 = _first_col(g, "Timeframe 2")
    tf = (_first_col(g, "Timeframe 1", "Entry Timeframe", "Entry Model Timeframe") if tf2 else
          _first_col(g, "Entry Timeframe", "Timeframe 1", "Entry Model Timeframe"))
    ses = _first_col(g, "Session", "Session Norm")
    out = pd.DataFrame(index=g.index)
    out["when"] = pd.to_datetime(g["__Date"])
    out["r"] = pd.to_numeric(g["Closed RR"] if "Closed RR" in g.columns else g.get("PnL_from_RR"), errors="coerce")
    out["session"] = g[ses].map(_txt) if ses else ""
    m1 = g[em1].map(_txt) if em1 else pd.Series("", index=g.index)
    m2 = g[em2].map(_txt) if em2 else pd.Series("", index=g.index)
    out["setup"] = [a + (f" → {b}" if b else "") for a, b in zip(m1, m2)]
    # "your record with this setup" matches the whole pair
    out["model"] = out["setup"]
    t1 = g[tf].map(_txt) if tf else pd.Series("", index=g.index)
    t2 = g[tf2].map(_txt) if tf2 else pd.Series("", index=g.index)
    out["tf"] = [a + (f" → {b}" if (a and b) else "") for a, b in zip(t1, t2)]
    out["dir"] = g["Direction"].map(_txt) if "Direction" in g.columns else ""
    for c, k in (("MFE (R)", "mfe"), ("MAE (R)", "mae"), ("Planned R:R", "plan")):
        out[k] = pd.to_numeric(g[c], errors="coerce") if c in g.columns else float("nan")
    out["rules"] = g["Rules Followed?"].map(_yes) if "Rules Followed?" in g.columns else None
    out["mistake"] = g["Mistake"].map(_txt) if "Mistake" in g.columns else ""
    out["mistake"] = out["mistake"].where(~out["mistake"].str.lower().isin(["no mistake", "none"]), "")
    out["aplus"] = g["A+ Setup?"].map(_yes) if "A+ Setup?" in g.columns else None
    out["flag"] = out["rules"].eq(False) | out["mistake"].ne("")
    out["notes"] = [" · ".join(x for x in (_note_text(g.at[i, c]) for c in _NOTE_COLS if c in g.columns) if x)
                    for i in g.index]
    tags = {}
    for c, lab in (("Conviction (1-5)", "Conviction"), ("Mental State", "Mental state"),
                   ("Conditions MTF", "Conditions"), ("Volatility", "Volatility"),
                   ("News Aspect", "News"), ("Breakeven Criteria", "Break-even rule"),
                   ("Tiers in pricing MTF", "Tier")):
        if c in g.columns:
            tags[lab] = g[c].map(_txt)
    out["tags"] = [{k: v.at[i] for k, v in tags.items() if v.at[i]} for i in g.index]
    out["url"] = g["__url"].map(_notion_link) if "__url" in g.columns else ""
    out = out[out["r"].notna() & out["when"].notna()]
    return out.sort_values("when", ascending=False)


def _path_svg(row, w: int = 150, h: int = 14) -> str:
    lo, hi = -1.3, 4.4
    X = lambda v: (min(max(v, lo), hi) - lo) / (hi - lo) * w
    mae = row["mae"] if pd.notna(row["mae"]) else min(row["r"], 0.0)
    mfe = row["mfe"] if pd.notna(row["mfe"]) else max(row["r"], 0.0)
    col = GREEN if row["r"] > 0.15 else (RED if row["r"] < -0.15 else BE_GREY)
    return (f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}"><rect x="0" y="{h/2-1}" width="{w}" height="2" fill="#e2e8f0"/>'
            f'<rect x="{X(mae):.1f}" y="{h/2-4}" width="{max(X(mfe)-X(mae), 2):.1f}" height="8" rx="4" fill="#c7d2fe"/>'
            f'<line x1="{X(0):.1f}" x2="{X(0):.1f}" y1="0" y2="{h}" stroke="#64748b"/>'
            f'<circle cx="{X(row["r"]):.1f}" cy="{h/2}" r="4.5" fill="{col}" stroke="#fff" stroke-width="1.5"/></svg>')


def _big_path(row, w: int = 400) -> str:
    t = _tokens()
    plan = row["plan"] if pd.notna(row["plan"]) else None
    mae = row["mae"] if pd.notna(row["mae"]) else None
    mfe = row["mfe"] if pd.notna(row["mfe"]) else None
    pts = [-1.0, 0.0, row["r"]] + [x for x in (plan, mae, mfe) if x is not None]
    lo, hi = min(pts) - 0.3, max(pts) + 0.4
    X = lambda v: 14 + (v - lo) / (hi - lo) * (w - 28)
    marks = [(-1.0, "stop −1R", RED), (0.0, "entry", t["muted"])]
    if plan:
        marks.append((plan, f"target {plan:.1f}R", "#a78bfa" if _dark() else PURPLE))
    svg = "".join(f'<line x1="{X(v):.1f}" x2="{X(v):.1f}" y1="24" y2="62" stroke="{c}" stroke-dasharray="3 3"/>'
                  f'<text x="{X(v):.1f}" y="78" font-size="11.5" fill="{c}" text-anchor="middle" font-weight="700">{lab}</text>'
                  for v, lab, c in marks)
    if mae is not None and mfe is not None:
        svg += (f'<rect x="{X(mae):.1f}" y="37" width="{max(X(mfe) - X(mae), 2):.1f}" height="12" rx="6" fill="#c7d2fe"/>'
                f'<text x="{X(mae):.1f}" y="16" font-size="11" fill="{t["muted"]}" text-anchor="middle">worst {fmt_r(mae)}</text>'
                f'<text x="{X(mfe):.1f}" y="16" font-size="11" fill="{t["muted"]}" text-anchor="middle">best {fmt_r(mfe)}</text>')
    col = GREEN if row["r"] > 0.15 else (RED if row["r"] < -0.15 else BE_GREY)
    svg += f'<circle cx="{X(row["r"]):.1f}" cy="43" r="8" fill="{col}" stroke="#fff" stroke-width="2"/>'
    # capped width: a viewBox stretched across a desktop card blew the labels up 3x
    return (f'<svg viewBox="0 0 {w} 86" style="width:100%;max-width:{w + 60}px;height:auto;display:block;" '
            f'preserveAspectRatio="xMinYMid meet">{svg}</svg>')


def trade_explorer(g: pd.DataFrame, key: str = "ea_tx") -> None:
    """Every trade, filterable, with a path bar per row; open one to see its
    card: the move against stop and target, its tags, its notes, and how the
    same setup has done before."""
    x = explorer_frame(g)
    if x.empty:
        st.caption("Trades appear here once they carry a date and a result.")
        return
    t = _tokens()
    res = st.radio("Show", ["All", "Wins", "Losses", "Break-even", "Flagged"], horizontal=True,
                   key=f"{key}_res", label_visibility="collapsed") or "All"
    _phone = st.session_state.get("layout_mode") == "mobile"
    if _phone:
        # four stacked boxes were a wall on a phone: the period stays out,
        # the rest fold away
        per = st.selectbox("Period", ["All time", "Last 30 days", "Last 90 days", "This year"],
                           key=f"{key}_per", label_visibility="collapsed")
        _more = st.expander("Session, setup, search")
        c2 = c3 = c4 = _more
    else:
        c1, c2, c3, c4 = st.columns([1, 1, 1, 1.3])
        with c1:
            per = st.selectbox("Period", ["All time", "Last 30 days", "Last 90 days", "This year"],
                               key=f"{key}_per", label_visibility="collapsed")
    with c2:
        sess = sorted(s for s in x["session"].unique() if s)
        ses = st.selectbox("Session", ["Every session"] + sess, key=f"{key}_ses", label_visibility="collapsed")
    with c3:
        mods = sorted(s for s in x["model"].unique() if s)
        mod = st.selectbox("Setup", ["Every setup"] + mods, key=f"{key}_mod", label_visibility="collapsed")
    with c4:
        q = st.text_input("Search", key=f"{key}_q", placeholder="Search notes and mistakes",
                          label_visibility="collapsed")
    v = x
    if per != "All time":
        _last = x["when"].max()
        _from = (_last.normalize().replace(month=1, day=1) if per == "This year"
                 else _last.normalize() - pd.Timedelta(days=(29 if per == "Last 30 days" else 89)))
        v = v[v["when"] >= _from]
    if res == "Wins":
        v = v[v["r"] > 0.15]
    elif res == "Losses":
        v = v[v["r"] < -0.15]
    elif res == "Break-even":
        v = v[v["r"].abs() <= 0.15]
    elif res == "Flagged":
        v = v[v["flag"]]
    if ses != "Every session":
        v = v[v["session"] == ses]
    if mod != "Every setup":
        v = v[v["model"] == mod]
    if q.strip():
        needle = q.strip().lower()
        v = v[(v["notes"].str.lower().str.contains(needle, regex=False))
              | (v["mistake"].str.lower().str.contains(needle, regex=False))
              | (v["setup"].str.lower().str.contains(needle, regex=False))]
    if v.empty:
        st.caption("No trades match. Widen the filters.")
        return
    # Ten rows to start, grouped by week, so a long journal stays a list you
    # can scan rather than a wall (his note, 26 Sep: "once there's heaps of
    # trades, it could be too much")
    shown = int(st.session_state.get(f"{key}_n", 10))
    _wk = v["when"].dt.to_period("W-SUN")
    _wsum = v.groupby(_wk)["r"].agg(["size", "sum"])
    rows = ""
    _cur_wk = None
    for i, r in v.head(shown).iterrows():
        _p = _wk.loc[i]
        if _p != _cur_wk:
            _cur_wk = _p
            _n, _s = int(_wsum.loc[_p, "size"]), float(_wsum.loc[_p, "sum"])
            _sc = GREEN if _s > 0.15 else (RED if _s < -0.15 else t["muted"])
            rows += (f'<tr class="wk"><td colspan="7">Week of {_p.start_time.strftime("%d %b")}'
                     f'<span class="mu"> · {_n} trade{"s" if _n != 1 else ""} · </span>'
                     f'<b style="color:{_sc};">{_h.escape(fmt_r(_s, 1))}</b></td></tr>')
        rc = GREEN if r["r"] > 0.15 else (RED if r["r"] < -0.15 else t["muted"])
        tags = ""
        if r["aplus"] is True:
            tags += '<span class="tg good">A+</span>'
        if r["mistake"]:
            tags += f'<span class="tg bad">{_h.escape(r["mistake"][:40])}</span>'
        if r["rules"] is False:
            tags += '<span class="tg bad">rule broken</span>'
        setup = _h.escape(r["setup"] or "—") + (f' <span class="mu">· {_h.escape(r["tf"])}</span>' if r["tf"] else "")
        rows += (f'<tr><td class="w"><b>{r["when"].strftime("%a %d %b")}</b> <span class="mu">{r["when"].strftime("%H:%M") if r["when"].hour or r["when"].minute else ""}</span></td>'
                 f'<td class="m">{_h.escape(r["session"])}</td><td>{setup}'
                 + (f'<div class="tgm">{tags}</div>' if tags else '')
                 + f'</td><td class="m mu">{_h.escape(r["dir"])}</td>'
                 f'<td class="rv" style="color:{rc};">{_h.escape(fmt_r(r["r"]))}</td><td class="m">{_path_svg(r)}</td><td class="m">{tags}</td></tr>')
    extra = f"""
.ea-tx{{border-collapse:collapse !important;width:100%;font-size:13.5px;border:0 !important;}}
.ea-tx th{{font-size:11px;font-weight:700;letter-spacing:.06em;color:{t['muted']};text-transform:uppercase;text-align:left;
  padding:7px 8px !important;border:0 !important;border-bottom:1px solid {t['line']} !important;background:none !important;white-space:nowrap;}}
.ea-tx td{{padding:8px 8px !important;border:0 !important;border-bottom:1px solid {t['line']} !important;vertical-align:middle;color:{t['ink']};background:none !important;}}
.ea-tx tr{{background:none !important;}}
.ea-tx td.w{{white-space:nowrap;}} .ea-tx td.rv{{font-weight:800;white-space:nowrap;}}
.ea-tx tr.wk td{{font-size:12px;font-weight:700;letter-spacing:.02em;padding:14px 8px 5px !important;
  color:{t['ink']};border-bottom:1px solid {t['line']} !important;}}
.ea-tx .mu{{color:{t['muted']};}}
.ea-tx .tg{{display:inline-block;font-size:11.5px;font-weight:700;border-radius:6px;padding:1px 7px;margin:1px 4px 1px 0;}}
.ea-tx .tg.good{{background:{'#12301f' if _dark() else '#dcfce7'};color:{'#86efac' if _dark() else '#14532d'};}}
.ea-tx .tg.bad{{background:{'#3a1d22' if _dark() else '#fde8e8'};color:{'#fca5a5' if _dark() else '#7f1d1d'};}}
.ea-tx .tgm{{display:none;margin-top:3px;}}
@media (max-width:640px){{.ea-tx td.m,.ea-tx th.m{{display:none;}} .ea-tx .tgm{{display:block;}}}}
"""
    st.markdown(css(extra) + '<div class="ea-rx ea-rx-scroll"><table class="ea-tx"><tr><th>When</th><th class="m">Session</th>'
                '<th>Setup</th><th class="m">Dir</th><th>R</th><th class="m">Path (worst → best, ● exit)</th><th class="m">Tags</th></tr>'
                f'{rows}</table></div>', unsafe_allow_html=True)
    n_all = len(v)
    cap_ = f"Showing {min(shown, n_all)} of {n_all}. Flagged = your Rules tag says No, or a mistake is logged."
    b1, b2 = st.columns([3, 1], vertical_alignment="center")
    with b1:
        st.caption(cap_)
    with b2:
        if n_all > shown and st.button(f"Show {min(20, n_all - shown)} more", key=f"{key}_more",
                                       use_container_width=True):
            st.session_state[f"{key}_n"] = shown + 20
            st.rerun()

    # the trade card
    st.markdown("#### Open a trade")
    lab = {f'{r["when"].strftime("%a %d %b %Y %H:%M")} · {r["setup"] or "no setup"} · {fmt_r(r["r"])}': i
           for i, r in v.iterrows()}
    pick = st.selectbox("Trade", list(lab), index=0, key=f"{key}_pick", label_visibility="collapsed")
    r = v.loc[lab[pick]]
    same = x[(x["model"] == r["model"]) & (x["session"] == r["session"])] if r["model"] else x.iloc[0:0]
    same_tf = x[(x["model"] == r["model"]) & (x["tf"] == r["tf"])] if (r["model"] and r["tf"]) else x.iloc[0:0]
    rec = ""
    if len(same) >= 2:
        rec = (f'<b>Your record with this setup:</b> {_h.escape(r["model"])} in {_h.escape(r["session"] or "any session")}: '
               f'<b>{len(same)} trades, {_h.escape(fmt_r(same["r"].mean()))} average, '
               f'{(same["r"] > 0.15).mean() * 100:.0f}% won</b>.')
        if len(same_tf) >= 2:
            rec += f' On the {_h.escape(r["tf"])}: {len(same_tf)} trades, {_h.escape(fmt_r(same_tf["r"].mean()))} average.'
    kv = dict(r["tags"])
    if r["aplus"] is not None:
        kv["A+ setup"] = "Yes" if r["aplus"] else "No"
    if r["rules"] is not None:
        kv["Rules followed"] = "Yes" if r["rules"] else "No"
    if r["mistake"]:
        kv["Mistake"] = r["mistake"]
    if pd.notna(r["mfe"]) and r["mfe"] > 0 and r["r"] > 0.15:
        kv["Captured"] = f"{min(100, r['r'] / r['mfe'] * 100):.0f}% of the move"
    kvh = "".join(f'<div><div class="k">{_h.escape(k)}</div><div class="v">{_h.escape(str(vv))}</div></div>'
                  for k, vv in kv.items())
    rc = GREEN if r["r"] > 0.15 else (RED if r["r"] < -0.15 else t["muted"])
    notes = (f'<div class="nt">{_h.escape(r["notes"])}</div>' if r["notes"] else
             '<div class="nt mu">No notes on this trade.</div>')
    extra = f"""
.ea-tc{{border:1px solid {'#4c3a99' if _dark() else '#c4b5fd'};border-radius:14px;padding:16px 18px;background:{t['base']};}}
.ea-tc .top{{display:flex;justify-content:space-between;gap:12px;align-items:flex-start;}}
.ea-tc .e{{font-size:11.5px;font-weight:700;letter-spacing:.07em;color:{t['muted']};}}
.ea-tc .h{{font-size:19px;font-weight:800;color:{t['ink']};margin-top:2px;}}
.ea-tc .r{{font-size:28px;font-weight:800;white-space:nowrap;}}
.ea-tc .kv{{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:8px;margin-top:8px;}}
.ea-tc .kv>div{{background:{t['soft']};border:1px solid {t['line']};border-radius:10px;padding:8px 11px;}}
.ea-tc .k{{font-size:10.5px;font-weight:700;letter-spacing:.06em;color:{t['muted']};text-transform:uppercase;}}
.ea-tc .v{{font-size:14px;font-weight:700;color:{t['ink']};margin-top:1px;}}
.ea-tc .rec{{background:{'#221c44' if _dark() else '#f3f0ff'};border-radius:10px;padding:10px 13px;margin-top:12px;font-size:14px;line-height:1.5;color:{t['ink']};}}
.ea-tc .nt{{font-size:14px;color:{t['ink']};background:{t['soft']};border:1px dashed {t['line']};border-radius:10px;padding:9px 12px;margin-top:10px;white-space:pre-wrap;}}
.ea-tc .mu{{color:{t['muted']};}}
.ea-tc a.nl{{display:inline-block;margin-top:12px;font-size:13.5px;font-weight:700;color:{'#b3a1ff' if _dark() else PURPLE};text-decoration:none;}}
.ea-tc a.nl:hover{{text-decoration:underline;}}
"""
    when = r["when"].strftime("%a %d %b %Y") + (f' · {r["when"].strftime("%H:%M")}' if r["when"].hour or r["when"].minute else "")
    head = " · ".join(x_ for x_ in (r["setup"], r["tf"], r["dir"]) if x_) or "Trade"
    card = (f'<div class="ea-rx ea-tc"><div class="top"><div><div class="e">{_h.escape(when.upper())}'
            f'{(" · " + _h.escape(r["session"].upper())) if r["session"] else ""}</div>'
            f'<div class="h">{_h.escape(head)}</div></div><div class="r" style="color:{rc};">{_h.escape(fmt_r(r["r"]))}</div></div>'
            f'<div class="e" style="margin-top:12px;">HOW THE TRADE MOVED</div>{_big_path(r)}'
            f'<div class="kv">{kvh}</div>'
            + (f'<div class="rec">{rec}</div>' if rec else "")
            + f'<div class="e" style="margin-top:12px;">YOUR NOTES</div>{notes}'
            + (f'<a class="nl" href="{_h.escape(r["url"])}" target="_blank" rel="noopener">'
               'Open this trade in Notion \u2197</a>' if r.get("url") else "")
            + '</div>')
    st.markdown(css(extra) + card, unsafe_allow_html=True)


# ── share card (mockup V7): an R-only image for the group ────────────────────
def share_card_png(eyebrow: str, big: str, big_sub: str, lines: list, spark: list,
                   positive: bool = True) -> bytes:
    """1200×630 PNG for Discord. R only by construction: callers pass R
    strings, never a balance, lot size or dollar figure."""
    import io
    import os
    import numpy as np
    from PIL import Image, ImageDraw, ImageFont

    W, H = 1200, 630
    yy, xx = np.mgrid[0:H, 0:W]
    tt = np.clip((xx / W) * 0.65 + (yy / H) * 0.35, 0, 1)[..., None]
    c0, c1, c2 = np.array([11, 11, 26]), np.array([29, 11, 82]), np.array([58, 18, 184])
    rgb = np.where(tt < 0.7, c0 + (c1 - c0) * (tt / 0.7), c1 + (c2 - c1) * ((tt - 0.7) / 0.3))
    im = Image.fromarray(rgb.astype("uint8"), "RGB")
    d = ImageDraw.Draw(im)

    def font(sz):
        return ImageFont.load_default(size=sz)

    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    logo_p = os.path.join(root, "assets", "edge_logo_bar_dark.png")
    if os.path.exists(logo_p):
        lg = Image.open(logo_p).convert("RGBA")
        lg = lg.resize((int(lg.width * 62 / lg.height), 62))
        im.paste(lg, (56, 48), lg)
    d.text((W - 56, 70), eyebrow.upper(), font=font(24), fill=(196, 181, 253), anchor="ra")
    col = (74, 222, 128) if positive else (248, 113, 113)
    d.text((56, 170), big, font=font(150), fill=col, stroke_width=4, stroke_fill=col)
    d.text((60, 345), big_sub, font=font(30), fill=(203, 213, 225))
    y = 190
    for ln in lines[:4]:
        d.text((720, y), ln, font=font(32), fill=(237, 233, 254), stroke_width=1, stroke_fill=(237, 233, 254))
        y += 52
    vals = [float(v) for v in spark if v == v]
    if len(vals) >= 2:
        lo, hi = min(vals), max(vals)
        rng = (hi - lo) or 1.0
        x0, x1, y0, y1 = 56, W - 56, 430, 540
        pts = [(x0 + (x1 - x0) * i / (len(vals) - 1), y1 - (v - lo) / rng * (y1 - y0)) for i, v in enumerate(vals)]
        d.line(pts, fill=(167, 139, 250), width=5, joint="curve")
    d.text((56, H - 44), "R only · no balances", font=font(22), fill=(148, 163, 184))
    d.text((W - 56, H - 44), "Edge Analysis", font=font(22), fill=(148, 163, 184), anchor="ra")
    buf = io.BytesIO()
    im.save(buf, "PNG", optimize=True)
    return buf.getvalue()


# ── journal health (mockup V8) ───────────────────────────────────────────────
TAG_COLS = ["A+ Setup?", "Conviction (1-5)", "Mental State", "Mistake", "Rules Followed?"]
_RULE_MISTAKES = ("no a+ setup", "overtraded", "revenge traded", "revenge trade", "outside session")
_NO_MISTAKE = ("na", "none", "no mistake")


def _blank(v, mistake: bool = False) -> bool:
    if isinstance(v, bool):
        return False
    s = _txt(v).lower() if not isinstance(v, str) else v.strip().lower()
    if mistake and s in _NO_MISTAKE:
        return False
    return s in ("", "nan", "none", "na", "[]", "null", "nat")


def used_tags(df: pd.DataFrame, cols=None) -> list:
    """The hand tags this journal actually uses (filled on 10%+ of trades).
    A field the trader never fills (his Conviction) is not a gap on every
    trade: counting it read "0% complete, 23 need tagging" (26 Sep)."""
    if df is None or df.empty:
        return []
    return [c for c in (cols or TAG_COLS) if c in df.columns
            and (~df[c].map(lambda v, _m=(c == "Mistake"): _blank(v, _m))).mean() >= 0.10]


def journal_health(df: pd.DataFrame) -> dict:
    """Completeness plus each specific problem found, with its count and fix.
    Every check is plain counting; nothing here is a verdict on the trading."""
    out = dict(pct=100.0, full=0, total=0, problems=[], fill=[])
    if df is None or df.empty:
        return out
    g = df.copy()
    n = len(g)
    tags = used_tags(g)
    out["total"] = n
    if len(tags) >= 2:
        full_mask = g.apply(lambda r: not any(_blank(r.get(c), c == "Mistake") for c in tags), axis=1)
        out["full"] = int(full_mask.sum())
        out["pct"] = 100.0 * out["full"] / max(1, n)
        # untagged run at the end of the journal: tagging stopped
        if "Date" in g.columns and not full_mask.all():
            order = pd.to_datetime(g["Date"], errors="coerce").sort_values().index
            tail = 0
            for i in reversed(list(order)):
                if full_mask.get(i, True):
                    break
                tail += 1
            untagged = int((~full_mask).sum())
            if tail >= 2:
                since = pd.to_datetime(g.loc[list(order)[-tail], "Date"]).strftime("%a %d %b")
                out["problems"].append(("bad", tail, f"{tail} trades need tagging",
                                        f"Nothing hand-tagged since {since}. Until they are, setups, "
                                        "psychology and discipline run on stale data.",
                                        "Tag them in Notion"))
            elif untagged:
                out["problems"].append(("warn", untagged, f"{untagged} trade{'s' if untagged != 1 else ''} not fully tagged",
                                        "Missing one of: " + ", ".join(c.replace("?", "") for c in tags) + ".",
                                        "Fill the gaps in Notion"))
    # rules ticked but a rule-type mistake logged
    if "Rules Followed?" in g.columns and "Mistake" in g.columns:
        rk = g["Rules Followed?"].map(_yes)
        mk = g["Mistake"].map(_txt).str.lower()
        clash = (rk.eq(True)) & mk.apply(lambda s: any(m in s for m in _RULE_MISTAKES))
        if "A+ Setup?" in g.columns:
            clash |= g["A+ Setup?"].map(_yes).eq(True) & mk.str.contains("no a+ setup", regex=False)
        k = int(clash.sum())
        if k:
            out["problems"].append(("warn", k, f"{k} trade{'s' if k != 1 else ''} contradict{'s' if k == 1 else ''} itself" if k == 1
                                    else f"{k} trades contradict themselves",
                                    "Rules Followed says yes (or A+ says yes), but the mistake logged is a rule break "
                                    "(no A+ setup, overtraded, revenge).", "Review them"))
    # MAE measured past the close on losing trades
    if "MAE (R)" in g.columns and "Closed RR" in g.columns:
        mae = pd.to_numeric(g["MAE (R)"], errors="coerce")
        r = pd.to_numeric(g["Closed RR"], errors="coerce")
        past = (r < -0.15) & (mae < r - 0.5)
        k = int(past.sum())
        if k:
            out["problems"].append(("info", k, f"MAE runs past the exit on {k} loss{'es' if k != 1 else ''}",
                                    f"Worst dips as deep as {fmt_r(float(mae[past].min()))} on trades that closed near "
                                    f"{fmt_r(float(r[past].median()), 1)}. The MAE is measured after the close, so heat "
                                    "stats read deeper than they were.", "Check the sync"))
    # fields nobody fills are listed once, in Plan → My template ("Never
    # used: ..."); this card said it too, with a different count (4 vs 3)
    # fill rate: automatic vs hand-tagged
    auto = [c for c in ("Closed RR", "Session", "Direction", "MFE (R)", "MAE (R)") if c in g.columns]
    # (28 Sep check: the hand-tag bar repeated the ring's % a third time, and
    # "75%" beside "95% complete" never said what the 25% was) — one bar, for
    # the synced fields, naming the ones that are short
    if auto:
        pct = float(pd.concat([~g[c].map(_blank) for c in auto], axis=1).all(axis=1).mean() * 100)
        short = [(c, int(g[c].map(_blank).sum())) for c in auto]
        short = [f"{c.replace(' (R)', '')} on {k}" for c, k in short if k]
        out["fill"].append(("Synced fields" + (" \u2014 missing " + ", ".join(short) if short else ""), pct))
    return out


def journal_health_card(h: dict) -> None:
    t = _tokens()
    pct = int(round(h["pct"]))
    kinds = {"bad": RED, "warn": "#b45309", "info": "#6366f1", "mu": t["muted"]}
    rows = ""
    for kind, n, title, detail, action in h["problems"]:
        c = kinds.get(kind, t["muted"])
        rows += (f'<div class="jr"><div class="jn" style="color:{c};background:{c}1f;">{n}</div>'
                 f'<div class="jt"><b>{_h.escape(title)}</b><div>{_h.escape(detail)}</div></div>'
                 f'<div class="ja" style="color:{c};">{_h.escape(action)}</div></div>')
    fill = "".join(f'<div class="fr"><div class="fl"><span>{_h.escape(a)}</span><b>{b:.0f}%</b></div>'
                   f'<div class="fb"><div style="width:{max(b, 1.5):.0f}%;background:{GREEN if b >= 90 else ("#f59e0b" if b >= 50 else RED)};"></div></div></div>'
                   for a, b in h["fill"])
    # the % lives in the ring; the headline says it in trades
    head = (f"{h['full']} of {h['total']} trades carry every hand tag" if pct < 100 else "Every trade is fully tagged")
    sub = ("Every number on this site is only as good as this."
           if pct < 100 else "Nice. The checks below still look for contradictions and gaps.")
    extra = f"""
.ea-jh{{display:flex;gap:22px;align-items:center;flex-wrap:wrap;}}
.ea-jh .hm{{flex:1 1 300px;min-width:0;}}
.ea-jh .hh{{font-size:19px;font-weight:800;color:{t['ink']};}}
.ea-jh .hs{{font-size:14px;color:{t['muted']};margin-top:3px;line-height:1.45;}}
.ea-jh .fills{{flex:1 1 260px;}}
.ea-jh .fr{{margin:6px 0;}} .ea-jh .fl{{display:flex;justify-content:space-between;font-size:12.5px;color:{t['ink']};gap:8px;}}
.ea-jh .fb{{background:{t['h1']};border-radius:6px;height:8px;margin-top:3px;overflow:hidden;}} .ea-jh .fb div{{height:8px;border-radius:6px;}}
.ea-jp{{margin-top:12px;display:flex;flex-direction:column;gap:8px;}}
.ea-jp .jr{{display:flex;gap:14px;align-items:flex-start;border:1px solid {t['line']};border-radius:12px;padding:11px 14px;background:{t['base']};}}
.ea-jp .jn{{flex:none;min-width:44px;height:44px;border-radius:12px;font-size:17px;font-weight:800;display:flex;align-items:center;justify-content:center;padding:0 6px;}}
.ea-jp .jt{{flex:1;min-width:0;font-size:13.5px;color:{t['muted']};line-height:1.45;}}
.ea-jp .jt b{{display:block;font-size:15px;color:{t['ink']};}}
.ea-jp .ja{{flex:none;font-size:12.5px;font-weight:700;white-space:nowrap;}}
@media (max-width:640px){{.ea-jp .jr{{flex-wrap:wrap;}} .ea-jp .ja{{flex-basis:100%;padding-left:58px;margin-top:-4px;}}}}
"""
    ring = _ring(pct, 112, what="fully tagged", name="Journal completeness")
    body = (f'<div class="ea-rx"><div class="ea-jh">{ring}<div class="hm"><div class="hh">{_h.escape(head)}</div>'
            f'<div class="hs">{_h.escape(sub)}</div></div><div class="fills">{fill}</div></div>'
            + (f'<div class="ea-jp">{rows}</div>' if rows else "") + '</div>')
    st.markdown(css(extra) + body, unsafe_allow_html=True)
