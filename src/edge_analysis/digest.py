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
- every finding carries its evidence in one sentence;
- NO OUTCOME CIRCULARITY: a comparative finding may only condition on what the
  trader knew at decision time (session, model, state, rules). Tags applied
  BECAUSE a trade went wrong (Mistake, Reason of loss) prove nothing by
  comparison — "tagged trades underperform" is true by definition. Those are
  reported as a recurring specific behaviour and its total bill, never as a
  gap vs clean trades;
- NO ONE-SIDED EXIT MATHS: praising early exits inflates win rate by
  construction, and damning them ignores the reversals they dodged. Exit
  findings only count trades where price PROVABLY reached the planned target
  (MFE >= plan) and less was banked — R the market paid that wasn't collected.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

_MIN_N = 5
ALPHA = 0.05       # family-wise, across every slice tested on one journal
_B = 1000          # shuffles per slice


def _perm_p(x, mask, lower: bool) -> float:
    """One-sided permutation p-value that the slice's mean is lower (a leak)
    or higher (a strength) than everything else, from _B random relabellings
    of the same trades. Seeded, so a page never flickers between reruns."""
    x = np.asarray(pd.to_numeric(pd.Series(x), errors="coerce"), dtype=float)
    m = np.asarray(mask, dtype=bool)
    ok = ~np.isnan(x)
    x, m = x[ok], m[ok]
    n, k = len(x), int(m.sum())
    if k == 0 or k == n:
        return 1.0
    tot = x.sum()

    def stat(sum_in):
        return sum_in / k - (tot - sum_in) / (n - k)
    obs = stat(x[m].sum())
    rng = np.random.default_rng(7)
    idx = np.argsort(rng.random((_B, n)), axis=1)[:, :k]
    null = stat(x[idx].sum(axis=1))
    hits = (null <= obs) if lower else (null >= obs)
    return float((1 + hits.sum()) / (_B + 1))


def _holm_pass(ps: list, alpha: float = ALPHA) -> set:
    """Indices of the p-values Holm's step-down keeps at family-wise alpha."""
    order = sorted(range(len(ps)), key=lambda i: ps[i])
    keep, m = set(), len(ps)
    for rank, i in enumerate(order):
        if ps[i] > alpha / (m - rank):
            break
        keep.add(i)
    return keep


def _rr(df: pd.DataFrame):
    for c in ("PnL_from_RR", "Closed RR", "R Multiple"):
        if c in df.columns:
            v = pd.to_numeric(df[c], errors="coerce")
            if v.notna().any():
                return v
    return None


def _gap_finding(df, rr, mask, kind, label, note_yes, min_n=_MIN_N, need_loss=False, tested=None):
    """Generic split: trades inside `mask` vs the rest. R at stake = how much
    the offending slice underperforms the trader's own baseline, summed.
    need_loss: the slice must lose money itself. "Bench" a setup averaging
    +0.21R because the rest made +0.33R was advice to shelve a winner
    (26 Sep, his journal)."""
    mask = mask.fillna(False) if hasattr(mask, "fillna") else mask
    n_in, n_out = int(mask.sum()), int((~mask).sum())
    if n_in < min_n or n_out < min_n:
        return None
    a, b = rr[mask], rr[~mask]
    if not (a.notna().any() and b.notna().any()):
        return None
    # every slice that met the sample floor counts toward the correction,
    # whether or not it looks like a leak (5.3: honest verdicts)
    pv = _perm_p(rr, mask, lower=True)
    if tested is not None:
        tested.append(pv)
    avg_in, avg_out = float(a.mean()), float(b.mean())
    gap = avg_out - avg_in
    if gap <= 0.05 or (need_loss and avg_in >= 0):
        return None
    stake = gap * n_in
    return {
        "kind": kind, "label": label, "stake": round(stake, 1),
        "n": n_in, "p": pv, "_t": len(tested) - 1 if tested is not None else None,
        "evidence": (f"{n_in} {note_yes} averaged {avg_in:+.2f}R vs "
                     f"{avg_out:+.2f}R everywhere else — "
                     f"{stake:.1f}R at stake"),
    }


def _col_yes(df, col):
    """Yes/no per trade, <NA> where the tag wasn't answered (an untagged
    trade's unticked box is not a "no" — see untagged_checks_unknown)."""
    if col not in df.columns:
        return None
    v = df[col]
    if v.dtype == bool:
        return v
    out = v.astype(str).str.strip().str.lower().isin(["yes", "true", "__yes__", "1"]).astype("boolean")
    blank = v.isna() | v.astype(str).str.strip().str.lower().isin(["", "nan", "none", "[]"])
    out[blank] = pd.NA
    return out


