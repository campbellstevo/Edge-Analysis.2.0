"""WHOOP API v2 integration — OAuth helpers + full daily physiology DataFrame.

Pulls every daily-resolution signal that could plausibly affect trading:
recovery (score/HRV/RHR/SpO2/skin-temp), cycle (strain/energy/heart rate),
sleep (performance/efficiency/consistency/stages/debt/need/respiration) and
workouts, plus prior-day lag features. Streamlit is only imported for the
cached fetch wrapper.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple
from urllib.parse import urlencode

import pandas as pd
import requests

AUTH_URL = "https://api.prod.whoop.com/oauth/oauth2/auth"
TOKEN_URL = "https://api.prod.whoop.com/oauth/oauth2/token"
API_BASE = "https://api.prod.whoop.com/developer/v2"

# `offline` is required to receive a refresh token.
SCOPES = [
    "read:recovery",
    "read:sleep",
    "read:cycles",
    "read:workout",
    "read:profile",
    "read:body_measurement",
    "offline",
]

_TIMEOUT = 20
_MS_PER_H = 3.6e6

# Human labels for every daily metric we expose (used by the UI).
METRIC_LABELS = {
    "recovery": "Recovery %",
    "hrv_ms": "HRV (ms)",
    "rhr": "Resting HR",
    "spo2": "Blood oxygen %",
    "skin_temp": "Skin temp (°C)",
    "day_strain": "Day strain",
    "avg_hr": "Avg HR",
    "max_hr": "Max HR",
    "energy_kj": "Energy (kJ)",
    "sleep_perf": "Sleep performance %",
    "sleep_efficiency": "Sleep efficiency %",
    "sleep_consistency": "Sleep consistency %",
    "resp_rate": "Respiratory rate",
    "sleep_hours": "Sleep (h)",
    "rem_hours": "REM sleep (h)",
    "deep_hours": "Deep sleep (h)",
    "light_hours": "Light sleep (h)",
    "awake_hours": "Awake in bed (h)",
    "disturbances": "Sleep disturbances",
    "sleep_cycles": "Sleep cycles",
    "sleep_need_hours": "Sleep needed (h)",
    "sleep_debt_hours": "Sleep debt (h)",
    "sleep_vs_need": "Sleep vs need %",
    "workout_count": "Workouts (count)",
    "workout_strain": "Workout strain (max)",
    "recovery_prev": "Recovery % (prev day)",
    "day_strain_prev": "Day strain (prev day)",
    "sleep_hours_prev": "Sleep h (prev day)",
    "sleep_vs_need_prev": "Sleep vs need % (prev day)",
}

# Metrics carried into the "what moves your edge" correlation ranking.
DRIVER_METRICS = [
    "recovery", "hrv_ms", "rhr", "spo2", "skin_temp",
    "day_strain", "energy_kj", "max_hr",
    "sleep_perf", "sleep_efficiency", "sleep_consistency", "resp_rate",
    "sleep_hours", "rem_hours", "deep_hours", "light_hours",
    "awake_hours", "disturbances", "sleep_need_hours", "sleep_debt_hours",
    "sleep_vs_need", "workout_strain",
    "recovery_prev", "day_strain_prev", "sleep_hours_prev", "sleep_vs_need_prev",
]


# --------------------------------------------------------------------------- #
# OAuth
# --------------------------------------------------------------------------- #
def authorize_url(client_id: str, redirect_uri: str, state: str,
                  scopes=None) -> str:
    """Build the WHOOP consent URL. `state` must be >= 8 chars."""
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": " ".join(scopes or SCOPES),
        "state": state,
    }
    return AUTH_URL + "?" + urlencode(params)


def exchange_code(code: str, client_id: str, client_secret: str,
                  redirect_uri: str) -> dict:
    """Exchange an authorization code for tokens."""
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
    }
    r = requests.post(TOKEN_URL, data=data, timeout=_TIMEOUT)
    if not r.ok:
        raise requests.exceptions.HTTPError(
            f"{r.status_code}: {r.text[:300]}", response=r)
    return r.json()


def refresh_tokens(refresh_token: str, client_id: str,
                   client_secret: str) -> dict:
    """Exchange a refresh token for a fresh access/refresh pair.

    WHOOP rotates the refresh token on every use — callers MUST persist the
    `refresh_token` from the response.
    """
    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": client_id,
        "client_secret": client_secret,
        "scope": "offline",
    }
    r = requests.post(TOKEN_URL, data=data, timeout=_TIMEOUT)
    if not r.ok:
        raise requests.exceptions.HTTPError(
            f"{r.status_code}: {r.text[:300]}", response=r)
    return r.json()


# --------------------------------------------------------------------------- #
# Data fetch
# --------------------------------------------------------------------------- #
def _get_collection(path: str, token: str, start: Optional[str] = None,
                    end: Optional[str] = None, limit: int = 25,
                    max_pages: int = 100) -> list:
    """Fetch every record from a paginated v2 collection endpoint."""
    out: list = []
    next_token = None
    headers = {"Authorization": f"Bearer {token}"}
    for _ in range(max_pages):
        params = {"limit": limit}
        if start:
            params["start"] = start
        if end:
            params["end"] = end
        if next_token:
            params["nextToken"] = next_token
        r = requests.get(f"{API_BASE}/{path}", headers=headers,
                         params=params, timeout=_TIMEOUT)
        r.raise_for_status()
        j = r.json()
        out.extend(j.get("records", []) or [])
        next_token = j.get("next_token")
        if not next_token:
            break
    return out


def fetch_raw(token: str, start: Optional[str] = None,
              end: Optional[str] = None) -> dict:
    """Return {cycles, recoveries, sleeps, workouts} for the ISO time window."""
    return {
        "cycles": _get_collection("cycle", token, start, end),
        "recoveries": _get_collection("recovery", token, start, end),
        "sleeps": _get_collection("activity/sleep", token, start, end),
        "workouts": _get_collection("activity/workout", token, start, end),
    }


def _local_date(iso_ts: str, tzoff: Optional[str]):
    """Calendar date of an ISO timestamp in the user's local (WHOOP) offset."""
    if not iso_ts:
        return None
    dt = datetime.fromisoformat(iso_ts.replace("Z", "+00:00")).astimezone(timezone.utc)
    if tzoff and tzoff not in ("Z", ""):
        sign = 1 if tzoff[0] == "+" else -1
        try:
            hh, mm = tzoff[1:].split(":")
            dt = dt + sign * timedelta(hours=int(hh), minutes=int(mm))
        except Exception:
            pass
    return dt.date()


