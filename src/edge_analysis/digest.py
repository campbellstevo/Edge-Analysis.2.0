"""The "what needs work" engine.

Every dashboard on the market shows a trader everything and leaves them to find
the problem. This module does the finding: it scans the executed trades, prices
each weakness in R AT STAKE — the R you'd plausibly have kept by fixing just
that habit over this data — and returns findings ranked by that number.

Honesty rules:
- a finding needs a minimum sample (default 5 in the offending bucket) or it
  doesn't exist;
- R at stake is measured against the trader's OWN baseline (their average trade
  everywhere else), never against zero, so a bad patch in a good system isn't
  overstated;
- every finding carries its evidence in one sentence.
"""
from __future__ import annotations

import pandas as pd

_MIN_N = 5


def _rr(df: pd.DataFrame):
    for c in ("PnL_from_RR", "Closed RR", "R Multiple"):
        if c in df.columns:
            v = pd.to_numeric(df[c], errors="coerce")
            if v.notna().any():
                return v
    return None


def _gap_finding(df, rr, mask, kind, label, note_yes, min_n=_MIN_N):
    """Generic split: trades inside `mask` vs the rest. R at stake = how much
    the offending slice underperforms the trader's own baseline, summed."""
    mask = mask.fillna(False) if hasattr(mask, "fillna") else mask
    n_in, n_out = int(mask.sum()), int((~mask).sum())
    if n_in < min_n or n_out < min_n:
        return None
    a, b = rr[mask], rr[~mask]
    if not (a.notna().any() and b.notna().any()):
        return None
    avg_in, avg_out = float(a.mean()), float(b.mean())
    gap = avg_out - avg_in
    if gap <= 0.05:
        return None
    stake = gap * n_in
    return {
        "kind": kind, "label": label, "stake": round(stake, 1),
        "n": n_in,
        "evidence": (f"{n_in} {note_yes} averaged {avg_in:+.2f}R vs "
                     f"{avg_out:+.2f}R everywhere else — "
                     f"{stake:.1f}R at stake"),
    }


def _col_yes(df, col):
    if col not in df.columns:
        return None
    v = df[col]
    if v.dtype == bool:
        return v
    return v.astype(str).str.strip().str.lower().isin(
        ["yes", "true", "__yes__", "1"])


def findings(df: pd.DataFrame, min_n: int = _MIN_N) -> list:
    """Ranked list of what to fix, most R at stake first."""
    out = []
    if df is None or df.empty:
        return out
    rr = _rr(df)
    if rr is None or rr.notna().sum() < min_n * 2:
        return out
    ok = rr.notna()
    df, rr = df[ok], rr[ok]

    # 1. Sessions that bleed
    sess_col = next((c for c in ("Session Norm", "Session") if c in df.columns), None)
    if sess_col:
        vals = df[sess_col].astype(str).str.strip()
        for sess in vals.dropna().unique():
            if not sess or sess.lower() in ("nan", "none", ""):
                continue
            f = _gap_finding(df, rr, vals == sess, "session",
                            f"Cut or fix {sess}",
                            f"{sess} trades", min_n)
            if f:
                out.append(f)

    # 2. Entry models that cost
    if "Entry Models List" in df.columns:
        ex = df.copy()
        ex["__rr"] = rr
        ex = ex.explode("Entry Models List")
        ex["__m"] = ex["Entry Models List"].astype(str).str.strip()
        ex = ex[~ex["__m"].isin(["", "nan", "None"])]
        if not ex.empty:
            exr = pd.to_numeric(ex["__rr"], errors="coerce")
            for m in ex["__m"].unique():
                f = _gap_finding(ex, exr, ex["__m"] == m, "model",
                                f"Bench {m}", f"{m} entries", min_n)
                if f:
                    out.append(f)

    # 3. Rule breaks
    rules = _col_yes(df, "Rules Followed?")
    if rules is not None:
        f = _gap_finding(df, rr, ~rules, "rules", "Follow your rules",
                        "rule-break trades", min_n)
        if f:
            out.append(f)

    # 4. Repeated mistakes (already-tagged cost)
    if "Mistake" in df.columns:
        mk = df["Mistake"].astype(str).str.strip()
        tagged = ~mk.str.lower().isin(["", "nan", "none", "na"])
        f = _gap_finding(df, rr, tagged, "mistake", "Kill the tagged mistakes",
                        "trades with a tagged mistake", min_n)
        if f:
            out.append(f)

    # 5. Give-back: winners that came home early
    if "MFE (R)" in df.columns:
        mfe = pd.to_numeric(df["MFE (R)"], errors="coerce")
        gb = (mfe - rr).clip(lower=0)
        big = gb[(mfe >= 1.5) & (rr < mfe * 0.5)]
        if len(big) >= min_n and float(big.sum()) >= 2.0:
            out.append({
                "kind": "giveback", "label": "Hold winners to the plan",
                "stake": round(float(big.sum()), 1), "n": int(len(big)),
                "evidence": (f"{len(big)} trades ran {float(mfe[big.index].mean()):.1f}R "
                             f"in your favour but closed under half of it — "
                             f"{float(big.sum()):.1f}R at stake"),
            })

    # 6. Mental state (executed trades carry real pressure)
    if "Mental State" in df.columns:
        ms = df["Mental State"].astype(str).str.strip().str.lower()
        rough = ms.str.contains("stress") | ms.str.contains("fatig") \
            | ms.str.contains("impuls") | ms.str.contains("tired") \
            | ms.str.contains("rush")
        f = _gap_finding(df, rr, rough, "mental", "Don't trade tired or stressed",
                        "trades taken stressed or fatigued", min_n)
        if f:
            out.append(f)

    # One finding per kind — the worst of each — then rank by stake.
    best = {}
    for f in out:
        k = f["kind"]
        if k not in best or f["stake"] > best[k]["stake"]:
            best[k] = f
    return sorted(best.values(), key=lambda f: -f["stake"])