def findings(df: pd.DataFrame, min_n: int = _MIN_N, gate: bool = True) -> list:
    """Ranked list of what to fix, most R at stake first. gate=False skips
    the chance test: only for a "watching, not proven" line, never a verdict."""
    out = []
    if df is None or df.empty:
        return out
    # Doctrine guard, independent of whatever filter fed this frame: leaks are
    # about execution, and forward/back tests never touched a broker. A saved
    # pre-redesign filter of "All" must not smuggle them in.
    if "Type of Trade" in df.columns:
        _tt = df["Type of Trade"].astype(str).str.lower()
        _sim = (_tt.str.contains("forward") | _tt.str.contains("back test")
                | _tt.str.contains("backtest") | _tt.str.contains("paper"))
        df = df[~_sim]
        if df.empty:
            return out
    rr = _rr(df)
    if rr is None or rr.notna().sum() < min_n * 2:
        return out
    ok = rr.notna()
    df, rr = df[ok], rr[ok]
    tested: list = []

    # 1. Sessions that bleed
    sess_col = next((c for c in ("Session Norm", "Session") if c in df.columns), None)
    if sess_col:
        vals = df[sess_col].astype(str).str.strip()
        for sess in vals.dropna().unique():
            if not sess or sess.lower() in ("nan", "none", ""):
                continue
            f = _gap_finding(df, rr, vals == sess, "session",
                            f"{sess} is below your average",
                            f"{sess} trades", min_n, need_loss=True, tested=tested)
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
                                f"Bench {m}", f"{m} entries", min_n, need_loss=True, tested=tested)
                if f:
                    out.append(f)

    # 3. Rule breaks
    rules = _col_yes(df, "Rules Followed?")
    if rules is not None:
        known = rules.notna() if hasattr(rules, "notna") else pd.Series(True, index=df.index)
        known = known.astype(bool)
        rk = rules[known].astype(bool)
        f = _gap_finding(df[known], rr[known], ~rk, "rules", "Follow your rules",
                        "rule-break trades", min_n, tested=tested)
        if f:
            out.append(f)

    # 4. The one mistake that keeps recurring — frequency and its bill.
    # (Never "tagged vs clean": tags are applied because trades went wrong,
    # so that comparison is circular. Repetition of a named behaviour isn't.)
    if "Mistake" in df.columns:
        ex = df.copy()
        ex["__rr"] = rr
        ex["__mk"] = ex["Mistake"].astype(str)
        toks = (ex.assign(__tok=ex["__mk"].str.split(r"[;,]"))
                  .explode("__tok"))
        toks["__tok"] = toks["__tok"].astype(str).str.strip().str.strip('[]"\'')
        toks = toks[~toks["__tok"].str.lower().isin(["", "nan", "none", "na"])]
        best_tok = None
        for tok, sub in toks.groupby("__tok"):
            if len(sub) < 3:
                continue
            bill = float(pd.to_numeric(sub["__rr"], errors="coerce").sum())
            if bill >= -0.5:
                continue
            cand = {"kind": "mistake", "label": f"Stop \u201c{tok}\u201d",
                    "stake": round(-bill, 1), "n": int(len(sub)),
                    "evidence": (f"you've tagged it {len(sub)} times \u2014 "
                                 f"{bill:+.1f}R while doing it. You already "
                                 "know this one; it keeps happening")}
            if best_tok is None or cand["stake"] > best_tok["stake"]:
                best_tok = cand
        if best_tok:
            out.append(best_tok)

    # 5. Exits: only trades where price PROVABLY reached the planned target
    # and less was banked. No credit or blame for early exits beyond that —
    # cutting a trade that never reached plan may have saved you.
    if "MFE (R)" in df.columns and "Planned R:R" in df.columns:
        mfe = pd.to_numeric(df["MFE (R)"], errors="coerce")
        plan = pd.to_numeric(df["Planned R:R"], errors="coerce")
        tol = 0.1
        paid = mfe.notna() & plan.notna() & (plan > 0) & (mfe >= plan - tol) \
            & (rr < plan - tol)
        n_p = int(paid.sum())
        if n_p >= 3:
            left = float((plan[paid] - rr[paid]).clip(lower=0).sum())
            if left >= 2.0:
                out.append({
                    "kind": "exits", "label": "Bank the target when it's paid",
                    "stake": round(left, 1), "n": n_p,
                    "evidence": (f"{n_p} trades reached your planned target but "
                                 f"banked less \u2014 the market paid it and "
                                 f"{left:.1f}R wasn't collected"),
                })

    # 6. Mental state (executed trades carry real pressure)
    if "Mental State" in df.columns:
        ms = df["Mental State"].astype(str).str.strip().str.lower()
        rough = ms.str.contains("stress") | ms.str.contains("fatig") \
            | ms.str.contains("impuls") | ms.str.contains("tired") \
            | ms.str.contains("rush")
        f = _gap_finding(df, rr, rough, "mental", "Don't trade tired or stressed",
                        "trades taken stressed or fatigued", min_n, tested=tested)
        if f:
            out.append(f)

    # A comparison survives only if it beats chance across everything tested
    # on this journal (permutation p, Holm at 5% family-wise). Without it the
    # list fired on 75-90% of pure-noise journals (26 Sep measure).
    keep = _holm_pass(tested)
    if gate:
        out = [f for f in out if f.get("_t") is None or f["_t"] in keep]
    for f in out:
        f["proven"] = f.get("_t") is None or f["_t"] in keep
        f.pop("_t", None)

    # One finding per kind — the worst of each — then rank by stake.
    best = {}
    for f in out:
        k = f["kind"]
        if k not in best or f["stake"] > best[k]["stake"]:
            best[k] = f
    return sorted(best.values(), key=lambda f: -f["stake"])


