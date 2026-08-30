from __future__ import annotations
import sys
from pathlib import Path

# Add src directory to Python path FIRST (before any edge_analysis imports)
_ROOT = Path(__file__).resolve().parent
_SRC = _ROOT / "src"
if _SRC.exists():
    sys.path.insert(0, str(_SRC))

import os
import json
import base64
import secrets
import requests
import hashlib
import time
import re
from urllib.parse import urlencode, urlparse
from typing import Optional, Union, Tuple
from datetime import date as DateType
import pandas as pd
import streamlit as st

# Import theme functions up front for consolidated styling
from edge_analysis.ui.theme import inject_theme, inject_header, inject_header_bar, inject_dark_overlay, setup_favicon, get_chart_styler

# ------------------------------- Constants ------------------------------------
BRAND_PURPLE = "#4800ff"


def _init_sentry() -> None:
    """Crash reporting, active only when a SENTRY_DSN secret exists."""
    try:
        import os as _os
        _dsn = None
        try:
            _dsn = st.secrets.get("SENTRY_DSN")
        except Exception:
            _dsn = None
        _dsn = _dsn or _os.environ.get("SENTRY_DSN")
        if _dsn and not _os.environ.get("_EA_SENTRY_ON"):
            import sentry_sdk
            sentry_sdk.init(dsn=str(_dsn), traces_sample_rate=0.0,
                            send_default_pii=False)
            _os.environ["_EA_SENTRY_ON"] = "1"
    except Exception:
        pass


_init_sentry()


class SessionKeys:
    """Session state key constants."""
    OAUTH_TOKEN = "override_NOTION_TOKEN"
    USER_TOKEN = "user_notion_token"
    USER_ID = "user_id"
    DB_ID = "override_DATABASE_ID"
    NAV_PAGE = "nav_page"
    NAV_TARGET = "nav_page_target"
    LAYOUT = "layout_choice"
    OAUTH_PENDING = "oauth_pending"
    OAUTH_CALLBACK = "oauth_callback_code"


class PageNames:
    DASHBOARD = "Dashboard"
    CONNECT = "Journals"


class APIConstants:
    NOTION_API_VERSION = "2022-06-28"
    REQUEST_TIMEOUT = 15
    OAUTH_TIMEOUT = 30
    OAUTH_STATE_LENGTH = 24
    PKCE_VERIFIER_LENGTH = 64


# --------------------------- Page config / assets -----------------------------
def _find_assets_dir() -> Path:
    """Locate the assets directory by checking multiple candidate paths."""
    candidates = [
        _ROOT / "assets",
        (_ROOT.parent / "assets"),
        Path("assets").resolve(),
    ]
    for c in candidates:
        try:
            if c.exists():
                return c
        except Exception:
            pass
    return _ROOT / "assets"


ASSETS_DIR = _find_assets_dir()
FAVICON = ASSETS_DIR / "edge_favicon.png"
PAGE_ICON = str(FAVICON) if FAVICON.exists() else None

st.set_page_config(
    page_title="Edge Analysis",
    page_icon=PAGE_ICON,
    layout="wide",
    initial_sidebar_state="expanded",
)

# Consolidated theme injection; apply once at startup
inject_theme()
setup_favicon()


# --- Streamlit version compatibility shim -------------------------------------
def _st_rerun():
    """Trigger a rerun across different Streamlit versions."""
    try:
        st.rerun()
    except Exception:
        try:
            st.experimental_rerun()  # type: ignore[attr-defined]
        except Exception:
            pass


# ------------------------ Secrets / runtime helpers ---------------------------
def _get_query_param(name: str) -> Optional[str]:
    """Get a single query parameter value."""
    try:
        val = st.query_params.get(name)
        if isinstance(val, list):
            return val[0] if val else None
        return val
    except Exception:
        try:
            qp = st.experimental_get_query_params()
            if name in qp and qp[name]:
                return qp[name][0]
        except Exception:
            pass
    return None


def _get_all_query_params() -> dict:
    """Get all query parameters."""
    try:
        return dict(st.query_params)
    except Exception:
        try:
            return st.experimental_get_query_params()
        except Exception:
            return {}


def _clear_query_params():
    """Clear all query parameters."""
    try:
        st.query_params.clear()
    except Exception:
        st.experimental_set_query_params()


def _runtime_secret(key: str, default=None):
    """
    Get a secret value from session state, query params, st.secrets, or environment.
    Priority: session state override > query params > secrets.toml > env vars
    """
    override_key = f"override_{key}"
    val = st.session_state.get(override_key)
    if val:
        return val
    if key == "NOTION_TOKEN":
        qp = _get_query_param("notion_token")
        if qp:
            return qp
    if key == "DATABASE_ID":
        qp = _get_query_param("database_id")
        if qp:
            return qp
    try:
        return st.secrets[key]
    except Exception:
        return os.environ.get(key, default)


# ------------------------------- package imports ------------------------------
# load_trades_from_notion is imported in data_loading module

# Pull in externalized modules for cleaner structure
from data_loading import load_live_df
from filters import render_filters
from edge_analysis.core.constants import MODEL_SET, SESSION_CANONICAL
from edge_analysis.ui.components import show_light_table
from edge_analysis.ui.tabs import render_all_tabs, generate_overall_stats
from edge_analysis.user_store import get_user, upsert_user, set_user_db
from edge_analysis.data import whoop


# --------------------------- UI helpers ---------------------------------------


def render_entry_model_table(df: pd.DataFrame, title: str = "Entry Model Performance"):
    """
    Render a styled entry model performance table.

    Args:
        df: DataFrame with columns: Entry_Model, Trades, Win %, BE %, Loss %
        title: Table title to display
    """
    expected = ["Entry_Model", "Trades", "Win %", "BE %", "Loss %"]
    if df is None or df.empty or any(col not in df.columns for col in expected):
        return

    def fmt_int(v):
        return "" if pd.isna(v) else f"{int(v)}"

    def fmt_num(v, decimals=2):
        return "" if pd.isna(v) else f"{float(v):.{decimals}f}"

    header_html = (
        '<th class="text">Entry_Model</th>'
        '<th class="num">Trades</th>'
        '<th class="num">Win %</th>'
        '<th class="num">BE %</th>'
        '<th class="num">Loss %</th>'
    )

    rows_html = []
    for _, r in df.iterrows():
        rows_html.append(
            "<tr>"
            f'<td class="text">{r.get("Entry_Model", "")}</td>'
            f'<td class="num">{fmt_int(r.get("Trades"))}</td>'
            f'<td class="num">{fmt_num(r.get("Win %"))}</td>'
            f'<td class="num">{fmt_num(r.get("BE %"))}</td>'
            f'<td class="num">{fmt_num(r.get("Loss %"))}</td>'
            "</tr>"
        )

    table_html = f"""
    <div class="entry-card">
      <h2>{title}</h2>
      <div class="table-wrap">
        <table class="entry-model-table">
          <thead><tr>{header_html}</tr></thead>
          <tbody>{''.join(rows_html)}</tbody>
        </table>
      </div>
    </div>
    """
    st.markdown(table_html, unsafe_allow_html=True)


# ------------------------------- OAuth & Connect ------------------------------
@st.cache_resource
def _oauth_store() -> dict:
    """In-memory store for OAuth state verification."""
    return {}


def _oauth_put(state: str, code_verifier: str):
    """Store OAuth state and PKCE verifier."""
    _oauth_store()[state] = {"code_verifier": code_verifier, "ts": time.time()}


def _oauth_pop(state: str) -> Optional[dict]:
    """Retrieve and remove OAuth state."""
    return _oauth_store().pop(state, None)


def _pkce_pair() -> Tuple[str, str]:
    """
    Generate PKCE code verifier and challenge for OAuth.

    Returns:
        Tuple of (verifier, challenge)
    """
    verifier = base64.urlsafe_b64encode(os.urandom(APIConstants.PKCE_VERIFIER_LENGTH)).decode().rstrip("=")
    challenge = base64.b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    return verifier, challenge


def _oauth_client() -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """
    Get OAuth client credentials from secrets.

    Returns:
        Tuple of (client_id, client_secret, redirect_uri)
    """
    cid = _runtime_secret("NOTION_OAUTH_CLIENT_ID") or _runtime_secret("NOTION_CLIENT_ID")
    csec = _runtime_secret("NOTION_OAUTH_CLIENT_SECRET") or _runtime_secret("NOTION_CLIENT_SECRET")
    ruri = _runtime_secret("NOTION_OAUTH_REDIRECT_URI") or _runtime_secret("NOTION_REDIRECT_URI")
    return cid, csec, ruri