def _h(milli):
    return round(milli / _MS_PER_H, 2) if milli else None


def build_daily_df(cycles: list, recoveries: list, sleeps: list,
                   workouts: Optional[list] = None) -> pd.DataFrame:
    """Merge cycle/recovery/sleep/workout records into one row per day."""
    workouts = workouts or []

    rec_by_cycle = {r.get("cycle_id"): (r.get("score") or {})
                    for r in recoveries
                    if r.get("cycle_id") is not None and r.get("score_state") == "SCORED"}
    sleep_by_cycle = {}
    for s in sleeps:
        if s.get("nap"):
            continue
        cid = s.get("cycle_id")
        if cid is not None and s.get("score_state") == "SCORED":
            sleep_by_cycle[cid] = s.get("score") or {}

    # Aggregate workouts onto their local calendar day.
    wk_by_day: dict = {}
    for w in workouts:
        day = _local_date(w.get("start"), w.get("timezone_offset"))
        if day is None:
            continue
        ws = w.get("score") or {}
        agg = wk_by_day.setdefault(day, {"count": 0, "strain": 0.0, "kj": 0.0})
        agg["count"] += 1
        agg["strain"] = max(agg["strain"], float(ws.get("strain") or 0.0))
        agg["kj"] += float(ws.get("kilojoule") or 0.0)

    rows = []
    for c in cycles:
        day = _local_date(c.get("start"), c.get("timezone_offset"))
        if day is None:
            continue
        cs = c.get("score") or {}
        rs = rec_by_cycle.get(c.get("id"), {})
        ss = sleep_by_cycle.get(c.get("id"), {})
        stage = ss.get("stage_summary") or {}
        need = ss.get("sleep_needed") or {}

        in_bed = stage.get("total_in_bed_time_milli")
        awake = stage.get("total_awake_time_milli") or 0
        asleep_ms = (in_bed - awake) if in_bed else None
        need_ms = None
        if need:
            need_ms = ((need.get("baseline_milli") or 0)
                       + (need.get("need_from_sleep_debt_milli") or 0)
                       + (need.get("need_from_recent_strain_milli") or 0)
                       + (need.get("need_from_recent_nap_milli") or 0))
        sleep_vs_need = (round(100.0 * asleep_ms / need_ms, 1)
                         if asleep_ms and need_ms else None)
        wk = wk_by_day.get(day, {})

        rows.append({
            "date": day,
            # recovery
            "recovery": rs.get("recovery_score"),
            "hrv_ms": rs.get("hrv_rmssd_milli"),
            "rhr": rs.get("resting_heart_rate"),
            "spo2": rs.get("spo2_percentage"),
            "skin_temp": rs.get("skin_temp_celsius"),
            # cycle
            "day_strain": cs.get("strain"),
            "avg_hr": cs.get("average_heart_rate"),
            "max_hr": cs.get("max_heart_rate"),
            "energy_kj": cs.get("kilojoule"),
            # sleep
            "sleep_perf": ss.get("sleep_performance_percentage"),
            "sleep_efficiency": ss.get("sleep_efficiency_percentage"),
            "sleep_consistency": ss.get("sleep_consistency_percentage"),
            "resp_rate": ss.get("respiratory_rate"),
            "sleep_hours": _h(asleep_ms),
            "rem_hours": _h(stage.get("total_rem_sleep_time_milli")),
            "deep_hours": _h(stage.get("total_slow_wave_sleep_time_milli")),
            "light_hours": _h(stage.get("total_light_sleep_time_milli")),
            "awake_hours": _h(awake),
            "disturbances": stage.get("disturbance_count"),
            "sleep_cycles": stage.get("sleep_cycle_count"),
            "sleep_need_hours": _h(need_ms),
            "sleep_debt_hours": _h(need.get("need_from_sleep_debt_milli")),
            "sleep_vs_need": sleep_vs_need,
            # workouts
            "workout_count": wk.get("count", 0),
            "workout_strain": wk.get("strain") or None,
        })

    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["date"] = pd.to_datetime(df["date"])
    df = (df.sort_values("date")
            .drop_duplicates("date", keep="last")
            .reset_index(drop=True))
    return add_lag_features(df)