def _edge_finding(df, rr, mask, kind, label, note_yes, min_n=8, tested=None):
    """Positive mirror of _gap_finding: how much a decision-time bucket EARNS
    above the trader's own baseline. Strengths carry a stricter evidence bar
    than leaks (n >= 8, gap >= 0.15R/trade): praising noise creates bad habits
    faster than missing a leak does."""
    mask = mask.fillna(False) if hasattr(mask, "fillna") else mask
    n_in, n_out = int(mask.sum()), int((~mask).sum())
    if n_in < min_n or n_out < min_n:
        return None
    a, b = rr[mask], rr[~mask]
    if not (a.notna().any() and b.notna().any()):
        return None
    pv = _perm_p(rr, mask, lower=False)
    if tested is not None:
        tested.append(pv)
    avg_in, avg_out = float(a.mean()), float(b.mean())
    gap = avg_in - avg_out
    if gap < 0.15:
        return None
    edge = gap * n_in
    if edge < 2.0:
        return None
    return {
        "kind": kind, "label": label, "edge": round(edge, 1), "n": n_in,
        "p": pv, "_t": len(tested) - 1 if tested is not None else None,
        "evidence": (f"{n_in} {note_yes} averaged {avg_in:+.2f}R vs "
                     f"{avg_out:+.2f}R everywhere else"),
    }


def strengths(df: pd.DataFrame, min_n: int = 8) -> list:
    """Ranked list of what's WORKING — the decision-time buckets that earn the
    most R above the trader's own baseline. Same honesty rules as findings():
    decision-time conditioning only, minimum samples or silence, measured vs
    the trader's own baseline. Outcome-derived tags never qualify."""
    out = []
    if df is None or df.empty:
        return out
    if "Type of Trade" in df.columns:
        _tt = df["Type of Trade"].astype(str).str.lower()
        _sim = (_tt.str.contains("forward") | _tt.str.contains("back test")
                | _tt.str.contains("backtest") | _tt.str.contains("paper"))
        df = df[~_sim]
        if df.empty:
            return out
    rr = _rr(df)
    if rr is None or rr.notna().sum() < min_n * 2:
        return out
    ok = rr.notna()
    df, rr = df[ok], rr[ok]
    tested: list = []

    # 1. The session that pays
    sess_col = next((c for c in ("Session Norm", "Session") if c in df.columns), None)
    if sess_col:
        vals = df[sess_col].astype(str).str.strip()
        for sess in vals.dropna().unique():
            if not sess or sess.lower() in ("nan", "none", ""):
                continue
            f = _edge_finding(df, rr, vals == sess, "session",
                              f"Lean on {sess}", f"{sess} trades", min_n, tested=tested)
            if f:
                out.append(f)

    # 2. The entry model that earns
    if "Entry Models List" in df.columns:
        ex = df.copy()
        ex["__rr"] = rr
        ex = ex.explode("Entry Models List")
        ex["__m"] = ex["Entry Models List"].astype(str).str.strip()
        ex = ex[~ex["__m"].isin(["", "nan", "None"])]
        if not ex.empty:
            exr = pd.to_numeric(ex["__rr"], errors="coerce")
            for m in ex["__m"].unique():
                f = _edge_finding(ex, exr, ex["__m"] == m, "model",
                                  f"{m} is your edge", f"{m} entries", min_n, tested=tested)
                if f:
                    out.append(f)

    # 3. The timeframe that works (decision-time: chosen before entry)
    if "Entry Timeframe" in df.columns:
        tf = df["Entry Timeframe"].astype(str).str.strip()
        for t in tf.dropna().unique():
            if not t or t.lower() in ("nan", "none", ""):
                continue
            f = _edge_finding(df, rr, tf == t, "timeframe",
                              f"{t} entries are paying", f"{t}-entry trades",
                              min_n, tested=tested)
            if f:
                out.append(f)

    # 4. The state worth protecting
    if "Mental State" in df.columns:
        ms = df["Mental State"].astype(str).str.strip().str.lower()
        calm = ms.str.contains("clear") | ms.str.contains("calm")
        f = _edge_finding(df, rr, calm, "mental",
                          "Protect the clear-and-calm state",
                          "trades taken clear and calm", min_n, tested=tested)
        if f:
            out.append(f)

    keep = _holm_pass(tested)
    out = [f for f in out if f.get("_t") is None or f["_t"] in keep]
    for f in out:
        f.pop("_t", None)
    best = {}
    for f in out:
        k = f["kind"]
        if k not in best or f["edge"] > best[k]["edge"]:
            best[k] = f
    return sorted(best.values(), key=lambda f: -f["edge"])
