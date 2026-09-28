"""Externals: one card per market factor (28 Sep).

His notes, 28 Sep: "why don't we have anything on the website for gaps" and
"only have Market conditions in externals and nothing else?". Round 11 had
folded every market tag into one board of coloured segments; gaps were its
last thin row. Each factor the journal logs now gets its own card in the
house style: one sentence, then the plain ranked rows (reshape.ranked_rows).
A factor with only one real value says so in one honest line. Fields the
journal has but never fills are named once, at the bottom of the view.
"""
from __future__ import annotations

import html as _h

import pandas as pd
import streamlit as st

from edge_analysis.ui import reshape as rx

# (key, card title, card subtitle, [(column, block label)], yes/no words, what a tick means)
FACTORS = [
    ("trend", "Trend or range", "Was the market trending or ranging when you entered, on each timeframe you log?",
     [("Conditions MTF", "MTF"), ("Conditions HTF", "HTF"), ("Conditions ETF", "ETF")], None, None),
    ("ows", "Opposing weak structure", "Trades taken with weak structure in the way, against the clear ones.",
     [("Opposing Weak Structure?", None)], ("Into weak structure", "Clear"), "that has weak structure in the way"),
    ("tier", "Pricing tier", "Which tier of pricing each entry sat in.",
     [("Tiers in pricing MTF", "MTF"), ("Tiers in pricing HTF", "HTF")], None, None),
    ("news", "News", "What the news was doing around each trade.",
     [("News Aspect", None)], None, None),
    ("gap", "Gaps", "Trades lined up with a gap, against the rest.",
     [("GAP Alignment", None), ("GAP Alignment?", None)], ("Gap aligned", "No gap"), "that lines up with a gap"),
    ("vol", "Volatility", "How volatile the market was, on your own scale.",
     [("Volatility", None)], None, None),
    ("obos", "Overbought / oversold", "Entries at an overbought or oversold extreme, against the rest.",
     [("Oversold or Overbought?", None)], ("At an extreme", "Not at an extreme"), "taken at an extreme"),
]
# the journal field to name when a factor is never filled
FIELD = {"trend": "Conditions", "ows": "Opposing Weak Structure", "tier": "Tiers in pricing",
         "news": "News Aspect", "gap": "GAP Alignment", "vol": "Volatility", "obos": "Oversold or Overbought"}
_NO_WORDS = {"no", "false", "__no__", "0", ""}


def factor_values(df: pd.DataFrame, col: str, yes_no=None) -> pd.Series | None:
    """One label per trade for a logged factor column, "" where untagged, or
    None when the column is absent or never filled (a checkbox never ticked
    reads as not logged, not as "No" on every trade)."""
    if df is None or col not in df.columns:
        return None
    raw = df[col]
    yn = raw.map(rx._yes)
    as_flag = col.endswith("?") or (yn.notna().all() and set(raw.map(rx._txt).str.lower()) <= {"yes", "no", "true", "false", ""})
    if as_flag:
        if not (yn == True).any():      # noqa: E712  never ticked
            return None
        y, n = yes_no or ("Yes", "No")
        return yn.map(lambda v: y if v is True else (n if v is False else ""))
    vals = raw.map(rx._txt).str.split(",").str[0].str.strip()
    if col == "News Aspect":
        vals = vals.map(lambda v: rx._news_bucket(v) if v else v)
    if not vals.ne("").any():
        return None
    return vals


def _blocks(g: pd.DataFrame, spec) -> list:
    key, _t, _s, cols, yes_no, _what = spec
    out, seen = [], set()
    for col, label in cols:
        v = factor_values(g, col, yes_no)
        if v is None:
            continue
        base = col.rstrip("?")
        if base in seen:            # GAP Alignment and GAP Alignment? are one field
            continue
        seen.add(base)
        m = v != ""
        if int(m.sum()) < 3:
            continue
        out.append((label, v[m], g[m]))
    return out


def logged(df: pd.DataFrame, spec) -> bool:
    return bool(_blocks(rx._counted(df), spec)) if df is not None and not df.empty else False


