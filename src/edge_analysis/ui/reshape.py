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


def css() -> str:
    """The reshape components' stylesheet for the current theme. Blank lines
    are stripped: a Markdown <style> block ends at the first one."""
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
.ea-hm th.l{{width:72px;}}
.ea-hm td.name{{padding-right:10px !important;}}
.ea-hm th{{font-size:12px;font-weight:700;color:{t['muted']};text-align:center;padding:2px 4px;white-space:nowrap;}}
.ea-hm th.l{{text-align:left;}}
.ea-hm td{{border-radius:8px;text-align:center;padding:8px 4px;font-size:15px;font-weight:800;
  font-variant-numeric:tabular-nums;background:{t['h1']};color:{t['ink']};}}
.ea-hm td small{{display:block;font-size:11px;font-weight:600;opacity:.8;}}
.ea-hm td.name{{text-align:left;background:none;font-size:13.5px;font-weight:700;padding-left:0;white-space:nowrap;color:{t['ink']};}}
.ea-hm td.few{{background:repeating-linear-gradient(135deg,{t['h1']} 0 6px,{t['h2']} 6px 12px);color:{t['few']};font-weight:700;}}
.ea-hm td.none{{background:{t['soft']};color:{t['few']};font-weight:600;font-size:12px;}}
.ea-hm td.tot{{box-shadow:inset 0 0 0 2px {t['base']};}}
.ea-hm tr.tot td.name{{color:{t['muted']};}}
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
              total_row_label: str = "All", total_col_label: str = "All") -> None:
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
    st.markdown(css() + f'<div class="ea-rx ea-rx-scroll"><table class="ea-hm"><tr><th class="l">{_h.escape(row_head)}</th>'
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
