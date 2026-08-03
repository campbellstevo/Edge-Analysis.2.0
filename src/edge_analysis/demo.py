"""Demo journal: realistic simulated gold trades for the try-before-you-connect mode.

v2 — mirrors Campbell's real MT5 Trade Log schema exactly (entry models, sessions,
mental states, mistakes, news/volatility/GAP externals, OBOS, missed runners,
entry timeframes), lands roughly +5% every month, and always shows a populated
current month. Deterministic per (month, attempt): past months never reshuffle.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

_EPOCH = pd.Timestamp("2025-11-01")

# ——— his real select options ————————————————————————————————————————————————
_MODELS = ["Internal FBoS", "External FBoS",
           "External Protected Structure Continuation",
           "Internal Protected Structure Continuation",
           "Internal NC Model", "External NC Model"]
_MODEL_P = [0.26, 0.22, 0.20, 0.16, 0.09, 0.07]
_MODEL_EDGE = {"Internal FBoS": 0.08, "External FBoS": 0.05,
               "External Protected Structure Continuation": 0.03,
               "Internal Protected Structure Continuation": -0.02,
               "Internal NC Model": -0.06, "External NC Model": -0.12}
_SESS = ["London", "NY", "London/NY Overlap", "Asian"]
_SESS_P = [0.40, 0.30, 0.18, 0.12]
_SESS_EDGE = {"London": 0.07, "NY": 0.0, "London/NY Overlap": 0.10, "Asian": -0.17}
_MENTAL = ["Clear & Calm", "Fatigued & Hesitant", "Stressed & Impulsive"]
_MISTAKES = ["Cut winner early", "Revenge Traded", "No A+ setup", "Overtraded",
             "Fell in love with bias", "Failed to lock in profits", "Poor SL placement"]
_TFS = ["1M", "3M", "5M", "15M"]
_TF_P = [0.30, 0.24, 0.28, 0.18]
_NEWS = ["No News", "No News", "No News", "Post News",
         "Traded through News (Entry was over 2hs before news)",
         "Closed before news >2hs",
         "Traded through News (Entry was within 2hs  of news)"]
_GAP = ["No GAP Present", "No GAP Present", "Traded Towards GAP", "Traded Away from GAP"]
_LOSS_NOTES = [
    "Wrong bias — MTF structure was against me and I forced the long anyway",
    "Misread the structure, entered into opposing weak highs",
    "Should have set BE after the first push, gave the whole thing back",
    "Held through the pullback without moving stop — management error",
    "Entered too early before the sweep completed",
    "Late entry chasing the move after it had already run",
    "News candle took me out — traded straight into the release window",
    "Volatility spike on CPI, spread blew out through my stop",
    "Moved my stop wider mid-trade, classic mistake",
    "Bias was right but timing was off, stopped out before it went",
    "Counter-trend against the ETF trend, low quality setup",
]

_WIN_RRS = [1.5, 1.8, 2.0, 2.3, 2.8, 4.0]
_WIN_P = [.18, .24, .24, .18, .11, .05]


def _month_days(ms: pd.Timestamp, today: pd.Timestamp):
    """Business days this month should show: full past months entirely; the
    current month at least ~3 weeks in, so the first chart is never empty."""
    me = ms + pd.offsets.MonthEnd(0)
    if me <= today:
        return pd.bdate_range(ms, me)
    horizon = max(today, list(pd.bdate_range(ms, me))[:14][-1] if len(pd.bdate_range(ms, me)) >= 14 else me)
    return pd.bdate_range(ms, min(horizon, me))


def _gen_month(ms: pd.Timestamp, days, seed: int, attempt: int, balance: float):
    rng = np.random.default_rng(seed * 1000003 + ms.year * 100 + ms.month * 7 + attempt * 31)
    rows = []
    for d in days:
        n = int(rng.choice([0, 1, 1, 1, 2, 2], p=[.24, .26, .18, .10, .14, .08]))
        for _ in range(n):
            sess = str(rng.choice(_SESS, p=_SESS_P))
            model = str(rng.choice(_MODELS, p=_MODEL_P))
            second = str(rng.choice([m for m in _MODELS if m != model]))
            multi = rng.random() < 0.18
            aplus = rng.random() < 0.25
            rules = rng.random() > 0.10
            conviction = int(np.clip(round(rng.normal(4.1 if aplus else 3.0, 0.7)), 1, 5))
            if aplus and rules:
                mental = str(rng.choice(_MENTAL, p=[.78, .14, .08]))
            else:
                mental = str(rng.choice(_MENTAL, p=[.52, .26, .22]))
            wr = 0.35 + _SESS_EDGE[sess] + _MODEL_EDGE[model] \
                 + (0.07 if aplus else -0.02) + (0.0 if rules else -0.13) \
                 + (0.03 if mental == "Clear & Calm" else -0.05)
            u = rng.random()
            planned = float(rng.choice([2.0, 2.5, 3.0], p=[.45, .35, .20]))
            early_exit = False
            if u < wr:
                early_exit = rng.random() < 0.13
                if early_exit:
                    # closed early; price then ran to the full target without them
                    rr = float(np.round(max(0.3, planned - abs(rng.normal(0.9, 0.35))), 2))
                    mfe = float(np.round(planned + abs(rng.normal(0.3, 0.25)), 2))
                else:
                    rr = float(np.round(rng.choice(_WIN_RRS, p=_WIN_P) + rng.normal(0, 0.12), 2))
                    mfe = rr + abs(rng.normal(0.25, 0.2))
                result = "Win"
            elif u < wr + 0.18:
                rr = float(np.round(rng.normal(0.0, 0.06), 2))
                mfe = abs(rng.normal(0.9, 0.4))
                result = "BE"
            else:
                rr = float(np.round(-1.0 + rng.normal(0, 0.06), 2))
                mfe = abs(rng.normal(0.45, 0.35))
                result = "Loss"
            is_loss = rr < -0.15
            missed = "Yes" if early_exit else ("No" if result == "Win" else "NA")
            hour = int(rng.choice([17, 18, 19, 20, 21, 22, 23, 0, 1, 2, 9, 11],
                                  p=[.09, .10, .11, .10, .10, .14, .12, .08, .06, .04, .03, .03]))
            risk_usd = balance * 0.01
            pnl = round(rr * risk_usd, 2)
            balance = round(balance + pnl, 2)
            mistake = ""
            if is_loss and not rules:
                mistake = str(rng.choice(_MISTAKES))
            elif is_loss and rng.random() < 0.25:
                mistake = str(rng.choice(_MISTAKES))
            elif early_exit and rng.random() < 0.5:
                mistake = "Cut winner early"
            rows.append({
                "Date": d + pd.Timedelta(hours=hour, minutes=int(rng.integers(0, 59))),
                "Instrument": "Gold", "Pair": "XAUUSD", "Symbol": "XAUUSD.r",
                "Session": sess, "Session Norm": sess,
                "Direction": str(rng.choice(["Long", "Short"], p=[.56, .44])),
                "Entry Model": model,
                "Entry Models List": [model, second] if multi else [model],
                "Multi Entry Model Setup": "Yes" if multi else "No",
                "Entry Timeframe": str(rng.choice(_TFS, p=_TF_P)),
                "DIV?": "Yes" if rng.random() < 0.42 else "No",
                "Sweep?": "Yes" if rng.random() < 0.5 else "No",
                "Oversold or Overbought?": "Yes" if rng.random() < 0.32 else "No",
                "Conditions ETF": '["Trending"]' if rng.random() < 0.6 else '["Ranging"]',
                "Conditions MTF": '["Trending"]' if rng.random() < 0.55 else '["Ranging"]',
                "Conditions HTF": '["Trending"]' if rng.random() < 0.5 else '["Ranging"]',
                "Volatility": str(rng.choice(["2/5", "3/5", "4/5", "5/5"], p=[.2, .4, .3, .1])),
                "News Aspect": str(rng.choice(_NEWS)),
                "GAP Alignment": str(rng.choice(_GAP)),
                "Result": result,
                "Outcome": "Win" if rr > 0.15 else ("Loss" if is_loss else "BE"),
                "Closed RR": rr, "Closed RR Num": rr, "PnL_from_RR": rr,
                "Planned R:R": planned,
                "MFE (R)": round(mfe, 2),
                "MAE (R)": round(-abs(rng.normal(0.55, 0.25)) if not is_loss else
                                 -abs(rng.normal(0.97, 0.05)), 2),
                "PnL": pnl, "PnL (USD)": pnl,
                "Commission": round(-abs(rng.normal(0.55, 0.15)), 2),
                "Lot Size": round(float(rng.choice([0.05, 0.08, 0.1, 0.12])), 2),
                "Balance": balance,
                "Type of Trade": "Live",
                "Hit Full TP Without You": missed,
                "A+ Setup?": "Yes" if aplus else "No",
                "Rules Followed?": "Yes" if rules else "No",
                "Conviction (1-5)": str(conviction),
                "Mental State": mental,
                "Mistake": mistake,
                "Reason of loss": str(rng.choice(_LOSS_NOTES)) if (is_loss and rng.random() < 0.7) else "",
                "Hour (Melb)": hour,
                "2h session window": "Yes" if rng.random() < 0.05 else "",
            })
    return rows, balance


def demo_df(today: pd.Timestamp | None = None, seed: int = 9) -> pd.DataFrame:
    today = (today or pd.Timestamp.now()).normalize()
    all_rows = []
    balance = 10000.0
    ms = _EPOCH
    while ms <= today:
        days = _month_days(ms, today)
        me = ms + pd.offsets.MonthEnd(0)
        full = me <= today
        frac = len(days) / max(1, len(pd.bdate_range(ms, me)))
        lo, hi = (3.6, 6.2) if full else (max(0.5, 3.2 * frac - 1.0), 6.8 * frac + 2.0)
        chosen = None
        for attempt in range(60):
            rows, end_bal = _gen_month(ms, days, seed, attempt, balance)
            s = sum(r["Closed RR"] for r in rows)
            if lo <= s <= hi:
                chosen = (rows, end_bal)
                break
            if chosen is None or abs(s - (lo + hi) / 2) < abs(
                    sum(r["Closed RR"] for r in chosen[0]) - (lo + hi) / 2):
                chosen = (rows, end_bal)
        rows, balance = chosen
        all_rows.extend(rows)
        ms = (ms + pd.offsets.MonthBegin(1)).normalize()
    df = pd.DataFrame(all_rows)
    df["DayName"] = pd.to_datetime(df["Date"]).dt.day_name()
    return df