def _exchange_code_for_token(code: str, code_verifier: Optional[str] = None) -> Optional[dict]:
    """
    Exchange OAuth authorization code for access token.

    Args:
        code: Authorization code from Notion
        code_verifier: PKCE code verifier

    Returns:
        Token response dict, or None on error
    """
    client_id, client_secret, redirect_uri = _oauth_client()
    if not (client_id and client_secret and redirect_uri):
        return None

    basic = base64.b64encode(f"{client_id}:{client_secret}".encode("utf-8")).decode("ascii")
    payload = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
    }
    if code_verifier:
        payload["code_verifier"] = code_verifier

    try:
        resp = requests.post(
            "https://api.notion.com/v1/oauth/token",
            headers={
                "Authorization": f"Basic {basic}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=APIConstants.OAUTH_TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.HTTPError as e:
        st.error(f"Notion API error: {e.response.status_code if e.response else 'Unknown'}")
        return None
    except requests.exceptions.JSONDecodeError:
        st.error("Invalid response from Notion")
        return None
    except Exception as e:
        st.error(f"OAuth exchange failed: {e}")
        return None


def _get_notion_me(access_token: str) -> Optional[dict]:
    """
    Fetch current Notion user info.

    Args:
        access_token: Notion access token

    Returns:
        User info dict, or None on error
    """
    if not access_token:
        return None

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Notion-Version": _runtime_secret("NOTION_VERSION", APIConstants.NOTION_API_VERSION),
        "Content-Type": "application/json",
    }
    try:
        r = requests.get(
            "https://api.notion.com/v1/users/me",
            headers=headers,
            timeout=APIConstants.REQUEST_TIMEOUT,
        )
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return None


def _complete_login_with_token(access_token: str, workspace_name: Optional[str] = None):
    """
    Complete login flow after obtaining OAuth token.

    Args:
        access_token: Notion OAuth access token
        workspace_name: Optional workspace name
    """
    st.session_state[SessionKeys.OAUTH_TOKEN] = access_token
    st.session_state[SessionKeys.USER_TOKEN] = access_token

    user_info = _get_notion_me(access_token) or {}
    user_id = user_info.get("id")
    name = user_info.get("name")
    email = None
    person = user_info.get("person")
    if isinstance(person, dict):
        email = person.get("email")

    st.session_state["ea_user_email"] = (email or "")
    st.session_state["ea_user_id"] = str(user_id or "")

    if user_id:
        st.session_state[SessionKeys.USER_ID] = user_id
        upsert_user(user_id, name=name, email=email, workspace=workspace_name)
        rec = get_user(user_id) or {}
        dbid = rec.get("db_id")
        if dbid:
            st.session_state[SessionKeys.DB_ID] = dbid
            st.session_state[SessionKeys.NAV_TARGET] = PageNames.DASHBOARD
        else:
            st.session_state[SessionKeys.NAV_TARGET] = PageNames.CONNECT
    else:
        st.session_state[SessionKeys.NAV_TARGET] = PageNames.CONNECT


def _prepare_oauth_url() -> Optional[str]:
    """
    Prepare OAuth authorization URL with PKCE.

    Returns:
        Authorization URL, or None if credentials missing
    """
    client_id, _, redirect_uri = _oauth_client()
    if not (client_id and redirect_uri):
        return None

    state = secrets.token_urlsafe(APIConstants.OAUTH_STATE_LENGTH)
    verifier, challenge = _pkce_pair()
    st.session_state[SessionKeys.OAUTH_PENDING] = {"state": state, "verifier": verifier}
    _oauth_put(state, verifier)

    params = {
        "client_id": client_id,
        "response_type": "code",
        "owner": "user",
        "redirect_uri": redirect_uri,
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    return "https://api.notion.com/v1/oauth/authorize?" + urlencode(params)


def _handle_oauth_callback() -> bool:
    """
    Handle OAuth callback from Notion.

    Returns:
        True if callback was handled, False otherwise
    """
    qp = _get_all_query_params()
    code = qp.get("code")[0] if isinstance(qp.get("code"), list) else qp.get("code")
    rstate = qp.get("state")[0] if isinstance(qp.get("state"), list) else qp.get("state")

    if not code or not rstate:
        return False

    if str(rstate).startswith(WHOOP_STATE_PREFIX):
        return False

    rec = _oauth_pop(rstate)
    verifier = (rec or {}).get("code_verifier") or (st.session_state.get(SessionKeys.OAUTH_PENDING) or {}).get("verifier")

    try:
        data = _exchange_code_for_token(code, code_verifier=verifier)
        if not data:
            raise RuntimeError("Token exchange returned no data")

        access_token = data.get("access_token")
        if not access_token:
            raise RuntimeError("No access_token in Notion response")

        ws = data.get("workspace_name") or data.get("bot_id")
        _complete_login_with_token(access_token, workspace_name=ws)
        st.success("Connected to Notion via OAuth")
        if ws:
            st.caption(f"Workspace: {ws}")
        if _auto_connect_journal():
            st.success("Found your journal — opening your dashboard…")
    except Exception as e:
        st.error(f"OAuth token exchange failed: {e}")
    finally:
        st.session_state.pop(SessionKeys.OAUTH_PENDING, None)
        _clear_query_params()
        _st_rerun()

    return True


def _auto_connect_journal() -> bool:
    """After sign-in: find the journal among shared databases and connect it
    without asking anything, when the answer is unambiguous."""
    token = st.session_state.get(SessionKeys.OAUTH_TOKEN) \
        or st.session_state.get(SessionKeys.USER_TOKEN)
    if not token or st.session_state.get(SessionKeys.DB_ID):
        return False
    try:
        from edge_analysis.data.db_finder import find_journals
        cands = find_journals(token)
    except Exception:
        cands = None
    if cands is None:
        return False
    st.session_state["ea_db_cands"] = cands
    strong = [c for c in cands if c["hits"] >= 5]
    if len(strong) == 1:
        dbid = strong[0]["id"]
        st.session_state[SessionKeys.DB_ID] = dbid
        uid = st.session_state.get(SessionKeys.USER_ID)
        if uid:
            set_user_db(uid, dbid, template=strong[0]["schema"])
        st.session_state[SessionKeys.NAV_TARGET] = PageNames.DASHBOARD
        return True
    return False


# -------------------- Database helpers ----------------------------------------
def _validate_dbid(dbid: str) -> bool:
    """
    Validate Notion database ID format.

    Args:
        dbid: Database ID to validate

    Returns:
        True if valid 32-character hex string
    """
    return bool(dbid and re.fullmatch(r"[0-9a-f]{32}", dbid.lower()))


def _extract_db_id_from_url_or_id(text: str) -> Optional[str]:
    """
    Extract Notion database ID from URL or raw ID.

    Args:
        text: Database URL or ID string

    Returns:
        Normalized 32-char hex ID, or None if invalid
    """
    if not text:
        return None

    t = text.strip()
    raw = t.replace("-", "")

    # Check if it's already a valid ID
    if re.fullmatch(r"[0-9a-fA-F]{32}", raw):
        return raw.lower()

    # Try to extract from URL
    try:
        u = urlparse(t)
        path = (u.path or "").replace("-", "")
        m = re.search(r"([0-9a-fA-F]{32})", path)
        if m:
            return m.group(1).lower()
    except Exception:
        pass

    return None


def _verify_database_access(oauth_token: Optional[str], internal_token: Optional[str], dbid: str) -> Tuple[bool, Optional[int], Union[dict, str]]:
    """
    Verify access to a Notion database.

    Args:
        oauth_token: OAuth access token from user authentication
        internal_token: Internal integration token (fallback)
        dbid: Notion database ID (32-char hex string)

    Returns:
        Tuple of (success, status_code, response_data_or_error)
    """
    # Validate database ID format first
    if not _validate_dbid(dbid):
        return (False, None, "Invalid database ID format")

    token = oauth_token or internal_token
    if not token:
        return (False, None, "No Notion token available.")

    headers = {
        "Authorization": f"Bearer {token}",
        "Notion-Version": _runtime_secret("NOTION_VERSION", APIConstants.NOTION_API_VERSION),
        "Content-Type": "application/json",
    }
    url = f"https://api.notion.com/v1/databases/{dbid}"

    try:
        r = requests.get(url, headers=headers, timeout=APIConstants.REQUEST_TIMEOUT)
        if r.status_code == 200:
            return (True, 200, r.json())
        else:
            return (False, r.status_code, r.text)
    except requests.exceptions.Timeout:
        return (False, None, "Request timed out")
    except requests.exceptions.RequestException as e:
        return (False, None, f"Network error: {e}")
    except Exception as e:
        return (False, None, f"Request failed: {e}")


# ---- Connect page UI ---------------------------------------------------------
def _connect_page_css():
    """Inject CSS specific to the Connect page."""
    st.markdown(
        f"""
        <style>
        :root {{ --brand: {BRAND_PURPLE}; }}
        [data-testid="stSidebar"] * {{ color:#0f172a !important; }}

        .connect-wrap {{ max-width: 980px; margin: 0 auto; }}
        .ea-title {{
            display:flex; align-items:center; gap:.6rem;
            font-size:38px; line-height:1.2; font-weight:800; letter-spacing:-0.02em;
            color:#0f172a; margin:6px 0 8px 0;
        }}
        .ea-sub {{ color:#475569; font-size:16px; margin:0 0 16px 0; }}
        .ea-card {{
            background:#fff; border-radius:18px; box-shadow:0 8px 30px rgba(0,0,0,.06);
            border:1px solid rgba(0,0,0,0.06); padding:24px 28px; margin: 10px 0 18px 0;
        }}
        .ea-divider {{ height:1px; background:#e5e7eb; margin:16px 0 12px 0; }}
        .ea-step {{ font-size:22px; font-weight:800; color:#0f172a; margin: 6px 0 6px 0; }}
        .ea-help {{ color:#475569; font-size:15px; margin-bottom:14px; }}

        .stButton>button {{
            border-radius:12px; padding:12px 18px; font-weight:700;
            border:1px solid rgba(0,0,0,0.06); box-shadow:0 2px 6px rgba(0,0,0,0.04);
        }}
        .ea-primary .stButton>button {{ background:var(--brand); color:#fff; border-color:var(--brand); }}
        .ea-secondary .stButton>button {{ background:#fff; color:#111827; }}

        .stTextInput>div>div>input {{
            border: 2px solid #e5e7eb !important; border-radius:12px !important;
            padding:12px 14px !important; font-size:15px !important;
        }}

        @media (max-width: 800px) {{
          .ea-title {{ font-size:30px; }}
          .ea-step {{ font-size:19px; }}
          .ea-card {{ padding:18px 18px; }}
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_connect_page(mobile: bool):
    """
    Render the Connect Notion page.

    Args:
        mobile: Whether to render in mobile mode
    """
    inject_header("light")
    _connect_page_css()

    if _handle_oauth_callback():
        pass

    with st.container():
        st.markdown('<div class="connect-wrap">', unsafe_allow_html=True)
        _signed_in = bool(st.session_state.get(SessionKeys.USER_TOKEN)
                          or st.session_state.get(SessionKeys.OAUTH_TOKEN))
        _ttl = "Your journals" if _signed_in else "Connect your journal"
        _sub = ("Switching only changes which data the dashboard reads \u2014 "
                "nothing in your Notion is touched."
                if _signed_in else
                "Sign in once \u2014 your journals appear by themselves.")
        st.markdown(f'<div class="ea-title">{_ttl}</div>'
                    "<div style='text-align:center;font-size:14px;color:#64748b;"
                    f"margin:2px 0 14px;'>{_sub}</div>", unsafe_allow_html=True)
        if _signed_in:
            _cur_db0 = str(st.session_state.get(SessionKeys.DB_ID) or "").replace("-", "")
            _cands0 = st.session_state.get("ea_db_cands") or []
            _cur_t = next((c["title"] for c in _cands0
                           if c.get("id") == _cur_db0), None)
            if _cur_db0:
                _cur_lab = _cur_t or "your journal"
                st.markdown(
                    "<div style='display:flex;justify-content:center;margin:0 0 16px;'>"
                    "<div style='display:inline-flex;align-items:center;gap:9px;"
                    "background:#e9f7ef;border:1px solid #bfe6cd;border-radius:999px;"
                    "padding:9px 18px;font-size:13.5px;font-weight:700;color:#14532d;'>"
                    "<span style='width:9px;height:9px;border-radius:50%;"
                    "background:#16a34a;display:inline-block;'></span>"
                    f"Reading from: {_cur_lab}</div></div>", unsafe_allow_html=True)
        if not st.session_state.get(SessionKeys.USER_TOKEN):
            st.markdown(
                "<div style='text-align:center;font-size:14px;color:#64748b;"
                "margin:2px 0 10px;'>Just looking? Explore every chart with a "
                "realistic simulated journal — no account, nothing to connect.</div>",
                unsafe_allow_html=True)
            _dc1, _dc2, _dc3 = st.columns([1, 1.2, 1])
            with _dc2:
                st.button("▶ View the live demo", key="ea_demo_enter", type="primary",
                          use_container_width=True, on_click=_enter_demo)
            st.markdown("<div style='text-align:center;color:#cbd5e1;"
                        "font-size:12px;margin:2px 0 10px;'>— or connect your own —</div>",
                        unsafe_allow_html=True)
        st.markdown('<div class="ea-card">', unsafe_allow_html=True)

        _tpl_url = _runtime_secret("TEMPLATE_URL")
        if not _signed_in:
            if _tpl_url:
                st.markdown('<div class="ea-step">Step 1 — Get the journal template</div>',
                            unsafe_allow_html=True)
                st.markdown('<div class="ea-help">Open it in Notion and press '
                            '<b>Duplicate</b> (top-right). Skip this if you already '
                            'use an Edge Analysis journal.</div>', unsafe_allow_html=True)
                st.markdown(f'<a href="{_tpl_url}" target="_blank" class="ea-link-btn" '
                            'style="background:#fff;color:#4800ff;border:2px solid #4800ff;">'
                            '📒 Get the free template</a>', unsafe_allow_html=True)
                st.markdown('<div class="ea-divider"></div>', unsafe_allow_html=True)
                st.markdown('<div class="ea-step">Step 2 — Sign in with Notion</div>',
                            unsafe_allow_html=True)
            else:
                st.markdown('<div class="ea-step">Step 1 — Sign in with Notion</div>',
                            unsafe_allow_html=True)
            st.markdown('<div class="ea-help">No keys, no setup — one click. Notion will '
                        'show a checklist of your pages: <b>tick your Trade Journal</b> '
                        '(or the template you just duplicated) so the app can read it.</div>',
                        unsafe_allow_html=True)
        else:
            st.markdown('<div class="ea-step">Share more pages</div>',
                        unsafe_allow_html=True)
            st.markdown('<div class="ea-help">Made a new journal and it\'s not in the '
                        'list below? Notion only shares what you <b>tick</b>. Press '
                        '<b>Connect Notion</b>, and on Notion\'s screen choose '
                        '<b>Select pages</b> and tick the page your new journal lives '
                        'in \u2014 new pages are never added by themselves. '
                        'Then press <b>\u21bb Look again</b> below.</div>',
                        unsafe_allow_html=True)

        _cid, _csec, _ruri = _oauth_client()
        missing = []
        if not _cid:
            missing.append("Client ID")
        if not _csec:
            missing.append("Client Secret")
        if not _ruri:
            missing.append("Redirect URI")
        if missing:
            st.warning(
                "OAuth secrets not fully configured: " + ", ".join(missing) +
                ". Add either NOTION_OAUTH_* or NOTION_* to your `.streamlit/secrets.toml`."
            )

        # Callback fallback
        if st.session_state.get(SessionKeys.OAUTH_CALLBACK):
            st.info("We received a callback from Notion but your session was reset.")
            if st.button("Finalise sign-in", key="btn_finalize_oauth"):
                code = st.session_state.get(SessionKeys.OAUTH_CALLBACK)
                try:
                    data = _exchange_code_for_token(code, code_verifier=None)
                    if not data:
                        raise RuntimeError("Token exchange returned no data")
                    access_token = data.get("access_token")
                    if not access_token:
                        raise RuntimeError("No access_token in Notion response")
                    _complete_login_with_token(access_token)
                    st.success("Notion connected via OAuth")
                except Exception as e:
                    st.error(f"OAuth token exchange failed: {e}")
                finally:
                    st.session_state.pop(SessionKeys.OAUTH_CALLBACK, None)
                    _st_rerun()

        c1, c2 = st.columns(2)
        with c1:
            st.markdown('<div class="ea-primary">', unsafe_allow_html=True)
            auth_url = _prepare_oauth_url()
            if auth_url:
                st.link_button("Connect Notion", auth_url)
            else:
                st.button("Connect Notion", disabled=True)
            st.markdown('</div>', unsafe_allow_html=True)

        with c2:
            st.markdown('<div class="ea-secondary">', unsafe_allow_html=True)
            if st.button("Disconnect", key="btn_oauth_clear"):
                for key in [
                    SessionKeys.OAUTH_TOKEN,
                    SessionKeys.USER_TOKEN,
                    SessionKeys.USER_ID,
                    SessionKeys.OAUTH_PENDING,
                    SessionKeys.OAUTH_CALLBACK,
                ]:
                    st.session_state.pop(key, None)
                _clear_device_auth()
                st.info("Disconnected.")
            st.markdown('</div>', unsafe_allow_html=True)

        if st.session_state.get(SessionKeys.OAUTH_TOKEN):
            st.success("Connected (token stored for this session only)")
        elif st.session_state.get(SessionKeys.OAUTH_PENDING):
            st.info("Completing Notion sign-in...")

        st.markdown('<div class="ea-divider"></div>', unsafe_allow_html=True)

        # The journal list — nobody pastes anything
        if _signed_in:
            st.markdown('<div class="ea-step">Your journals</div>',
                        unsafe_allow_html=True)
        else:
            _step_n = "3" if _tpl_url else "2"
            st.markdown(f'<div class="ea-step">Step {_step_n} — We find your journal '
                        'automatically</div>', unsafe_allow_html=True)
        st.markdown('<div class="ea-jlist"></div>', unsafe_allow_html=True)
        oauth_token = st.session_state.get(SessionKeys.OAUTH_TOKEN)
        _cur_db = st.session_state.get(SessionKeys.DB_ID)
        if oauth_token:
            if st.session_state.get("ea_db_cands") is None:
                with st.spinner("Looking through your shared pages…"):
                    from edge_analysis.data.db_finder import find_journals
                    st.session_state["ea_db_cands"] = find_journals(oauth_token)
            _cands = st.session_state.get("ea_db_cands")
            if _cands:
                from edge_analysis.data.db_finder import schema_label
                st.markdown('<div class="ea-help">Your journals \u2014 tap to connect '
                            'or switch:</div>', unsafe_allow_html=True)
                for _c in _cands[:6]:
                    _is_cur = _cur_db and _c["id"] == str(_cur_db).replace("-", "")
                    _lab = (("✓  " if _is_cur else "📒  ") + _c["title"]
                            + "   ·   " + schema_label(_c["schema"])
                            + ("   ·   reading now" if _is_cur else ""))
                    if st.button(_lab, key=f"ea_pick_{_c['id'][:10]}",
                                 use_container_width=True, disabled=bool(_is_cur)):
                        st.session_state[SessionKeys.DB_ID] = _c["id"]
                        _uid = st.session_state.get(SessionKeys.USER_ID)
                        if _uid:
                            set_user_db(_uid, _c["id"], template=_c["schema"])
                        # force the device memory to follow the new choice
                        st.session_state.pop("ea_auth_sig", None)
                        st.session_state[SessionKeys.NAV_TARGET] = PageNames.DASHBOARD
                        _st_rerun()
            elif _cands is not None:
                st.warning("Signed in, but no journal is shared with the app yet. "
                           "Notion only shares the pages you TICK at sign-in \u2014 and "
                           "pages created later aren't added automatically. Tap "
                           "**Connect Notion** above, tick the page that holds your "
                           "journal, then **\u21bb Look again**.")
            if st.button("↻ Look again", key="ea_db_refind"):
                st.session_state.pop("ea_db_cands", None)
                _st_rerun()
        else:
            st.markdown('<div class="ea-help">Sign in first — then your journal '
                        'appears here by itself.</div>', unsafe_allow_html=True)

        with st.expander("Advanced: paste a database link instead"):
            db_link = st.text_input(
                "Database link or ID",
                value=st.session_state.get("db_link_input", ""),
                key="db_link_input",
                placeholder="https://www.notion.so/My-DB-Name-1234567abcd1234ef567890abcd1234",
            )

            if db_link:
                dbid = _extract_db_id_from_url_or_id(db_link)
                if not dbid:
                    st.error("That doesn't look like a valid Notion database link or ID.")
                else:
                    st.caption(f"Detected database ID: `{dbid}`")
                    ok, status, info = _verify_database_access(
                        oauth_token=oauth_token,
                        internal_token=None,
                        dbid=dbid,
                    )
                    if ok:
                        st.success("Database verified")
                        st.session_state[SessionKeys.DB_ID] = dbid
                        uid = st.session_state.get(SessionKeys.USER_ID)
                        if uid:
                            set_user_db(uid, dbid)
                        st.session_state.pop("ea_auth_sig", None)
                        st.session_state[SessionKeys.NAV_TARGET] = PageNames.DASHBOARD
                        _st_rerun()
                    else:
                        if status == 403:
                            st.warning(
                                "Access denied (403). In Notion, open the database → ⋯ → "
                                "Add connections → choose your app/integration, then try again."
                            )
                            if st.button("Verify again"):
                                _st_rerun()
                        elif status == 404:
                            # A 404 on a private object usually means ACCESS,
                            # not existence: the sign-in didn't include it.
                            _res = None
                            if oauth_token:
                                try:
                                    import requests as _rq
                                    _kids = _rq.get(
                                        f"https://api.notion.com/v1/blocks/{dbid}/children",
                                        headers={"Authorization": f"Bearer {oauth_token}",
                                                 "Notion-Version": "2022-06-28"},
                                        params={"page_size": 50}, timeout=15)
                                    for _blk in (_kids.json() or {}).get("results", []):
                                        if _blk.get("type") == "child_database":
                                            _res = _blk["id"].replace("-", "")
                                            break
                                except Exception:
                                    _res = None
                            if _res:
                                st.success("That link was a page — found the journal inside it.")
                                st.session_state[SessionKeys.DB_ID] = _res
                                uid = st.session_state.get(SessionKeys.USER_ID)
                                if uid:
                                    set_user_db(uid, _res)
                                st.session_state.pop("ea_auth_sig", None)
                                st.session_state[SessionKeys.NAV_TARGET] = PageNames.DASHBOARD
                                _st_rerun()
                            else:
                                st.error(
                                    "Notion answered 404 — for private databases that "
                                    "almost always means your sign-in doesn't include "
                                    "it, not that it doesn't exist.")
                                st.markdown(
                                    "<div style='font-size:13.5px;color:#64748b;line-height:1.7;'>"
                                    "Fix: press <b>Connect Notion</b> above and on Notion's "
                                    "checklist tick the page that holds this database "
                                    "(new pages aren't included automatically) — or in "
                                    "Notion open the database &rarr; &#8943; &rarr; "
                                    "<b>Connections</b> &rarr; add Edge Analysis. "
                                    "Then press Verify again.</div>",
                                    unsafe_allow_html=True)
                                if st.button("Verify again", key="btn_verify_404"):
                                    _st_rerun()
                        else:
                            st.error(f"Couldn't verify the database. {info}")

        st.markdown('<div class="ea-divider"></div>', unsafe_allow_html=True)
        if st.button("Back to dashboard", key="btn_return_dashboard_connect", use_container_width=True):
            st.session_state[SessionKeys.NAV_TARGET] = PageNames.DASHBOARD
            _st_rerun()

        st.markdown('</div>', unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)


# --------------------------- Login gate ---------------------------------------
def _inject_signin_css():
    """Inject sign-in page specific CSS."""
    st.markdown(
        """
        <style>
        /* Hide header and sidebar on sign-in */
        header[data-testid="stHeader"] { display: none !important; }
        [data-testid="stSidebar"] { display: none !important; }

        /* App background - soft gradient for depth */
        [data-testid="stAppViewContainer"] {
            background: linear-gradient(135deg, #f6f7fb 0%, #eef1fb 100%) !important;
        }

        /* Wrapper for centered sign-in card
           Use full viewport height with no extra padding or margin so
           the login card is vertically centred without empty space above or below. */
        .ea-signin-wrap {
            height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 0;
            margin: 0;
        }

        /* Sign-in card */
        .ea-signin-card {
            background: #ffffff;
            border-radius: 24px;
            max-width: 480px;
            width: 100%;
            padding: 3rem;
            border: 1px solid #e6e8f3;
            box-shadow: 0 16px 36px rgba(72, 0, 255, 0.1);
            text-align: center;
        }

        /* Logo in sign-in card */
        .ea-signin-logo {
            margin-bottom: 1rem;
            display: block;
        }

        /* Title and subtitle in card */
        .ea-signin-card h1 {
            font-size: 2.25rem;
            font-weight: 800;
            color: #0f172a;
            margin: 0 0 0.75rem 0;
        }
        .ea-signin-card p {
            font-size: 1rem;
            color: #475569;
            margin: 0 0 2rem 0;
            line-height: 1.6;
        }

        /* Sign-in button */
        .ea-link-btn {
            display: block;
            background: #4800ff !important;
            color: #ffffff !important;
            border: none;
            border-radius: 12px;
            padding: 0.9rem 1.2rem;
            font-weight: 700;
            font-size: 1rem;
            text-decoration: none;
            width: 100%;
            transition: background 0.15s ease;
        }
        .ea-link-btn:hover {
            background: #3800cc !important;
            box-shadow: 0 4px 14px rgba(72, 0, 255, 0.25);
            transform: translateY(-2px);
        }

        /* Note styling */
        .ea-login-note {
            margin-top: 1.6rem;
            font-size: 0.85rem;
            color: #6b7280;
            padding: 1rem 1rem;
            border-radius: 12px;
            border: 1px solid #e5e7eb;
            background: #f8f6ff;
            line-height: 1.4;
        }

        /* Responsive adjustments */
        @media (max-width: 720px) {
            .ea-signin-card {
                padding: 2rem 2rem;
            }
            .ea-signin-card h1 {
                font-size: 1.8rem;
            }
            .ea-signin-card p {
                font-size: 0.95rem;
            }
        }

        /* Sign-in button */
        .ea-link-btn {
            display: inline-block;
            background: #4800ff !important;
            color: #ffffff !important;
            border: none;
            border-radius: 12px;
            padding: 1rem 1.5rem;
            font-weight: 700;
            font-size: 1rem;
            text-decoration: none;
            width: 100%;
            transition: all 0.15s ease;
        }
        .ea-link-btn:hover {
            background: #3800cc !important;
            box-shadow: 0 4px 14px rgba(72, 0, 255, 0.25);
            transform: translateY(-2px);
        }

        /* Note styling */
        .ea-login-note {
            margin-top: 1.5rem;
            font-size: 0.85rem;
            color: #6b7280;
            padding: 1rem 1rem;
            border-radius: 12px;
            border: 1px solid #e5e7eb;
            background: #f8f6ff;
            line-height: 1.4;
        }

        /* Responsive adjustments */
        @media (max-width: 720px) {
            .ea-login-container {
                flex-direction: column;
                padding: 3rem 1rem;
            }
            .ea-login-card {
                max-width: 100%;
                padding: 2rem 2rem;
            }
            .ea-login-hero h1 {
                font-size: 2.25rem;
            }
            .ea-login-hero p {
                font-size: 1rem;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _render_login_page():
    """Render the login/sign-in page using pure Streamlit components."""
    _inject_signin_css()

    # Get OAuth URL from existing helper
    auth_url = _prepare_oauth_url()
    if not auth_url:
        st.error("Could not prepare Notion OAuth URL. Check your client ID, secret, and redirect URI.")
        return

    # Centered sign-in page layout using a single card
    # Load the logo image and convert to base64 if available
    logo_html = ""
    try:
        assets_dir = ASSETS_DIR if 'ASSETS_DIR' in globals() else _find_assets_dir()
        logo_path = assets_dir / "edge_logoslim.png"
        if not logo_path.exists():
            logo_path = assets_dir / "edge_logo.png"
        if logo_path.exists():
            with open(logo_path, "rb") as _lf:
                _lb64 = base64.b64encode(_lf.read()).decode()
            logo_html = f'<img class="ea-signin-logo" src="data:image/png;base64,{_lb64}" alt="Edge Analysis" />'
    except Exception:
        pass

    st.markdown("""
        <style>
        div[data-testid="stVerticalBlock"]:has(> div.stElementContainer .ea-wallcard) {
            background: #ffffff; border-radius: 24px; max-width: 480px;
            padding: 3rem; border: 1px solid #e6e8f3;
            box-shadow: 0 16px 36px rgba(72, 0, 255, 0.1);
            margin: 8vh auto 0; text-align: center; gap: 0 !important;
        }
        div[data-testid="stVerticalBlock"]:has(> div.stElementContainer .ea-wallcard)
            .stButton > button {
            width: 100%; background: #ffffff; color: #4800ff;
            border: 2px solid #4800ff; border-radius: 999px;
            font-weight: 700; padding: 0.72rem 1rem;
        }
        div[data-testid="stVerticalBlock"]:has(> div.stElementContainer .ea-wallcard)
            .stButton > button:hover {
            background: #f4f0ff; color: #4800ff; border-color: #4800ff;
        }
        </style>""", unsafe_allow_html=True)
    with st.container():
        st.markdown(
            f"""<div class="ea-wallcard"></div>{logo_html}
            <p style="margin:0 0 18px;">Connect your trading journal to unlock insights.</p>""",
            unsafe_allow_html=True)
        st.button("▶ View the live demo", key="ea_demo_enter_wall",
                  use_container_width=True, on_click=_enter_demo)
        _tpl = _runtime_secret("TEMPLATE_URL")
        _tpl_html = (f'<a href="{_tpl}" target="_blank" style="color:#4800ff;'
                     f'font-weight:700;">Get the free template</a> · ' if _tpl else "")
        st.markdown(
            f"""<div style="font-size:12.5px;color:#64748b;margin:6px 0 16px;">
              Realistic simulated journal — nothing to connect</div>
            <a href="{auth_url}" class="ea-link-btn">Sign in with Notion</a>
            <div style="font-size:12.5px;color:#64748b;margin:10px 0 0;">
              {_tpl_html}Notion will show a checklist of your pages —
              <b>tick your Trade Journal</b> and we find it automatically.</div>
            <div class="ea-login-note">
              🔒 Your Notion credentials are never stored. Authentication is handled securely via Notion's OAuth system.
            </div>""",
            unsafe_allow_html=True)
    with st.expander("On your phone and it opens the Notion app instead?"):
        st.markdown(
            "That happens when your phone's **browser** isn't signed in to Notion — "
            "the sign-in detour is what switches you to the app. One-time fix:\n\n"
            "1. In this browser, go to **notion.so** and log in "
            "(if it offers to open the app, choose *Continue in browser*).\n"
            "2. Come back here and tap **Sign in with Notion** — you'll get the "
            "normal page to select your template.\n\n"
            "After that, this device stays signed in automatically."
        )


# ----------------------- Device-persistent login ------------------------------
_DEVICE_AUTH_KEY = "ea_auth"


def _js_eval(expr: str, key: str):
    """Run JS in the visitor's browser via streamlit-js-eval. Returns None while
    the component round-trip is pending, or on any failure."""
    try:
        from streamlit_js_eval import streamlit_js_eval
        return streamlit_js_eval(js_expressions=expr, key=key)
    except Exception:
        return None


def _prefs_blob() -> dict:
    """Read every stored preference in ONE browser round-trip. Four separate
    components meant four component mounts (and reruns) on every cold boot."""
    if "ea_prefs" in st.session_state:
        return st.session_state["ea_prefs"]
    tries = int(st.session_state.get("ea_prefs_tries", 0))
    if tries >= 6:
        return {}
    st.session_state["ea_prefs_tries"] = tries + 1
    raw = _js_eval(
        "JSON.stringify({v:localStorage.getItem('ea_view')||'',"
        "f:localStorage.getItem('ea_filters')||'',"
        "p:localStorage.getItem('ea_mplan')||'',"
        "t:localStorage.getItem('ea_theme')||'',"
        "d:localStorage.getItem('ea_density')||'',"
        "su:localStorage.getItem('ea_setup')||''})",
        key="ea_prefs_load")
    if not raw:
        return {}
    try:
        blob = json.loads(raw) or {}
    except ValueError:
        return {}
    if isinstance(blob, dict):
        st.session_state["ea_prefs"] = blob
        return blob
    return {}


def _sync_device_auth() -> None:
    """Persist the current login to this device's browser storage, so the next
    visit to the plain URL logs in automatically (critical on phones, where the
    Notion app can hijack the OAuth consent page)."""
    token = (
        st.session_state.get(SessionKeys.USER_TOKEN)
        or st.session_state.get(SessionKeys.OAUTH_TOKEN)
    )
    if not token:
        return
    dbid = st.session_state.get(SessionKeys.DB_ID) or ""
    _sig = f"{token[-10:]}|{dbid}"
    if st.session_state.get("ea_auth_sig") == _sig:
        return
    st.session_state["ea_auth_sig"] = _sig
    js = (
        "(function(){var o={};try{o=JSON.parse(localStorage.getItem("
        + json.dumps(_DEVICE_AUTH_KEY)
        + ")||'{}')}catch(e){};var v={t:" + json.dumps(token)
        + ",d:" + json.dumps(dbid) + "||o.d||''};localStorage.setItem("
        + json.dumps(_DEVICE_AUTH_KEY) + ",JSON.stringify(v));return true;})()"
    )
    _js_eval(js, key="ea_auth_save")


def _restore_device_auth() -> bool:
    """Try to log in from browser storage. Returns True if login completed."""
    saved = _js_eval(f"localStorage.getItem({json.dumps(_DEVICE_AUTH_KEY)}) || ''",
                     key="ea_auth_load")
    if saved is None:
        return None  # component still resolving — caller may wait briefly
    if not saved:
        return False
    try:
        rec = json.loads(saved)
    except Exception:
        return False
    if not (isinstance(rec, dict) and rec.get("t")):
        return False
    _complete_login_with_token(rec["t"])
    # The device remembers the journal you used LAST TIME ON THIS DEVICE —
    # the server store remembers what you actually chose last. Server wins;
    # the device value only fills a gap (e.g. store wiped by a redeploy).
    dbid = str(rec.get("d") or "")
    if dbid and _validate_dbid(dbid.replace("-", "")) \
            and not st.session_state.get(SessionKeys.DB_ID):
        st.session_state[SessionKeys.DB_ID] = dbid
    if st.session_state.get(SessionKeys.DB_ID):
        st.session_state[SessionKeys.NAV_TARGET] = PageNames.DASHBOARD
    return True


def _recover_db_from_device() -> None:
    """After login, if no template/database is attached (e.g. the server-side
    store was wiped by a redeploy), recover it from this device's storage and
    heal the server store."""
    if st.session_state.get(SessionKeys.DB_ID):
        return
    saved = _js_eval(f"localStorage.getItem({json.dumps(_DEVICE_AUTH_KEY)}) || ''",
                     key="ea_db_recover")
    if not saved:
        return
    try:
        rec = json.loads(saved)
    except Exception:
        return
    dbid = str((rec or {}).get("d") or "")
    if not (dbid and _validate_dbid(dbid.replace("-", ""))):
        return
    st.session_state[SessionKeys.DB_ID] = dbid
    uid = st.session_state.get(SessionKeys.USER_ID)
    if uid:
        try:
            set_user_db(uid, dbid)
        except Exception:
            pass
    st.session_state[SessionKeys.NAV_TARGET] = PageNames.DASHBOARD
    _st_rerun()


def _clear_device_auth() -> None:
    _js_eval(f"localStorage.removeItem({json.dumps(_DEVICE_AUTH_KEY)})", key="ea_auth_clear")


def _require_notion_login():
    """Enforce Notion OAuth login before accessing main app."""
    qp = _get_all_query_params()
    _rs = qp.get("state")
    _rs = _rs[0] if isinstance(_rs, list) else _rs
    if qp.get("code") and qp.get("state") and not str(_rs or "").startswith(WHOOP_STATE_PREFIX):
        _handle_oauth_callback()
        return

    token = (
        st.session_state.get(SessionKeys.USER_TOKEN)
        or st.session_state.get(SessionKeys.OAUTH_TOKEN)
    )
    if token:
        return

    # Tokenized link (phone handoff): log in straight from the URL.
    url_token = _get_query_param("notion_token")
    if url_token:
        _complete_login_with_token(url_token)
        url_db = _get_query_param("database_id")
        if url_db and _validate_dbid(url_db.replace("-", "")):
            st.session_state[SessionKeys.DB_ID] = url_db
            st.session_state[SessionKeys.NAV_TARGET] = PageNames.DASHBOARD
        return

    # Login saved on this device (set after any previous successful login).
    _restored = _restore_device_auth()
    if _restored:
        _st_rerun()
        return
    if _restored is None and st.session_state.get("ea_auth_tries", 0) < 4:
        # localStorage read still in flight — don't dump the user on the
        # Connect page yet (under load the report can lag a few runs).
        st.session_state["ea_auth_tries"] = st.session_state.get("ea_auth_tries", 0) + 1
        st.markdown("<div style='text-align:center;color:#64748b;font-size:14px;"
                    "padding:120px 0 8px;'>Restoring your session…</div>",
                    unsafe_allow_html=True)
        import time as _t
        _t.sleep(0.8)
        _st_rerun()
        return

    _render_login_page()
    st.stop()


# -------------------------- Mobile CSS helper ---------------------------------
# -------------------------------- Dashboard -----------------------------------
DateRange = Union[DateType, Tuple[DateType, DateType]]


def _apply_date_filter(df: pd.DataFrame, date_range: Optional[DateRange]) -> pd.Series:
    """
    Apply date range filter to dataframe.

    Args:
        df: DataFrame with 'Date' column
        date_range: Single date or tuple of (start, end)

    Returns:
        Boolean mask series
    """
    if date_range is None:
        return pd.Series(True, index=df.index)

    if isinstance(date_range, tuple) and len(date_range) == 2:
        start, end = date_range
        return df["Date"].dt.date.between(start, end)

    # Single date
    return df["Date"].dt.date == date_range


def render_dashboard(mobile: bool):
    """
    Render the main dashboard page.

    Args:
        mobile: Whether to render in mobile mode
    """
    st.markdown(
        f"""
        <style>
        :root {{ --brand: {BRAND_PURPLE}; }}
        [data-testid="stSidebar"] {{ background:#fff !important; }}
        [data-testid="stSidebar"] * {{ color:#0f172a !important; }}

        .ea-empty-wrap {{
            text-align:center;
            margin: 32px 0 18px 0;
        }}
        .ea-empty-title {{
            font-size:24px;
            font-weight:800;
            color:var(--brand);
            letter-spacing:-0.01em;
        }}
        .ea-empty-btn .stButton>button {{
            background:var(--brand);
            color:#ffffff;
            border:none;
            border-radius:999px;
            padding:12px 24px;
            font-weight:700;
            box-shadow:0 8px 22px rgba(72,0,255,0.22);
        }}
        .ea-empty-btn .stButton>button:hover {{
            filter:brightness(0.96);
        }}
        @media (max-width: 768px) {{
          .ea-empty-wrap {{ margin: 24px 0 14px 0; }}
          .ea-empty-title {{ font-size:20px; }}
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )

    styler = get_chart_styler()

    # Get token and database ID
    token = (
        st.session_state.get(SessionKeys.USER_TOKEN)
        or st.session_state.get(SessionKeys.OAUTH_TOKEN)
        or _runtime_secret("NOTION_TOKEN")
    )

    dbid = st.session_state.get(SessionKeys.DB_ID)
    if not dbid:
        uid = st.session_state.get(SessionKeys.USER_ID)
        if uid:
            rec = get_user(uid)
            if rec and rec.get("db_id"):
                dbid = rec["db_id"]
        if not dbid:
            dbid = _runtime_secret("DATABASE_ID")

    _demo = bool(st.session_state.get("ea_demo"))
    _sync = st.session_state.get("ea_last_sync")
    _status = "Live · Notion connected" if (token and dbid) else "Not connected"
    if _demo:
        _status = "Demo · simulated data"
    if token and dbid and _sync:
        try:
            _age = max(0.0, float(pd.Timestamp.now().timestamp()) - float(_sync))
            if _age < 120:
                _ago = "just now"
            elif _age < 3600:
                _ago = f"{int(_age // 60)}m ago"
            elif _age < 86400:
                _ago = f"{int(_age // 3600)}h ago"
            else:
                _ago = f"{int(_age // 86400)}d ago"
            _status += f" · synced {_ago}"
        except (TypeError, ValueError):
            pass  # legacy HH:MM stamp from an older session — drop it
    if mobile:
        inject_header_bar(_status, bool(token and dbid) or _demo)
        _brand = None
    else:
        from edge_analysis.ui.theme import header_parts
        _brand = header_parts(_status, bool(token and dbid) or _demo)
    st.session_state["_ea_connected"] = bool(token and dbid) or _demo

    if _demo:
        df = _demo_frame(pd.Timestamp.now().strftime("%Y-%m-%d"))
        _db1, _db2 = st.columns([4.2, 1])
        with _db1:
            st.markdown(
                "<div style='background:linear-gradient(90deg,#4800ff12,#4800ff08);"
                "border:1px solid #4800ff33;border-radius:12px;padding:10px 16px;"
                "font-size:13.5px;color:#3b3f4d;margin:2px 0 8px;'>"
                "<b style='color:#4800ff;'>You're exploring the demo</b> — a simulated "
                "gold-trading journal. Every chart, insight and the analyst chat work "
                "exactly like this on your own Notion journal.</div>",
                unsafe_allow_html=True)
        with _db2:
            st.button("Connect my data", key="ea_demo_exit", type="primary",
                      use_container_width=True, on_click=_exit_demo)
    else:
        with st.spinner("Reading your journal…"):
            df = load_live_df(token, dbid)

    # Keep the account balance honest: a figure typed days ago is stale the
    # moment the next trade closes, and every % on the site inherits the error.
    # Roll it forward by the P&L banked since it was entered.
    try:
        if df is not None and not df.empty and "Date" in df.columns:
            _lastd = pd.to_datetime(df["Date"], errors="coerce").max()
            if pd.notna(_lastd):
                st.session_state["ea_bal_asof"] = _lastd.isoformat()
            _sav = st.session_state.get("ea_mplan_saved") or {}
            _anchor, _asof = _sav.get("b"), _sav.get("d")
            if _anchor and _asof:
                from edge_analysis.ui.tabs import _pnl_series
                _p = _pnl_series(df)
                if _p is not None:
                    _newer = pd.to_datetime(df["Date"], errors="coerce") > pd.Timestamp(_asof)
                    _since = float(_p[_newer].fillna(0).sum())
                    if abs(_since) >= 0.01:
                        st.session_state["ea_m_bal_rolled"] = float(_anchor) + _since
                        st.session_state["ea_m_bal_rolled_from"] = (
                            float(_anchor), pd.Timestamp(_asof).strftime("%d %b"),
                            int(_newer.sum()))
                    else:
                        st.session_state.pop("ea_m_bal_rolled", None)
    except Exception:
        pass

    if (token and dbid) or _demo:
        pass
    else:
        with st.container():
            st.markdown(
                """
                <div class="ea-empty-wrap">
                  <div class="ea-empty-title">No Notion template is connected yet</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            col_left, col_mid, col_right = st.columns([1, 2, 1])
            with col_mid:
                st.markdown('<div class="ea-empty-btn">', unsafe_allow_html=True)
                if st.button("Connect Notion", key="btn_connect_template", use_container_width=True):
                    st.session_state[SessionKeys.NAV_TARGET] = PageNames.CONNECT
                    _st_rerun()
                st.markdown('</div>', unsafe_allow_html=True)
        return

    if df.empty:
        # Connected but no rows yet — the next five minutes decide whether this
        # person stays. Tell them exactly what happens next, warmly.
        st.markdown(
            """
            <div class="ea-empty-wrap">
              <div class="ea-empty-title">You're connected — now log your first trade</div>
              <div style="font-size:14.5px;color:#5b6270;line-height:1.8;max-width:560px;
                          margin:10px auto 0;text-align:center;">
                Add a trade to your Notion journal and it appears here on the next
                refresh &mdash; charts, sessions, psychology, all of it.
                On MetaTrader&nbsp;5? Grab the sync from the <b>&hellip;</b> menu
                (top right) and your trades log themselves.
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        return

    # Prepare filter options
    instruments = sorted(df["Instrument"].dropna().unique().tolist())
    instruments = [i for i in instruments if i != "DUMMY ROW"]
    inst_opts = ["All"] + instruments
    _models_seen = []
    if "Entry Models List" in df.columns:
        try:
            _models_seen = sorted({
                str(m).strip() for lst in df["Entry Models List"].dropna()
                for m in (lst if isinstance(lst, (list, tuple)) else [lst])
                if str(m).strip() and str(m).strip().lower() not in ("nan", "none")})
        except Exception:
            _models_seen = []
    em_opts = ["All"] + [m for m in MODEL_SET if m in _models_seen]         + [m for m in _models_seen if m not in MODEL_SET]         if _models_seen else ["All"] + MODEL_SET
    sess_opts = ["All"] + sorted(set(SESSION_CANONICAL) | set(df["Session Norm"].dropna().unique()))
    date_mode_options = ["All", "Last 30 days", "Last 90 days", "This year", "Custom"]

    # Account filter options
    _ACCT_MAP = {
        "Demo/Challenge": "Demo",
        "Live/Funded Capital": "Live",
        "Forward Test": "FT",
    }
    _ACCT_FILTER_OPTS = ["All", "Live", "Demo", "FT", "Live and Demo"]
    acct_opts = _ACCT_FILTER_OPTS
    # Real account names, when the journal carries them (MT5 writes the login).
    # These drive the track-record card, which belongs to ONE account.
    _real_accts = []
    if "Account" in df.columns:
        _av = df["Account"].astype(str).str.strip()
        _av = _av[_av.notna() & ~_av.isin(["", "nan", "None"])]
        if not _av.empty and _av.nunique() <= 24 and _av.str.len().max() > 6:
            _counts = _av.value_counts()
            _real_accts = list(_counts.index)
            acct_opts = ["All executed"] + _real_accts
            # Nominate a track-record account once: the one you actually trade
            # most. Everything with a plan rule attached follows it.
            if st.session_state.get("ea_track_account") not in _real_accts:
                _exec_mask = pd.Series(True, index=df.index)
                if "Type of Trade" in df.columns:
                    _tt2 = df["Type of Trade"].astype(str).str.lower()
                    _exec_mask = ~(_tt2.str.contains("forward")
                                   | _tt2.str.contains("back test")
                                   | _tt2.str.contains("backtest"))
                _live = df.loc[_exec_mask & df["Account"].astype(str).str.contains(
                    "live", case=False, na=False), "Account"].astype(str)
                _pick = (_live.value_counts().index[0] if not _live.empty
                         else _counts.index[0])
                st.session_state["ea_track_account"] = _pick
            st.session_state["ea_track_accounts_all"] = _real_accts

    # Trade Type options (MT5 schema only)
    tot_opts = ["All"]
    if "Type of Trade" in df.columns:
        _tot = sorted({
            t.strip()
            for v in df["Type of Trade"].dropna().astype(str)
            for t in re.split(r"[;,]", v) if t.strip()
        })
        if _tot:
            tot_opts = ["All"] + _tot
            _low = [t.lower() for t in _tot]
            _sim = any(("forward" in v or "back" in v or "demo" in v
                        or "paper" in v or "sim" in v) for v in _low)
            _exe = any(not ("forward" in v or "back" in v or "demo" in v
                            or "paper" in v or "sim" in v) for v in _low)
            _extra = []
            if _sim and _exe:
                # The line is execution, not money: a challenge fill is a real
                # fill under real pressure; a forward test never touched a broker.
                _extra.append("Executed")
            if any("live" in v or "funded" in v for v in _low) and \
                    any("challenge" in v or "combine" in v or "evaluation" in v
                        for v in _low):
                _extra.append("Live money")
            if _extra:
                tot_opts = _extra + ["All"] + _tot

    if "Date" in df.columns:
        min_date = df["Date"].min().date()
        max_date = df["Date"].max().date()
    else:
        from datetime import date as _date
        min_date = max_date = _date.today()

    # Render filters (imported from filters module)
    # ── Three-tap setup (first sign-in only) ─────────────────────────────
    # One screen, three choices, saved to this device. Never shown again once
    # answered (localStorage ea_setup=1), never shown while the prefs blob is
    # still in flight, never shown in demo.
    if (not _demo and "ea_prefs" in st.session_state
            and not (st.session_state.get("ea_prefs") or {}).get("su")
            and not st.session_state.get("ea_setup_done")):
        _s_accts = st.session_state.get("ea_track_accounts_all") or []
        if "ea_setup_view" not in st.session_state:
            st.session_state["ea_setup_view"] = (
                "Charts" if st.session_state.get("ea_view_pref") == "Chart" else "Tables")
        if "ea_setup_density" not in st.session_state:
            st.session_state["ea_setup_density"] = (
                "Focus" if st.session_state.get("ea_density_pref") == "Focus"
                else "Everything")
        st.markdown("<div class='spacer-12'></div>", unsafe_allow_html=True)
        with st.container(border=True):
            st.markdown(
                "<div style='font-size:22px;font-weight:800;letter-spacing:-0.01em;"
                "margin:2px 0 2px;'>Make it yours</div>"
                "<div style='font-size:14px;color:#5b6270;margin-bottom:14px;'>"
                "Three taps — change any of them later from the header.</div>",
                unsafe_allow_html=True)
            if len(_s_accts) > 1:
                _cur = st.session_state.get("ea_track_account")
                st.markdown(
                    "<div style='font-size:11px;font-weight:700;letter-spacing:0.06em;"
                    "color:#64748b;margin:6px 0 4px;'>MAIN ACCOUNT &mdash; MONEY CARDS FOLLOW IT</div>",
                    unsafe_allow_html=True)
                st.selectbox("Main account", _s_accts,
                             index=_s_accts.index(_cur) if _cur in _s_accts else 0,
                             key="ea_setup_acct", label_visibility="collapsed")
            st.markdown(
                "<div style='font-size:11px;font-weight:700;letter-spacing:0.06em;"
                "color:#64748b;margin:12px 0 4px;'>YOUR NUMBERS AS</div>",
                unsafe_allow_html=True)
            st.markdown('<div class="ea-setupseg"></div>', unsafe_allow_html=True)
            st.radio("Numbers", ["Tables", "Charts"], key="ea_setup_view",
                     horizontal=True, label_visibility="collapsed")
            st.markdown(
                "<div style='font-size:11px;font-weight:700;letter-spacing:0.06em;"
                "color:#64748b;margin:12px 0 4px;'>HOW MUCH AT ONCE</div>",
                unsafe_allow_html=True)
            st.markdown('<div class="ea-setupseg"></div>', unsafe_allow_html=True)
            st.radio("Density", ["Everything", "Focus"], key="ea_setup_density",
                     horizontal=True, label_visibility="collapsed",
                     help="Focus opens with your track record and what needs work. "
                          "Everything keeps all six tabs.")
            st.markdown("<div class='spacer-12'></div>", unsafe_allow_html=True)
            if st.button("Start", key="ea_setup_go", type="primary"):
                _pick_acct = st.session_state.get("ea_setup_acct")
                if _pick_acct and _pick_acct in _s_accts:
                    st.session_state["ea_track_account"] = _pick_acct
                    st.session_state["ea_mplan_dirty"] = True
                _v = "Table" if st.session_state.get("ea_setup_view") == "Tables" else "Chart"
                if st.session_state.get("ea_view_pref") != _v:
                    st.session_state["ea_view_pref"] = _v
                    st.session_state["ea_view_dirty"] = True
                _dwant = ("Focus" if st.session_state.get("ea_setup_density") == "Focus"
                          else "All")
                st.session_state["ea_density_pref"] = _dwant
                st.session_state["ea_density_dirty"] = True
                st.session_state["ea_setup_done"] = True
                st.session_state["ea_setup_dirty"] = True
                _st_rerun()
        return

    # First-run walkthrough: right after the three-tap setup, once, dismissible.
    # Session-scoped on purpose — if they leave before dismissing, it's gone;
    # a nudge that nags is worse than no nudge.
    if st.session_state.get("ea_setup_done") and not st.session_state.get("ea_tour_done"):
        with st.container(border=True):
            st.markdown(
                "<div style='font-size:11px;font-weight:700;letter-spacing:0.06em;"
                "color:#64748b;margin-bottom:8px;'>WHERE TO LOOK FIRST</div>"
                "<div style='font-size:14px;line-height:2.0;color:#3b3f4d;'>"
                "<b>Your month vs your plan</b> — the first card, target and "
                "max-loss included.<br>"
                "<b>What needs work</b> — the Review tab prices your leaks in R; "
                "Focus mode (header) shows just these two.<br>"
                "<b>Auto-sync and template</b> — the &hellip; menu, top right."
                "</div>", unsafe_allow_html=True)
            if st.button("Got it", key="ea_tour_dismiss"):
                st.session_state["ea_tour_done"] = True
                _st_rerun()

    sel_inst, sel_em, sel_sess, date_range, sel_acct, sel_tot = render_filters(
        mobile, inst_opts, em_opts, sess_opts, date_mode_options, min_date, max_date,
        acct_opts, tot_opts, brand=_brand
    )

    # The Trade-Type coaching lives on the select itself (its help tooltip) —
    # a standing sentence above the nav was clutter in prime space.

    # Apply filters
    mask = pd.Series(True, index=df.index)
    if sel_inst != "All":
        mask &= (df["Instrument"] == sel_inst)
    if sel_em != "All":
        mask &= df["Entry Models List"].apply(
            lambda lst: sel_em in lst if isinstance(lst, list) else False
        )
    if sel_sess != "All":
        mask &= (df["Session Norm"] == sel_sess)
    if sel_acct not in ("All", "All executed") and "Account" in df.columns:
        if sel_acct in _real_accts:
            mask &= (df["Account"].astype(str).str.strip() == sel_acct)
        elif sel_acct == "Live and Demo":
            mask &= df["Account"].isin(["Live/Funded Capital", "Demo/Challenge"])
        else:
            _reverse = {v: k for k, v in _ACCT_MAP.items()}
            mask &= (df["Account"] == _reverse.get(sel_acct, sel_acct))

    _paper_mask = None
    if sel_tot in ("Executed", "Live money", "Real money only") \
            and "Type of Trade" in df.columns:
        _tt = df["Type of Trade"].astype(str).str.lower()
        _drop = (_tt.str.contains("forward") | _tt.str.contains("back test")
                 | _tt.str.contains("backtest") | _tt.str.contains("paper"))
        if sel_tot == "Live money":
            _drop = _drop | _tt.str.contains("challenge") | _tt.str.contains("combine") \
                | _tt.str.contains("evaluation")
        _paper_mask = ~_drop
        mask &= _paper_mask
    elif sel_tot not in ("All", "Executed", "Live money",
                         "Real money only") and "Type of Trade" in df.columns:
        mask &= df["Type of Trade"].astype(str).str.contains(re.escape(sel_tot), case=False, na=False)

    mask &= _apply_date_filter(df, date_range)

    # Filtered dataframe
    f = df[mask].copy()
    _rr_num = pd.to_numeric(f.get("Closed RR Num", pd.Series(index=f.index, dtype=float)),
                            errors="coerce")
    _rr_raw = pd.to_numeric(f.get("Closed RR", pd.Series(index=f.index, dtype=float)),
                            errors="coerce")
    f["PnL_from_RR"] = _rr_num.fillna(_rr_raw).fillna(0.0)
    stats = generate_overall_stats(f)

    # Calculate metrics
    if "Closed RR" in f.columns:
        wins_only = f[f["Outcome"] == "Win"]
        avg_rr_wins = float(wins_only["Closed RR"].mean()) if not wins_only.empty else 0.0
    else:
        avg_rr_wins = 0.0
    total_pnl_rr = float(f["PnL_from_RR"].sum())

    # Display KPIs
    st.markdown("<div class='spacer-12'></div>", unsafe_allow_html=True)

    # Render tabs with data
    try:
        # full-history views (month cards, records) must honour the money/paper
        # split too — otherwise the hero and the card below it disagree
        _df_hist = df[_paper_mask].copy() if _paper_mask is not None else df
        render_all_tabs(f, _df_hist, styler, show_light_table, hero_fn=None)
    except Exception:
        import traceback as _tb
        st.error("Something broke rendering this view — usually a template/column mismatch. "
                 "Screenshot the details below to report it.")
        with st.expander("Error details"):
            st.code(_tb.format_exc())
    st.markdown(
        "<div style='text-align:center;font-size:12px;color:#b3bac6;margin:34px 0 10px;'>"
        "Your trades live in your Notion — this server keeps only your account "
        "link (name, email, chosen template) and a short-lived cache for speed · "
        "Edge Analysis is a journal, not financial advice · Privacy &amp; terms in the ⋯ menu.</div>",
        unsafe_allow_html=True)
    try:
        from edge_analysis.ui.chat import render_chat_bubble
        render_chat_bubble(f)
    except Exception:
        pass
    if st.session_state.pop("ea_needs_fresh", False):
        # First paint came from the warm-boot copy — fetch fresh now that
        # the user is looking at something.
        _st_rerun()


# --------------------------------- Router -------------------------------------
def _detect_default_layout_index() -> int:
    """
    Detect default layout from query parameters.

    Returns:
        0 for desktop, 1 for mobile
    """
    layout_qp = (_get_query_param("layout") or "").lower()
    if layout_qp in {"m", "mobile", "phone"}:
        return 1
    return 0


# ----------------------------- WHOOP integration ------------------------------
WHOOP_STATE_PREFIX = "whoop"


def _whoop_client():
    """(client_id, client_secret, redirect_uri) for the WHOOP OAuth app."""
    return (
        _runtime_secret("WHOOP_CLIENT_ID"),
        _runtime_secret("WHOOP_CLIENT_SECRET"),
        _runtime_secret("WHOOP_REDIRECT_URI"),
    )


# ── WHOOP token: shared store in the user's Notion workspace ─────────────────
# One rotating refresh-token family shared by every device. Device localStorage
# stays as the fast path; Notion is the source of truth that survives any one
# device losing a rotation write.
_WHOOP_PAGE_TITLE = "Edge Analysis \u00b7 WHOOP link (do not delete)"
_NV = {"Notion-Version": "2022-06-28"}


def _whoop_notion_ids():
    """(page_id, block_id) of the shared store, cached per session."""
    tok = st.session_state.get(SessionKeys.USER_TOKEN)
    if not tok:
        return None, None
    if "whoop_np" in st.session_state:
        return st.session_state.get("whoop_np"), st.session_state.get("whoop_nb")
    hdr = {"Authorization": f"Bearer {tok}", **_NV}
    try:
        r = requests.post("https://api.notion.com/v1/search",
                          headers={**hdr, "Content-Type": "application/json"},
                          json={"query": "WHOOP link", "page_size": 5}, timeout=8)
        page_id = None
        for res in (r.json() or {}).get("results", []):
            try:
                title = res["properties"]["title"]["title"][0]["plain_text"]
            except Exception:
                continue
            if "WHOOP link" in title:
                page_id = res["id"]
                break
        block_id = None
        if page_id:
            rb = requests.get(f"https://api.notion.com/v1/blocks/{page_id}/children",
                              headers=hdr, timeout=8)
            for blk in (rb.json() or {}).get("results", []):
                if blk.get("type") == "paragraph":
                    block_id = blk["id"]
                    break
        st.session_state["whoop_np"] = page_id
        st.session_state["whoop_nb"] = block_id
        return page_id, block_id
    except Exception:
        return None, None


def _whoop_notion_read():
    page_id, block_id = _whoop_notion_ids()
    tok = st.session_state.get(SessionKeys.USER_TOKEN)
    if not (tok and block_id):
        return None
    try:
        r = requests.get(f"https://api.notion.com/v1/blocks/{block_id}",
                         headers={"Authorization": f"Bearer {tok}", **_NV}, timeout=8)
        txt = "".join(t.get("plain_text", "")
                      for t in (r.json() or {}).get("paragraph", {}).get("rich_text", []))
        blob = json.loads(txt) if txt.strip().startswith("{") else None
        return blob if isinstance(blob, dict) else None
    except Exception:
        return None


def _whoop_notion_write(blob: dict) -> None:
    tok = st.session_state.get(SessionKeys.USER_TOKEN)
    if not tok:
        return
    sig = (blob.get("rt") or "")[-12:]
    if st.session_state.get("whoop_nsig") == sig:
        return
    hdr = {"Authorization": f"Bearer {tok}", "Content-Type": "application/json", **_NV}
    payload_rt = [{"type": "text", "text": {"content": json.dumps(blob)}}]
    try:
        page_id, block_id = _whoop_notion_ids()
        if block_id:
            requests.patch(f"https://api.notion.com/v1/blocks/{block_id}",
                           headers=hdr, json={"paragraph": {"rich_text": payload_rt}}, timeout=8)
        else:
            dbid = st.session_state.get(SessionKeys.DB_ID)
            parent = None
            if dbid:
                rd = requests.get(f"https://api.notion.com/v1/databases/{dbid}",
                                  headers={"Authorization": f"Bearer {tok}", **_NV}, timeout=8)
                par = (rd.json() or {}).get("parent", {})
                if par.get("type") == "page_id":
                    parent = {"page_id": par["page_id"]}
            if not parent:
                return
            rc = requests.post("https://api.notion.com/v1/pages", headers=hdr, json={
                "parent": parent,
                "properties": {"title": {"title": [{"type": "text",
                               "text": {"content": _WHOOP_PAGE_TITLE}}]}},
                "children": [{"object": "block", "type": "paragraph",
                              "paragraph": {"rich_text": payload_rt}}],
            }, timeout=10)
            new_page = (rc.json() or {}).get("id")
            st.session_state["whoop_np"] = new_page
            st.session_state.pop("whoop_nb", None)
            if new_page:
                rb = requests.get(f"https://api.notion.com/v1/blocks/{new_page}/children",
                                  headers={"Authorization": f"Bearer {tok}", **_NV}, timeout=8)
                for blk in (rb.json() or {}).get("results", []):
                    if blk.get("type") == "paragraph":
                        st.session_state["whoop_nb"] = blk["id"]
                        break
        st.session_state["whoop_nsig"] = sig
    except Exception:
        pass


def _store_whoop_tokens(data: dict) -> None:
    """Store tokens from a WHOOP token/refresh response into session + device."""
    at = data.get("access_token")
    rt = data.get("refresh_token")
    if at:
        st.session_state["whoop_at"] = at
        st.session_state["whoop_at_exp"] = time.time() + int(data.get("expires_in", 3600)) - 120
    if rt:
        st.session_state["whoop_rt"] = rt


def _whoop_persist() -> None:
    """Save {refresh, access, expiry} to device + Notion. Write once per token
    signature, then verify once with a read-back — bounded reruns, self-healing
    if the write was lost, and no every-run component storm (that looped the app)."""
    at = st.session_state.get("whoop_at") or ""
    rt = st.session_state.get("whoop_rt") or ""
    exp = st.session_state.get("whoop_at_exp", 0)
    sig = f"{at[-10:]}|{rt[-10:]}|{int(exp)}"
    if (st.session_state.get("whoop_saved_sig") == sig
            and st.session_state.get("whoop_verified_sig") == sig):
        return
    if st.session_state.get("whoop_saved_sig") != sig:
        st.session_state["whoop_saved_sig"] = sig
        st.session_state["whoop_persist_tries"] = st.session_state.get("whoop_persist_tries", 0) + 1
        blob_d = {"rt": rt, "at": at, "exp": exp}
        _js_eval("localStorage.setItem('ea_whoop', " + json.dumps(json.dumps(blob_d)) + ")",
                 key="whoop_save")
        if rt:
            _whoop_notion_write(blob_d)
        return
    if st.session_state.get("whoop_persist_tries", 0) > 3:
        st.session_state["whoop_verified_sig"] = sig  # safety valve
        return
    raw = _js_eval("localStorage.getItem('ea_whoop') || ''", key="whoop_verify")
    if raw is None:
        return
    ok = False
    try:
        ok = (json.loads(raw).get("rt") or "")[-10:] == rt[-10:]
    except Exception:
        ok = not rt
    if ok:
        st.session_state["whoop_verified_sig"] = sig
        st.session_state["whoop_persist_tries"] = 0
    else:
        st.session_state.pop("whoop_saved_sig", None)


def _handle_whoop_logout() -> None:
    if not st.session_state.pop("whoop_logout", False):
        return
    for k in ("whoop_at", "whoop_rt", "whoop_at_exp",
              "whoop_saved_sig", "whoop_boot", "whoop_nsig", "whoop_verify"):
        st.session_state.pop(k, None)
    # drop per-token retry caps so a fresh Connect starts clean
    for k in [k for k in list(st.session_state.keys())
              if str(k).startswith("whoop_refresh_done_")]:
        st.session_state.pop(k, None)
    # blank the SHARED Notion store — otherwise adoption-first re-seeds the
    # dead connection on the very next run and Disconnect looks like it did
    # nothing (the bug Campbell hit)
    try:
        _whoop_notion_write({"rt": "", "at": "", "exp": 0})
    except Exception:
        pass
    st.session_state["whoop_logged_out"] = True
    st.session_state["whoop_nsig"] = None
    _js_eval("localStorage.removeItem('ea_whoop')", key="whoop_clear")
    _st_rerun()


def _handle_whoop_callback() -> None:
    """Process the WHOOP OAuth redirect (?code&state where state starts 'whoop')."""
    if _get_all_query_params().get("state"):
        st.session_state.pop("whoop_logged_out", None)
    qp = _get_all_query_params()
    code = qp.get("code")[0] if isinstance(qp.get("code"), list) else qp.get("code")
    rstate = qp.get("state")[0] if isinstance(qp.get("state"), list) else qp.get("state")
    if not code or not rstate or not str(rstate).startswith(WHOOP_STATE_PREFIX):
        return
    expected = st.session_state.get("whoop_state")
    if expected and rstate != expected:
        return
    cid, csec, ruri = _whoop_client()
    if not (cid and csec and ruri):
        return
    try:
        data = whoop.exchange_code(code, cid, csec, ruri)
        _store_whoop_tokens(data)
        st.session_state["whoop_just_connected"] = True
    except Exception as e:
        st.session_state["whoop_error"] = str(e)
    finally:
        _clear_query_params()
        _st_rerun()


def _whoop_load_blob(key: str):
    """Return device-stored WHOOP creds: None while pending, {} if none, else
    {rt, at, exp}. Tolerates the legacy bare-refresh-token format."""
    raw = _js_eval("localStorage.getItem('ea_whoop') || ''", key=key)
    if raw is None:
        return None
    if not raw:
        return {}
    try:
        blob = json.loads(raw)
    except Exception:
        return {"rt": raw}  # legacy: value was a bare refresh token
    return blob if isinstance(blob, dict) else {}


def _whoop_bootstrap() -> None:
    """Keep the WHOOP session alive across reloads. Reuses a still-valid access
    token from the device; only refreshes when it has actually expired; never
    drops the session on a transient error."""
    cid, csec, ruri = _whoop_client()
    if not (cid and csec and ruri):
        return
    if st.session_state.get("whoop_logged_out"):
        # Disconnected this session: skip token adoption/refresh, but still
        # build the consent URL so the Connect button renders.
        st.session_state["whoop_boot"] = "ready"
        if not st.session_state.get("whoop_auth_url"):
            _state = st.session_state.get("whoop_state")
            if not _state:
                _state = WHOOP_STATE_PREFIX + secrets.token_urlsafe(12)
                st.session_state["whoop_state"] = _state
            st.session_state["whoop_auth_url"] = whoop.authorize_url(cid, ruri, _state)
        return

    # Already have a live access token — make sure the device copy is current.
    if st.session_state.get("whoop_at") and time.time() < st.session_state.get("whoop_at_exp", 0):
        st.session_state["whoop_boot"] = "ready"
        _whoop_persist()
        return

    # No creds in this session yet: restore them from the device.
    if not st.session_state.get("whoop_rt") and not st.session_state.get("whoop_at"):
        blob = _whoop_load_blob("whoop_load")
        if blob is None:
            st.session_state["whoop_boot"] = "pending"  # still resolving — don't show Connect
            return
        if not blob:
            nb = _whoop_notion_read()
            if nb:
                blob = nb
        if blob.get("at"):
            st.session_state["whoop_at"] = blob["at"]
            st.session_state["whoop_at_exp"] = blob.get("exp", 0)
        if blob.get("rt"):
            st.session_state["whoop_rt"] = blob["rt"]

    # Restored access token still valid → done, no network call.
    if st.session_state.get("whoop_at") and time.time() < st.session_state.get("whoop_at_exp", 0):
        st.session_state["whoop_boot"] = "ready"
        _whoop_persist()
        return

    # Access token expired. FIRST adopt the newest shared credentials from the
    # Notion store — if another device refreshed within the hour, we reuse its
    # access token and never touch the (reuse-sensitive) refresh token at all.
    nb = _whoop_notion_read()
    if nb and nb.get("at") and time.time() < float(nb.get("exp", 0) or 0):
        st.session_state["whoop_at"] = nb["at"]
        st.session_state["whoop_at_exp"] = float(nb.get("exp", 0) or 0)
        if nb.get("rt"):
            st.session_state["whoop_rt"] = nb["rt"]
        st.session_state["whoop_boot"] = "ready"
        _whoop_persist()
        return
    # Genuinely need a refresh: always use the FRESHEST refresh token known
    # (Notion beats device beats session) — refreshing with a stale token can
    # revoke the whole family (WHOOP reuse detection).
    if nb and nb.get("rt"):
        st.session_state["whoop_rt"] = nb["rt"]
    rt = st.session_state.get("whoop_rt")
    _tried_key = "whoop_refresh_done_" + (rt or "")[-8:]
    if rt and st.session_state.get(_tried_key):
        # one attempt per token per session — a failing WHOOP API must never
        # turn every rerun into a 20s network stall (this looped the app)
        st.session_state["whoop_boot"] = "ready"
        return
    if rt:
        st.session_state[_tried_key] = True
        try:
            _store_whoop_tokens(whoop.refresh_tokens(rt, cid, csec))
            st.session_state["whoop_boot"] = "ready"
            _whoop_persist()
            return
        except requests.exceptions.HTTPError as e:
            code = getattr(e.response, "status_code", None)
            if code in (400, 401):
                # Refresh token rejected. Another tab may have rotated it —
                # re-read the device copy. The read is async: on the first run
                # it returns None, so stay in "pending" and finish the retry
                # on the next run instead of giving up straight away.
                blob = _whoop_load_blob("whoop_reload")
                if blob is None:
                    st.session_state["whoop_boot"] = "pending"
                    return
                nb = _whoop_notion_read()
                if nb and nb.get("rt") and nb.get("rt") != rt:
                    blob = nb
                newrt = (blob or {}).get("rt")
                if newrt and newrt != rt:
                    try:
                        _store_whoop_tokens(whoop.refresh_tokens(newrt, cid, csec))
                        st.session_state["whoop_boot"] = "ready"
                        _whoop_persist()
                        return
                    except Exception:
                        pass
                # Genuinely dead: drop the session copy AND the device copy so
                # a burned token is never restored again on the next reload.
                for k in ("whoop_at", "whoop_rt", "whoop_at_exp", "whoop_saved_sig"):
                    st.session_state.pop(k, None)
                _js_eval("localStorage.removeItem('ea_whoop')", key="whoop_clear_dead")
            # Non-4xx (network/5xx): keep tokens and try again next load.
        except Exception:
            pass  # transient — keep tokens

    # Genuinely not connected → prepare the consent URL.
    st.session_state["whoop_boot"] = "ready"
    if not st.session_state.get("whoop_at"):
        state = st.session_state.get("whoop_state")
        if not state:
            state = WHOOP_STATE_PREFIX + secrets.token_urlsafe(12)
            st.session_state["whoop_state"] = state
        st.session_state["whoop_auth_url"] = whoop.authorize_url(cid, ruri, state)

_DEMO_RESET_KEYS = ("ea_mplan_saved", "ea_filters_saved", "ea_m_tgt", "ea_m_stop",
                    "ea_m_cap", "ea_m_bal", "ea_m_bal_auto", "ea_m_bal_src",
                    "ea_plan_user_edited", "ea_filters_applied", "proj_ran",
                    "ea_chat", "ea_last_sync")


def _enter_demo() -> None:
    for _k in _DEMO_RESET_KEYS:
        st.session_state.pop(_k, None)
    for _k in [k for k in list(st.session_state) if str(k).startswith("filters_")]:
        st.session_state.pop(_k, None)
    st.session_state["ea_demo"] = True
    # a deliberate-looking plan, so the pills never show a degenerate auto seed
    st.session_state["ea_m_tgt"] = 5.0
    st.session_state["ea_m_stop"] = -6.0
    st.session_state["ea_m_cap"] = 20
    st.session_state[SessionKeys.NAV_TARGET] = PageNames.DASHBOARD


def _exit_demo() -> None:
    for _k in _DEMO_RESET_KEYS:
        st.session_state.pop(_k, None)
    for _k in [k for k in list(st.session_state) if str(k).startswith("filters_")]:
        st.session_state.pop(_k, None)
    st.session_state.pop("ea_demo", None)
    st.session_state["ea_demo_exited"] = True   # stops ?demo=1 re-entering forever
    try:
        if "demo" in st.query_params:
            del st.query_params["demo"]
    except Exception:
        pass
    st.session_state[SessionKeys.NAV_TARGET] = PageNames.CONNECT


@st.cache_data(show_spinner=False, ttl=3600)
def _demo_frame(_day: str):
    from edge_analysis.demo import demo_df
    return demo_df()


def main() -> None:
    """Main application entry point."""
    # WHOOP OAuth: handle logout + redirect before the Notion login gate
    _handle_whoop_logout()
    _handle_whoop_callback()

    # Demo mode: explore with simulated data, no account needed
    if str(_get_query_param("demo") or "").lower() in ("1", "true", "yes") \
            and not st.session_state.get("ea_demo") \
            and not st.session_state.get("ea_demo_exited"):
        _enter_demo()
    _demo = bool(st.session_state.get("ea_demo"))

    # Require login (the demo skips it by design)
    if not _demo:
        _require_notion_login()

    # Theme preference: restore from this device, persist changes, apply overlay
    _prefs = _prefs_blob()
    if "ea_view_pref" not in st.session_state:
        _saved_view = _prefs.get("v") or ""
        if _saved_view in ("Chart", "Table"):
            st.session_state["ea_view_pref"] = _saved_view
    if st.session_state.pop("ea_view_dirty", False):
        _js_eval("localStorage.setItem('ea_view', "
                 + json.dumps(st.session_state.get("ea_view_pref", "Chart")) + ")",
                 key="ea_view_save")
    if "ea_filters_saved" not in st.session_state and not _demo:
        _raw_f = _prefs.get("f") or ""
        if _raw_f:
            try:
                _fsaved = json.loads(_raw_f) or {}
            except ValueError:
                _fsaved = {}
            if isinstance(_fsaved, dict) and _fsaved:
                # applied by render_filters BEFORE its widgets exist
                st.session_state["ea_filters_saved"] = {
                    str(k): v for k, v in _fsaved.items()
                    if str(k).startswith("filters_") and isinstance(v, str)}
    if st.session_state.pop("ea_filters_dirty", False) and not _demo:
        _fp = {_k: st.session_state.get(_k)
               for _k in ("filters_inst_select", "filters_em_select", "filters_sess_select",
                          "filters_acct_select", "filters_tot_select", "filters_date_mode")
               if isinstance(st.session_state.get(_k), str)}
        _js_eval("localStorage.setItem('ea_filters', " + json.dumps(json.dumps(_fp)) + ")",
                 key="ea_filters_save")
    if "ea_mplan_saved" not in st.session_state and not _demo:
        _raw_plan = _prefs.get("p") or ""
        if _raw_plan:
            try:
                _pb = json.loads(_raw_plan) or {}
            except ValueError:
                _pb = {}
            if isinstance(_pb, dict) and "t" in _pb:
                # applied by _perf_settings BEFORE the plan sliders exist —
                # writing a widget key from here is rejected by Streamlit
                st.session_state["ea_mplan_saved"] = _pb
                if _pb.get("a") and "ea_track_account" not in st.session_state:
                    st.session_state["ea_track_account"] = str(_pb["a"])
    if st.session_state.pop("ea_mplan_dirty", False) and not _demo:
        # Overlay-only save: start from the last saved plan and update just the
        # keys present in session. Rebuilding from defaults once wrote a phantom
        # $10,000 balance anchor when setup saved before the plan card seeded.
        _pb = dict(st.session_state.get("ea_mplan_saved") or {})
        if "ea_m_tgt" in st.session_state:
            _pb["t"] = float(st.session_state["ea_m_tgt"])
        if "ea_m_stop" in st.session_state:
            _pb["s"] = float(st.session_state["ea_m_stop"])
        if "ea_m_cap" in st.session_state:
            _pb["c"] = int(st.session_state["ea_m_cap"])
        # b/d is a HAND-TYPED anchor for people without a synced balance.
        # When the journal stamps the balance, the journal is the source of
        # truth — never persist it as an anchor (and heal any phantom one).
        if st.session_state.get("ea_m_bal_src") == "from your journal":
            _pb.pop("b", None)
            _pb.pop("d", None)
        elif "ea_m_bal" in st.session_state:
            _pb["b"] = float(st.session_state["ea_m_bal"])
            _pb["d"] = str(st.session_state.get("ea_bal_asof") or "")
        if "ea_m_risk" in st.session_state:
            _pb["r"] = float(st.session_state["ea_m_risk"])
        if st.session_state.get("ea_track_account"):
            _pb["a"] = str(st.session_state["ea_track_account"])
        st.session_state["ea_mplan_saved"] = dict(_pb)
        _js_eval("localStorage.setItem('ea_mplan', " + json.dumps(json.dumps(_pb)) + ")",
                 key="ea_mplan_save")
    if st.session_state.pop("ea_mplan_clear", False):
        _js_eval("localStorage.removeItem('ea_mplan')", key="ea_mplan_clear_js")
    if "ea_density_pref" not in st.session_state:
        _saved_density = _prefs.get("d") or ""
        if _saved_density in ("Focus", "All"):
            st.session_state["ea_density_pref"] = _saved_density
    st.session_state.pop("ea_density_dirty", False)
    # Idempotent persistence: one constant-key component always writes the
    # CURRENT pref. A transient dirty-save component proved to re-fire during
    # boot replays and could stamp a stale value; re-writing the truth every
    # run makes any replay harmless by construction.
    _dcur = st.session_state.get("ea_density_pref")
    if _dcur in ("Focus", "All"):
        _js_eval("localStorage.setItem('ea_density', " + json.dumps(_dcur) + ")",
                 key="ea_density_sync")
    if st.session_state.pop("ea_setup_dirty", False):
        _js_eval("localStorage.setItem('ea_setup', \"1\")", key="ea_setup_save")
    if "ea_theme_pref" not in st.session_state:
        _saved_theme = _prefs.get("t") or ""
        if _saved_theme in ("dark", "light"):
            st.session_state["ea_theme_pref"] = _saved_theme
    if st.session_state.pop("ea_theme_dirty", False):
        _js_eval("localStorage.setItem('ea_theme', "
                 + json.dumps(st.session_state.get("ea_theme_pref", "light")) + ")",
                 key="ea_theme_save")
    if st.session_state.get("ea_theme_pref") == "dark":
        inject_dark_overlay()

    if not _demo:
        # Recover the template choice from this device if the server forgot it
        _recover_db_from_device()
        # Remember this login on the device (phones especially)
        _sync_device_auth()
        # WHOOP: restore/refresh token and prepare connect URL
        _whoop_bootstrap()

    # Initialize session state from query params
    if SessionKeys.LAYOUT not in st.session_state:
        st.session_state[SessionKeys.LAYOUT] = (
            "Desktop Layout" if _detect_default_layout_index() == 0 else "Mobile Layout"
        )

    if SessionKeys.NAV_PAGE not in st.session_state:
        qp_page = (_get_query_param("page") or "").lower()
        if qp_page.startswith("connect"):
            st.session_state[SessionKeys.NAV_PAGE] = PageNames.CONNECT
        else:
            st.session_state[SessionKeys.NAV_PAGE] = PageNames.DASHBOARD

    # Handle navigation target (from button clicks)
    if SessionKeys.NAV_TARGET in st.session_state:
        st.session_state[SessionKeys.NAV_PAGE] = st.session_state.pop(SessionKeys.NAV_TARGET)

    # Auto-switch to mobile layout on phones (once per session, unless the
    # visitor explicitly asked for a layout in the URL). Detection uses the
    # user agent: window.innerWidth is useless here because the JS helper runs
    # inside a 0-width iframe.
    if not st.session_state.get("ea_layout_autoset") and not _get_query_param("layout"):
        _ua = _js_eval("navigator.userAgent || ''", key="ea_ua")
        if _ua is not None:
            st.session_state["ea_layout_autoset"] = True
            try:
                if re.search(r"Mobi|Android|iPhone|iPad", str(_ua)) and                         st.session_state.get(SessionKeys.LAYOUT) != "Mobile Layout":
                    st.session_state[SessionKeys.LAYOUT] = "Mobile Layout"
                    _st_rerun()
            except Exception:
                pass

    # Determine layout mode
    layout_choice_ss = st.session_state.get(SessionKeys.LAYOUT, "Desktop Layout")
    layout_mode = "mobile" if layout_choice_ss == "Mobile Layout" else "desktop"
    st.session_state["layout_index"] = 1 if layout_mode == "mobile" else 0
    st.session_state["layout_mode"] = layout_mode


    # Route to appropriate page
    if st.session_state.get(SessionKeys.NAV_PAGE) == PageNames.CONNECT:
        render_connect_page(mobile=(layout_mode == "mobile"))
    else:
        render_dashboard(mobile=(layout_mode == "mobile"))


if __name__ == "__main__":
    main()
