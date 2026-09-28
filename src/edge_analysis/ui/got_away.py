"""Managing the trade: what got away, said once (28 Sep).

The same leak was told three ways in three places: the "Left on winners" and
"Gave it back" tiles, "Provably left behind" under Manual close vs set TP,
and the Missed runners section with three more tiles. Four different R
figures for "what you left", none reconciled with the others. This is one
block: a sentence naming the biggest, then one row per way a trade can leak,
each with its trades and the R it cost. The rows overlap on purpose (one
trade can go +1R, come back and also be a missed runner), so they are never
summed.
"""
from __future__ import annotations

import html as _h

import pandas as pd
import streamlit as st

from edge_analysis.ui import reshape as rx

TOL = 0.1   # "reached the target" within 0.1R, as in Manual close vs set TP


def _num(df: pd.DataFrame, col: str):
    return pd.to_numeric(df[col], errors="coerce") if col in df.columns else None


def leaks(df: pd.DataFrame) -> list[dict]:
    """[{key, what, n, of, r}] — r is R given up (positive), biggest first."""
    g = rx._mgmt_frame(df)
    out = []
    if g is not None:
        gave = g[(g["mfe"] >= 1) & (g["r"] <= 0.15)]
        if len(gave):
            out.append(dict(key="gave", what="Went +1R, then closed at break-even or worse",
                            n=int(len(gave)), of=None, r=float((gave["mfe"] - gave["r"]).sum()),
                            how="peak minus close"))
        wins = g[g["r"] > 0.15]
        left = float((wins["mfe"] - wins["r"]).clip(lower=0).sum()) if len(wins) else 0.0
        if len(wins) and left > 0.05:
            out.append(dict(key="left", what="Winners closed before their best price",
                            n=int(len(wins)), of=None, r=left, how="best price minus close"))
    if df is not None and "Hit Full TP Without You" in df.columns:
        hit = df["Hit Full TP Without You"].astype(str).str.strip().str.lower()
        tagged = int(hit.isin(["yes", "no"]).sum())
        miss = df[hit == "yes"]
        rr, mfe = _num(miss, "Closed RR"), _num(miss, "MFE (R)")
        if len(miss) and rr is not None and mfe is not None:
            r = float((mfe - rr).clip(lower=0).sum())
            out.append(dict(key="missed", what="Ran to full TP after you closed (your tag)",
                            n=int(len(miss)), of=tagged, r=r, how="peak minus close"))
    prov = provable_left(df)
    if prov is not None and prov[0]:
        out.append(dict(key="cut", what="Cut early, then price reached your target",
                        n=prov[0], of=None, r=prov[1], how="target minus close"))
    return sorted(out, key=lambda d: -d["r"])


def provable_left(df: pd.DataFrame):
    """(trades, R) for early closes whose peak still reached the set target —
    the "provably left behind" of Manual close vs set TP; None without MFE."""
    if df is None or df.empty:
        return None
    tcol = next((c for c in ("Targeted RR", "Planned R:R", "Planned RR", "RR") if c in df.columns), None)
    rr, mfe = _num(df, "Closed RR"), _num(df, "MFE (R)")
    if tcol is None or rr is None or mfe is None:
        return None
    from edge_analysis.ui.mt5_tabs import _parse_tgt
    tgt = df[tcol].apply(_parse_tgt)
    tgt = pd.to_numeric(tgt, errors="coerce")
    ok = rr.notna() & tgt.notna() & (tgt > 0.3) & mfe.notna()
    early_tag = (df["Result"].astype(str).str.contains("Early Close", na=False)
                 if "Result" in df.columns else pd.Series(False, index=df.index))
    hit = (rr >= tgt - TOL) & ~early_tag
    stopped = (rr <= -0.85) & ~early_tag & (rr < tgt - TOL)
    early = ok & ~hit & ~stopped
    reached = early & (mfe >= tgt - TOL)
    return int(reached.sum()), float((tgt[reached] - rr[reached]).clip(lower=0).sum())


def what_got_away(df: pd.DataFrame) -> bool:
    rows = leaks(df)
    if not rows:
        return False
    t = rx._tokens()
    neg = "#f87171" if rx._dark() else rx.RED
    top = rows[0]
    what = top["what"][:1].lower() + top["what"][1:]      # "+1R" keeps its capital
    head = (f"The biggest leak: <b>{_h.escape(what)}</b> — {top['n']} "
            f"trade{'s' if top['n'] != 1 else ''}, <b style='color:{neg}'>{top['r']:.1f}R</b> "
            f"({_h.escape(top['how'])}).")
    if len(rows) > 1:
        head += " A trade can sit in more than one row, so they don't add up."
    span = max(r["r"] for r in rows) or 1.0
    body = ""
    for r in rows:
        w = max(2.0, r["r"] / span * 100)
        cnt = f"{r['n']} of {r['of']} tagged" if r["of"] else f"{r['n']} trade{'s' if r['n'] != 1 else ''}"
        body += (f'<div class="ea-ga-r"><div class="ea-ga-n">{_h.escape(r["what"])}'
                 f'<small>{cnt} · {_h.escape(r["how"])}</small></div>'
                 f'<div class="ea-ga-t"><i style="width:{w:.0f}%;background:{neg}"></i></div>'
                 f'<div class="ea-ga-v" style="color:{neg}">−{r["r"]:.1f}R</div></div>')
    extra = f"""
.ea-ga-head{{font-size:15px;line-height:1.5;margin:0 0 10px;color:{t['ink']};}}
.ea-ga-r{{display:grid;grid-template-columns:minmax(0,1.3fr) minmax(0,1fr) 80px;gap:14px;align-items:center;
  background:{t['soft']};border:1px solid {t['line']};border-radius:10px;padding:10px 12px;margin:0 0 6px;}}
.ea-ga-n{{font-size:14.5px;font-weight:700;color:{t['ink']};min-width:0;}}
.ea-ga-n small{{display:block;font-size:12.5px;font-weight:500;color:{t['muted']};margin-top:1px;}}
.ea-ga-t{{height:12px;border-radius:6px;background:{t['h1']};overflow:hidden;}}
.ea-ga-t i{{display:block;height:12px;border-radius:6px;}}
.ea-ga-v{{font-size:16px;font-weight:800;text-align:right;white-space:nowrap;}}
@media (max-width:640px){{.ea-ga-r{{grid-template-columns:minmax(0,1fr) auto;}} .ea-ga-t{{display:none;}}}}
"""
    st.markdown("#### What got away")
    st.markdown(rx.css(extra) + f'<div class="ea-rx"><div class="ea-ga-head">{head}</div>{body}</div>',
                unsafe_allow_html=True)
    return True
