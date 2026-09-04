from __future__ import annotations
import pandas as pd
import streamlit as st
import html as _h

def show_light_table(df: pd.DataFrame, hide_index: bool = True):
    if df is None or df.empty:
        st.info("No rows.")
        return
    df2 = df.copy()
    for col in df2.columns:
        if df2[col].map(lambda x: isinstance(x, list)).any():
            df2[col] = df2[col].apply(lambda v: ", ".join(v) if isinstance(v, list) else v)
    if hide_index:
        df2 = df2.reset_index(drop=True)
    thead = "".join(f"<th>{str(c)}</th>" for c in df2.columns)
    rows = []
    for _, r in df2.iterrows():
        tds = "".join(f"<td>{'' if pd.isna(v) else str(v)}</td>" for v in r)
        rows.append(f"<tr>{tds}</tr>")
    tbody = "".join(rows)
    html = f"<div class='table-wrap'><table><thead><tr>{thead}</tr></thead><tbody>{tbody}</tbody></table></div>"
    st.markdown(html, unsafe_allow_html=True)

def _fmt_int(v):
    return "" if pd.isna(v) else f"{int(v)}"

def _fmt_num(v, d: int = 2):
    """Trim decimal noise: 28.00 -> 28, 33.30 -> 33.3, 0.39 stays 0.39."""
    if pd.isna(v):
        return ""
    out = f"{float(v):.{d}f}".rstrip("0").rstrip(".")
    return out if out not in ("", "-", "-0") else "0"

def _fmt_signed(v, d: int = 2):
    """Signed R figures: +0.32, -1.5, 0 — the sign is the point of the column."""
    if pd.isna(v):
        return ""
    f = round(float(v), d)
    if f == 0:
        return "0"
    out = f"{f:+.{d}f}".rstrip("0").rstrip(".")
    return out

def _split_small(df, min_n: int = 3):
    """Every row shows (his ruling: hiding is annoying in both directions).
    The doctrine's minimum-sample rule still gates VERDICTS, never data."""
    return df, 0


def _small_note(hidden: int):
    return None


# One column spec per known metric: header label, formatter, sign colouring,
# and a short label the phone stylesheet swaps in (a 64px column can't hold
# "Expectancy" without breaking it mid-word).
_COL_SPECS = {
    "Trades":         ("Trades",          lambda v: _fmt_int(v),       False, "Trades"),
    "Win %":          ("Win %",           lambda v: _fmt_num(v, 1),    False, "Win %"),
    "BE %":           ("BE %",            lambda v: _fmt_num(v, 1),    False, "BE %"),
    "Loss %":         ("Loss %",          lambda v: _fmt_num(v, 1),    False, "Loss %"),
    "Net PnL (R)":    ("Net R",           lambda v: _fmt_signed(v, 1), True,  "Net R"),
    "Expectancy (R)": ("Expectancy (R)",  lambda v: _fmt_signed(v, 2), True,  "Exp (R)"),
    "Avg RR":         ("Avg R",           lambda v: _fmt_signed(v, 2), True,  "Avg R"),
    "Profit Factor":  ("Profit factor",   lambda v: _fmt_num(v, 2),    False, "PF"),
}


def _render_perf_table(df: pd.DataFrame, key_col: str, first_label: str,
                       title: str | None) -> None:
    """The one table renderer behind every per-category performance table
    (entry models, sessions, days, timeframes, assets, criteria ...).

    Rows under 3 trades render dimmed, never hidden. R columns are signed and
    coloured by sign; percentages carry one decimal at most. `title` is
    optional — sections that already have a heading pass None so nothing is
    printed twice."""
    df, _hidden = _split_small(df)
    if df is None or df.empty:
        return
    present = [c for c in _COL_SPECS if c in df.columns]
    headers = [f'<th class="text">{_h.escape(first_label)}</th>']
    for c in present:
        _full, _short = _COL_SPECS[c][0], _COL_SPECS[c][3]
        if _short == _full:
            headers.append(f'<th class="num">{_h.escape(_full)}</th>')
        else:
            headers.append(f'<th class="num"><span class="lab-full">{_h.escape(_full)}</span>'
                           f'<span class="lab-short">{_h.escape(_short)}</span></th>')
    rows = []
    for _, r in df.iterrows():
        cells = [f'<td class="text">{_h.escape(str(r.get(key_col, "")))}</td>']
        for c in present:
            _lab, _fmt, _signed, _sh = _COL_SPECS[c]
            v = r.get(c)
            cls = "num"
            if _signed and not pd.isna(v):
                try:
                    fv = float(v)
                    cls += " pos" if fv > 0 else (" neg" if fv < 0 else "")
                except (TypeError, ValueError):
                    pass
            cells.append(f'<td class="{cls}">{_fmt(v)}</td>')
        try:
            _dim_n = float(r.get("Trades") or 0)
        except (TypeError, ValueError):
            _dim_n = 0
        _dim = ' class="dim"' if _dim_n < 3 else ""
        rows.append(f"<tr{_dim}>{''.join(cells)}</tr>")
    _title_html = f"<h3 class='ea-tbl-title'>{_h.escape(title)}</h3>" if title else ""
    st.markdown(f"""
    <div class="entry-card">
      {_title_html}
      <div class="table-wrap">
        <table class="entry-model-table">
          <thead><tr>{''.join(headers)}</tr></thead>
          <tbody>{''.join(rows)}</tbody>
        </table>
      </div>
    </div>
    """, unsafe_allow_html=True)


def render_entry_model_table(df: pd.DataFrame, title: str | None = "Entry models",
                             first_col_label: str | None = None):
    """Per-category table keyed on `Entry_Model` (callers rename their key
    column to it). `first_col_label` names that column for the reader —
    "Criterion", "Pair", "Asset" ... — since not every caller ranks models."""
    if df is None or df.empty:
        return
    label = first_col_label or "Entry model"
    if "Entry_Model" not in df.columns and "Instrument" in df.columns:
        label = first_col_label or "Asset"
        df = df.rename(columns={"Instrument": "Entry_Model"}).copy()
    expected = ["Entry_Model", "Trades", "Win %", "BE %", "Loss %"]
    if any(c not in df.columns for c in expected):
        return
    _render_perf_table(df, "Entry_Model", label, title)

def render_session_performance_table(df: pd.DataFrame, title: str | None = "Sessions"):
    expected = ["Session", "Trades", "Win %", "BE %", "Loss %"]
    if df is None or df.empty or any(c not in df.columns for c in expected):
        return
    _render_perf_table(df, "Session", "Session", title)

def render_day_performance_table(df: pd.DataFrame, title: str | None = "Days (Mon–Fri)"):
    expected = ["Day", "Trades", "Win %", "BE %", "Loss %"]
    if df is None or df.empty or any(c not in df.columns for c in expected):
        return
    _render_perf_table(df, "Day", "Day", title)

def render_timeframe_table(df: pd.DataFrame, title: str | None = "Timeframes",
                           first_col_label: str = "Timeframe"):
    """
    Required columns: Entry_Model, Trades, Win %, BE %, Loss %
    Optional: Avg RR, Profit Factor
    """
    expected = ["Entry_Model", "Trades", "Win %", "BE %", "Loss %"]
    if df is None or df.empty or any(c not in df.columns for c in expected):
        return
    _render_perf_table(df, "Entry_Model", first_col_label, title)