def add_lag_features(df: pd.DataFrame) -> pd.DataFrame:
    """Add prior-day carry-over signals (yesterday's load affects today)."""
    if df.empty:
        return df
    d = df.sort_values("date").reset_index(drop=True).copy()
    # Only treat as a real "previous day" when the gap is exactly one day.
    prev_gap = d["date"].diff().dt.days
    for src, dst in [("recovery", "recovery_prev"),
                     ("day_strain", "day_strain_prev"),
                     ("sleep_hours", "sleep_hours_prev"),
                     ("sleep_vs_need", "sleep_vs_need_prev")]:
        shifted = d[src].shift(1)
        d[dst] = shifted.where(prev_gap == 1)
    return d


def get_profile(token: str) -> dict:
    """Basic WHOOP profile — used to confirm connection."""
    try:
        r = requests.get(f"{API_BASE}/user/profile/basic",
                         headers={"Authorization": f"Bearer {token}"},
                         timeout=_TIMEOUT)
        r.raise_for_status()
        return r.json()
    except Exception:
        return {}


# --------------------------------------------------------------------------- #
# Cached wrapper (Streamlit)
# --------------------------------------------------------------------------- #
def cached_daily_df(token: str, start_iso: str, end_iso: str) -> pd.DataFrame:
    """Fetch + build the daily DataFrame, cached for 30 min by (token, window)."""
    import streamlit as st

    @st.cache_data(ttl=1800, show_spinner=False)
    def _run(_token: str, _start: str, _end: str) -> pd.DataFrame:
        raw = fetch_raw(_token, _start, _end)
        return build_daily_df(raw["cycles"], raw["recoveries"],
                              raw["sleeps"], raw["workouts"])

    return _run(token, start_iso, end_iso)
