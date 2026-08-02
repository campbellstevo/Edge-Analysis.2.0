"""Demo journal: realistic simulated gold trades for the try-before-you-connect mode.

Deterministic (seeded), so every visitor sees the same coherent story:
a profitable-but-human 9 months — London is the edge, Asia bleeds, A+ setups
outperform, rule breaks cost money, one losing news month, give-back visible.
Compounds 1% risk on a $10,000 start so dollars, balance and % all reconcile.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

_SESS_P = {"London": 0.45, "New York": 0.40, "Asia": 0.15}
# per-session expectancy shift (the story: London pays, Asia doesn't)
_SESS_EDGE = {"London": 0.10, "New York": 0.02, "Asia": -0.20}
_MODELS = ["OB", "FVG", "Sweep Reversal", "BOS Retest"]
_MODEL_P = [0.38, 0.28, 0.22, 0.12]
_MODEL_EDGE = {"OB": 0.09, "FVG": 0.01, "Sweep Reversal": 0.03, "BOS Retest": -0.14}
# month drift: slow start, one news blowup, strong recent run
_MONTH_DRIFT = [-0.16, 0.02, -0.04, -0.26, 0.08, 0.06, -0.02, 0.10, 0.04]

_LOSS_NOTES = [
    "Wrong bias — MTF structure was against me and I forced the long anyway",
    "Misread the structure, entered into opposing weak highs",
    "Should have set BE after the first push, gave the whole thing back",
    "Held through the pullback without moving stop — management error",
    "Entered too early before the sweep completed",
    "Late entry chasing the move after it had already run",
    "News candle took me out — traded straight into the release window",
    "Volatility spike on CPI, spread blew out through my stop",
    "Fat-fingered the lot size and panicked out — execution error",
    "Moved my stop wider mid-trade, classic mistake",
    "Bias was right but timing was off, stopped before it went",
    "Counter-trend against the ETF trend, low quality setup",
]
_MISTAKES = ["", "", "", "", "", "Moved stop", "Early entry", "Chased", "Oversized", "No BE"]


def demo_df(today: pd.Timestamp | None = None, seed: int = 9) -> pd.DataFrame:
    today = (today or pd.Timestamp.now()).normalize()
    start = pd.Timestamp("2025-11-01")  # fixed epoch: history grows, never reshuffles
    days = pd.bdate_range(start, today)  # gold: weekday sessions only

    rows = []
    balance = 10000.0
    for d in days:
        # one rng per day: as real time passes new days append while every
        # past day's trades stay exactly the same — the demo never reshuffles
        rng = np.random.default_rng(seed * 100003 + d.toordinal())
        n = int(rng.choice([0, 0, 1, 1, 1, 2, 2, 3], p=[.18, .12, .22, .18, .10, .12, .05, .03]))
        _mi = (d.year - start.year) * 12 + d.month - start.month
        month_ix = _mi if _mi < len(_MONTH_DRIFT) else None
        for _ in range(n):
            sess = str(rng.choice(list(_SESS_P), p=list(_SESS_P.values())))
            model = str(rng.choice(_MODELS, p=_MODEL_P))
            aplus = bool(rng.random() < 0.25)
            rules = bool(rng.random() > 0.12)
            conviction = int(np.clip(rng.normal(3.4 if aplus else 2.9, 0.9), 1, 5))
            # win prob from the story pieces
            _drift = (_MONTH_DRIFT[month_ix] if month_ix is not None
                      else [0.06, -0.05, 0.09, 0.0][_mi % 4])  # mild cycle beyond the scripted 9 months
            wr = 0.27 + _SESS_EDGE[sess] + _MODEL_EDGE[model] \
                 + (0.08 if aplus else -0.02) + (0.0 if rules else -0.14) \
                 + _drift
            u = rng.random()
            if u < wr:                                   # win
                rr = float(np.round(rng.choice([1.5, 1.8, 2.0, 2.3, 2.8, 4.0],
                                               p=[.18, .24, .24, .18, .11, .05])
                                    + rng.normal(0, 0.12), 2))
                mfe = rr + abs(rng.normal(0.25, 0.2))
                result = "Win"
            elif u < wr + 0.20:                          # break-even
                rr = float(np.round(rng.normal(0.0, 0.06), 2))
                mfe = abs(rng.normal(0.9, 0.4))
                result = "BE"
            else:                                        # loss
                rr = float(np.round(-1.0 + rng.normal(0, 0.07), 2))
                mfe = abs(rng.normal(0.45, 0.35))
                result = "Bad Beat" if mfe > 1.5 else "Loss"
            hour = int(rng.choice([17, 18, 19, 20, 21, 22, 23, 0, 1, 2, 9, 11],
                                  p=[.09, .10, .11, .10, .10, .14, .12, .08, .06, .04, .03, .03]))
            risk_usd = balance * 0.01
            pnl = round(rr * risk_usd, 2)
            balance = round(balance + pnl, 2)
            is_loss = rr < -0.15
            rows.append({
                "Date": d + pd.Timedelta(hours=hour, minutes=int(rng.integers(0, 59))),
                "Instrument": "Gold", "Pair": "XAUUSD",
                "Session": sess, "Session Norm": sess,
                "Direction": str(rng.choice(["Long", "Short"], p=[.56, .44])),
                "Entry Model": model, "Entry Models List": [model],
                "Multi Entry Model Setup": "Yes" if rng.random() < 0.2 else "No",
                "DIV?": "Yes" if rng.random() < 0.42 else "No",
                "Sweep?": "Yes" if rng.random() < 0.5 else "No",
                "Conditions ETF": '["Trending"]' if rng.random() < 0.6 else '["Ranging"]',
                "Conditions MTF": '["Trending"]' if rng.random() < 0.55 else '["Ranging"]',
                "Result": result,
                "Outcome": "Win" if rr > 0.15 else ("Loss" if is_loss else "BE"),
                "Closed RR": rr, "Closed RR Num": rr, "PnL_from_RR": rr,
                "Targeted RR": str(rng.choice(["2-3", "2.5", "3+", "2"])),
                "Planned R:R": float(rng.choice([2.0, 2.5, 3.0])),
                "MFE (R)": round(mfe, 2),
                "MAE (R)": round(-abs(rng.normal(0.55, 0.25)) if not is_loss else
                                 -abs(rng.normal(0.97, 0.05)), 2),
                "PnL": pnl, "PnL (USD)": pnl,
                "Commission": round(-abs(rng.normal(0.55, 0.15)), 2),
                "Lot Size": round(float(rng.choice([0.05, 0.08, 0.1, 0.12])), 2),
                "Balance": balance,
                "A+ Setup?": "Yes" if aplus else "No",
                "Rules Followed?": "Yes" if rules else "No",
                "Conviction (1-5)": str(conviction),
                "Mental State": str(rng.choice(
                    ["Clear", "Focused", "Calm", "Tired", "Frustrated", "Rushed"],
                    p=[.30, .22, .18, .12, .10, .08])) if rng.random() < 0.85 else "",
                "Mistake": str(rng.choice(_MISTAKES)) if is_loss else "",
                "Reason of loss": str(rng.choice(_LOSS_NOTES)) if (is_loss and rng.random() < 0.7) else "",
                "Hour (Melb)": hour,
                "2h session window": "Yes" if rng.random() < 0.05 else "",
            })
    df = pd.DataFrame(rows)
    df["DayName"] = pd.to_datetime(df["Date"]).dt.day_name()
    return df