def factor_board(df: pd.DataFrame, spec, verdicts: bool = True) -> bool:
    """The card body for one factor. False when the journal doesn't log it."""
    if df is None or df.empty:
        return False
    g = rx._counted(df)
    blocks = _blocks(g, spec)
    if not blocks:
        return False
    key, title, _sub, cols, yes_no, what = spec
    t = rx._tokens()
    # one real value per block (all but a trade or two on one side): one honest line
    rows_by = [(label, rx.group_rows(sub, v)) for label, v, sub in blocks]
    thin = all(len(rows) < 2 or sorted(r["n"] for r in rows)[-2] < rx.STATE_MIN for _l, rows in rows_by)
    if thin:
        bits = []
        for label, rows in rows_by:
            by_n = sorted(rows, key=lambda r: -r["n"])
            top, rest = by_n[0], by_n[1:]
            where = f" ({label})" if label and len(rows_by) > 1 else ""
            tagged = sum(r["n"] for r in rows)
            if yes_no and rest and rest[0]["m"] == yes_no[0]:
                y = rest[0]
                _each = "" if y["n"] == 1 else " a trade"
                bits.append(f"You ticked it on <b>{y['n']} of {tagged}</b> trades{where} "
                            f"({_h.escape(rx.fmt_r(y['exp']))}{_each}); the other {top['n']} average "
                            f"{_h.escape(rx.fmt_r(top['exp']))}.")
            else:
                s = (f"<b>{top['n']} of {tagged}</b> tagged trades{where} were <b>{_h.escape(top['m'])}</b>, "
                     f"averaging {_h.escape(rx.fmt_r(top['exp']))} a trade.")
                if rest:
                    s += " The rest: " + "; ".join(
                        f"<b>{_h.escape(r['m'])}</b>, {r['n']} trade{'s' if r['n'] != 1 else ''} at "
                        f"{_h.escape(rx.fmt_r(r['exp']))}" for r in rest) + "."
                bits.append(s)
        tail = (f" That's too few to compare yet — tick {_h.escape(FIELD[key])} on every trade "
                f"{what}, and this becomes a comparison once {rx.STATE_MIN} are ticked." if yes_no else
                f" No other value has {rx.STATE_MIN} trades yet, so there's nothing to compare.")
        st.markdown(rx.css(f".ea-ms1{{font-size:15px;line-height:1.55;color:{t['ink']};background:{t['soft']};"
                           f"border:1px solid {t['line']};border-radius:10px;padding:12px 14px;margin:2px 0 6px;}}")
                    + f'<div class="ea-rx"><div class="ea-ms1">{" ".join(bits)}{tail}</div></div>',
                    unsafe_allow_html=True)
        return True
    # the claims are tested across every value on the card, both directions (Holm)
    from edge_analysis.digest import _perm_p, _holm_pass
    keys, ps = [], []
    for (label, rows), (_l, _v, sub) in zip(rows_by, blocks):
        x = sub["__r"]          # each value against the rest of the trades that carry this tag
        for r in rows:
            if rx.PAIR_FEW <= r["n"] < len(x) - 1:
                m = pd.Series(x.index.isin(r["idx"]), index=x.index)
                for d in ("good", "bad"):
                    keys.append((label, r["m"], d))
                    ps.append(_perm_p(x, m, lower=d == "bad"))
    passed = {keys[i] for i in _holm_pass(ps)} if ps else set()

    def lab(label, r, d):
        return "beats chance" if (label, r["m"], d) in passed else "early read"

    def said(label, r, d):
        return verdicts or (label, r["m"], d) in passed

    bits = []
    for label, rows in rows_by:
        ok = [r for r in rows if r["n"] >= 3]
        if len(ok) < 2:
            continue
        best, worst = ok[0], ok[-1]
        where = f" on the {label}" if label and len(rows_by) > 1 else ""
        part = []
        if best["exp"] > 0 and said(label, best, "good"):
            part.append(f"<b>{_h.escape(best['m'])}</b>{where} leads at {_h.escape(rx.fmt_r(best['exp']))} a trade over "
                        f"{best['n']} <span class='ea-pl-l'>{lab(label, best, 'good')}</span>")
        if worst is not best and worst["exp"] < 0 and said(label, worst, "bad"):
            part.append(f"<b>{_h.escape(worst['m'])}</b>{where} costs {_h.escape(rx.fmt_r(worst['exp']))} a trade over "
                        f"{worst['n']} <span class='ea-pl-l'>{lab(label, worst, 'bad')}</span>")
        if part:
            bits.append("; ".join(part))
    head = (". ".join(bits) + ".") if bits else "Each row is what trades with that tag paid, best first."
    many = len(rows_by) > 1
    for i, (label, rows) in enumerate(rows_by):
        if many:
            # the column header hides on a phone, so a card with a block per
            # timeframe names each block where every screen shows it
            if i == 0:
                st.markdown(rx.css(f".ea-rx-top{{font-size:15px;line-height:1.5;margin:0 0 10px;color:{t['ink']};}}"
                                   f".ea-rx-k{{font-size:12px;font-weight:800;letter-spacing:.06em;"
                                   f"text-transform:uppercase;color:{t['muted']};margin:6px 0 6px;}}")
                            + f'<div class="ea-rx"><div class="ea-rx-top">{head}</div></div>', unsafe_allow_html=True)
            st.markdown(f'<div class="ea-rx"><div class="ea-rx-k">On the {_h.escape(label)}</div></div>',
                        unsafe_allow_html=True)
        rx.ranked_rows(rows, [f"<span>{_h.escape(r['m'])}</span>" for r in rows], "" if many else head,
                       label or title, cap=i == len(rows_by) - 1)
    return True


def never_filled(df: pd.DataFrame) -> list[str]:
    """The external fields this journal has as columns but never fills, by
    their journal names ("Conditions HTF", not the whole trend factor)."""
    if df is None or df.empty:
        return []
    out, seen = [], set()
    for spec in FACTORS:
        key, _t, _s, cols, yes_no, _w = spec
        for c, _l in cols:
            base = c.rstrip("?")
            if c in df.columns and base not in seen:
                seen.add(base)
                if factor_values(df, c, yes_no) is None and not any(
                        o.rstrip("?") == base and o in df.columns and factor_values(df, o, yes_no) is not None
                        for o, _ in cols if o != c):
                    out.append(base)
    return out
