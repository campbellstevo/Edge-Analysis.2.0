"""WHOOP API v2 integration — OAuth helpers + daily physiology DataFrame.

Pure-ish module: OAuth URL building, token exchange/refresh, paginated data
fetch, and a per-calendar-day DataFrame that can be joined to the trade journal
on date. Streamlit is only imported for the cached fetch wrapper.
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
    "offline",
]

_TIMEOUT = 20


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
    r.raise_for_status()
    return r.json()


def refresh_tokens(refresh_token: str, client_id: str,
                   client_secret: str) -> dict:
    """Exchange a refresh token for a fresh access/refresh token pair.

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
    r.raise_for_status()
    return r.json()


# --------------------------------------------------------------------------- #
# Data fetch
# --------------------------------------------------------------------------- #
def _get_collection(path: str, token: str, start: Optional[str] = None,
                    end: Optional[str] = None, limit: int = 25,
                    max_pages: int = 80) -> list:
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
              end: Optional[str] = None) -> Tuple[list, list, list]:
    """Return (cycles, recoveries, sleeps) for the given ISO time window."""
    cycles = _get_collection("cycle", token, start, end)
    recoveries = _get_collection("recovery", token, start, end)
    sleeps = _get_collection("activity/sleep", token, start, end)
    return cycles, recoveries, sleeps


def _local_date(iso_ts: str, tzoff: Optional[str]):
    """Calendar date of an ISO timestamp in the user's local (WHOOP) offset."""
    if not iso_ts:
        return None
    dt = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
    dt = dt.astimezone(timezone.utc)
    if tzoff and tzoff not in ("Z", ""):
        sign = 1 if tzoff[0] == "+" else -1
        try:
            hh, mm = tzoff[1:].split(":")
            dt = dt + sign * timedelta(hours=int(hh), minutes=int(mm))
        except Exception:
            pass
    return dt.date()


def build_daily_df(cycles: list, recoveries: list, sleeps: list) -> pd.DataFrame:
    """Merge cycle/recovery/sleep records into one row per calendar day.

    Columns: date, recovery, hrv_ms, rhr, day_strain, avg_hr, sleep_perf,
    sleep_hours.
    """
    rec_by_cycle = {}
    for r in recoveries:
        cid = r.get("cycle_id")
        if cid is not None and r.get("score_state") == "SCORED":
            rec_by_cycle[cid] = r.get("score") or {}

    sleep_by_cycle = {}
    for s in sleeps:
        if s.get("nap"):
            continue
        cid = s.get("cycle_id")
        if cid is not None and s.get("score_state") == "SCORED":
            sleep_by_cycle[cid] = s.get("score") or {}

    rows = []
    for c in cycles:
        day = _local_date(c.get("start"), c.get("timezone_offset"))
        if day is None:
            continue
        cscore = c.get("score") or {}
        rscore = rec_by_cycle.get(c.get("id"), {})
        sscore = sleep_by_cycle.get(c.get("id"), {})
        stage = sscore.get("stage_summary") or {}

        in_bed = stage.get("total_in_bed_time_milli")
        awake = stage.get("total_awake_time_milli") or 0
        sleep_hours = round((in_bed - awake) / 3.6e6, 2) if in_bed else None

        rows.append({
            "date": day,
            "recovery": rscore.get("recovery_score"),
            "hrv_ms": rscore.get("hrv_rmssd_milli"),
            "rhr": rscore.get("resting_heart_rate"),
            "day_strain": cscore.get("strain"),
            "avg_hr": cscore.get("average_heart_rate"),
            "sleep_perf": sscore.get("sleep_performance_percentage"),
            "sleep_hours": sleep_hours,
        })

    df = pd.DataFrame(rows)
    if not df.empty:
        df["date"] = pd.to_datetime(df["date"])
        df = (df.sort_values("date")
                .drop_duplicates("date", keep="last")
                .reset_index(drop=True))
    return df


def get_profile(token: str) -> dict:
    """Basic WHOOP profile (first name, email) — used to confirm connection."""
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
        cycles, recoveries, sleeps = fetch_raw(_token, _start, _end)
        return build_daily_df(cycles, recoveries, sleeps)

    return _run(token, start_iso, end_iso)
