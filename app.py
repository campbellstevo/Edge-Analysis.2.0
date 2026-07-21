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
    CONNECT = "Change Template"


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
    except Exception as e:
        st.error(f"OAuth token exchange failed: {e}")
    finally:
        st.session_state.pop(SessionKeys.OAUTH_PENDING, None)
        _clear_query_params()
        _st_rerun()

    return True


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
        st.markdown('<div class="ea-title">Change Template</div>', unsafe_allow_html=True)
        st.markdown('<div class="ea-card">', unsafe_allow_html=True)

        # Step 1: OAuth
        st.markdown('<div class="ea-step">Step 1 — Connect with Notion (OAuth)</div>', unsafe_allow_html=True)
        st.markdown('<div class="ea-help">Use OAuth to authorize securely. This token is stored for your session only.</div>', unsafe_allow_html=True)

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
            if st.button("Finalize sign-in", key="btn_finalize_oauth"):
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

        # Step 2: Database
        st.markdown('<div class="ea-step">Step 2 — Paste your Notion database link</div>', unsafe_allow_html=True)

        oauth_token = st.session_state.get(SessionKeys.OAUTH_TOKEN)
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
                        st.error(
                            "Notion can't find that database (404). Ensure it's a database "
                            "(not a page) and the ID/link is correct."
                        )
                    else:
                        st.error(f"Couldn't verify the database. {info}")

        st.markdown('<div class="ea-divider"></div>', unsafe_allow_html=True)
        if st.button("Return to Dashboard", key="btn_return_dashboard_connect", use_container_width=True):
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

    st.markdown(
        f"""
        <div class="ea-signin-wrap">
          <div class="ea-signin-card">
            {logo_html}
            <p>Connect your trading journal to unlock insights.</p>
            <a href="{auth_url}" class="ea-link-btn">Sign in with Notion</a>
            <div class="ea-login-note">
              🔒 Your Notion credentials are never stored. Authentication is handled securely via Notion's OAuth system.
            </div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
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
    if not saved:
        return False
    try:
        rec = json.loads(saved)
    except Exception:
        return False
    if not (isinstance(rec, dict) and rec.get("t")):
        return False
    _complete_login_with_token(rec["t"])
    dbid = str(rec.get("d") or "")
    if dbid and _validate_dbid(dbid.replace("-", "")):
        st.session_state[SessionKeys.DB_ID] = dbid
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
    if _restore_device_auth():
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

    _sync = st.session_state.get("ea_last_sync")
    _status = "Live · Notion connected" if (token and dbid) else "Not connected"
    if token and dbid and _sync:
        _status += f" · synced {_sync}"
    inject_header_bar(_status, bool(token and dbid))
    st.session_state["_ea_connected"] = bool(token and dbid)

    with st.spinner("Fetching trades from Notion…"):
        df = load_live_df(token, dbid)

    if token and dbid:
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
        st.info("No data yet. Add trades, adjust filters, or check credentials.")
        return

    # Prepare filter options
    instruments = sorted(df["Instrument"].dropna().unique().tolist())
    instruments = [i for i in instruments if i != "DUMMY ROW"]
    inst_opts = ["All"] + instruments
    em_opts = ["All"] + MODEL_SET
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

    if "Date" in df.columns:
        min_date = df["Date"].min().date()
        max_date = df["Date"].max().date()
    else:
        from datetime import date as _date
        min_date = max_date = _date.today()

    # Render filters (imported from filters module)
    sel_inst, sel_em, sel_sess, date_range, sel_acct, sel_tot = render_filters(
        mobile, inst_opts, em_opts, sess_opts, date_mode_options, min_date, max_date, acct_opts, tot_opts
    )

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
    if sel_acct != "All":
        if "Account" in df.columns:
            if sel_acct == "Live and Demo":
                mask &= df["Account"].isin(["Live/Funded Capital", "Demo/Challenge"])
            else:
                _reverse = {v: k for k, v in _ACCT_MAP.items()}
                mask &= (df["Account"] == _reverse.get(sel_acct, sel_acct))

    if sel_tot != "All" and "Type of Trade" in df.columns:
        mask &= df["Type of Trade"].astype(str).str.contains(re.escape(sel_tot), case=False, na=False)

    mask &= _apply_date_filter(df, date_range)

    # Filtered dataframe
    f = df[mask].copy()
    f["PnL_from_RR"] = f.get("Closed RR", pd.Series(0.0, index=f.index)).fillna(0.0)
    stats = generate_overall_stats(f)

    # Calculate metrics
    if "Closed RR" in f.columns:
        wins_only = f[f["Outcome"] == "Win"]
        avg_rr_wins = float(wins_only["Closed RR"].mean()) if not wins_only.empty else 0.0
    else:
        avg_rr_wins = 0.0
    total_pnl_rr = float(f["PnL_from_RR"].sum())

    # Display KPIs
    def _hero_block():
        # ── Hero band: net result + sparkline + stat chips (one card) ────────────
        spark = ""
        net_col = "#16a34a" if total_pnl_rr >= 0 else "#ef4444"
        _wk_chip = ""
        if "Date" in f.columns:
            _dser = pd.to_datetime(f["Date"], errors="coerce")
            _wk_r = float(f.loc[_dser >= (pd.Timestamp.now() - pd.Timedelta(days=7)), "PnL_from_RR"].sum())
            _wc = "#16a34a" if _wk_r >= 0 else "#ef4444"
            _arrow = "▲" if _wk_r >= 0 else "▼"
            _wk_chip = (f"<span style='font-size:14px;font-weight:700;color:{_wc};"
                        f"margin-left:12px;vertical-align:middle;'>{_arrow} {_wk_r:+.1f}R this week</span>")
        chips = "".join(
            f"<div style='flex:1;min-width:132px;background:#f8f9fc;border-radius:10px;padding:10px 12px;'>"
            f"<div style='font-size:11px;font-weight:600;letter-spacing:0.06em;color:#94a3b8;'>{lab}</div>"
            f"<div style='font-size:19px;font-weight:800;color:{col};margin-top:2px;'>{val}</div></div>"
            for lab, val, col in [
                ("TRADES", f"{stats['total']}", "#0f172a"),
                ("WIN", f"{stats['win_rate']:.0f}%", "#0f172a"),
                ("BREAK-EVEN", f"{stats['be_rate']:.0f}%", "#0f172a"),
                ("LOSS", f"{stats['loss_rate']:.0f}%", "#0f172a"),
                ("AVG WIN", f"{avg_rr_wins:.2f}R", "#4800ff"),
            ]
        )
        st.markdown(
            f"<div style='background:#ffffff;border:1px solid rgba(0,0,0,0.06);border-radius:12px;"
            f"padding:20px 22px;box-shadow:0 2px 12px rgba(0,0,0,0.05);margin:2px 0 14px;'>"
            f"<div style='font-size:12px;font-weight:600;letter-spacing:0.08em;color:#94a3b8;'>NET RESULT</div>"
            f"<div style='font-size:34px;font-weight:800;color:{net_col};line-height:1.15;'>{total_pnl_rr:+,.1f}R{_wk_chip}</div>"
            f"{spark}"
            f"<div style='display:flex;gap:10px;margin-top:14px;flex-wrap:wrap;'>{chips}</div>"
            f"</div>",
            unsafe_allow_html=True,
        )
        try:
            _now = pd.Timestamp.now()
            if _now.dayofweek <= 2 and "Date" in f.columns:
                _d = pd.to_datetime(f["Date"], errors="coerce")
                _mon = (_now - pd.Timedelta(days=int(_now.dayofweek))).normalize()
                _lw = f[(_d >= _mon - pd.Timedelta(days=7)) & (_d < _mon)]
                if len(_lw):
                    _lr = float(_lw["PnL_from_RR"].sum())
                    _lc = "#16a34a" if _lr >= 0 else "#ef4444"
                    st.markdown(
                        f"<div style='display:flex;align-items:center;gap:10px;background:#ffffff;"
                        f"border:1px solid rgba(0,0,0,0.06);border-radius:12px;padding:10px 16px;"
                        f"box-shadow:0 2px 10px rgba(0,0,0,0.04);margin:0 0 12px;font-size:14px;color:#334155;'>"
                        f"<span style='font-weight:700;'>Last week wrapped:</span>"
                        f"<span style='font-weight:800;color:{_lc};'>{_lr:+.1f}R</span>"
                        f"<span style='color:#64748b;'>over {len(_lw)} trade{'s' if len(_lw) != 1 else ''} "
                        f"— full breakdown in the Review tab.</span></div>",
                        unsafe_allow_html=True)
        except Exception:
            pass

    st.markdown("<div class='spacer-12'></div>", unsafe_allow_html=True)

    # Render tabs with data
    render_all_tabs(f, df, styler, show_light_table, hero_fn=_hero_block)


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
    """Save {refresh, access, expiry} to this device so the session survives
    reloads, reboots and Community-Cloud sleep — a still-valid access token can
    then be reused with no (rotation-prone) refresh call at all."""
    at = st.session_state.get("whoop_at") or ""
    rt = st.session_state.get("whoop_rt") or ""
    exp = st.session_state.get("whoop_at_exp", 0)
    # No dedupe gate: re-render the write component EVERY run. If a rerun
    # killed the component before its localStorage.setItem executed, the next
    # run re-issues it — a rotated refresh token can never be lost again.
    blob_d = {"rt": rt, "at": at, "exp": exp}
    blob = json.dumps(blob_d)
    _js_eval("localStorage.setItem('ea_whoop', " + json.dumps(blob) + ")",
             key="whoop_save")
    if rt:
        _whoop_notion_write(blob_d)


def _handle_whoop_logout() -> None:
    if not st.session_state.pop("whoop_logout", False):
        return
    for k in ("whoop_at", "whoop_rt", "whoop_at_exp", "whoop_state",
              "whoop_auth_url", "whoop_saved_sig", "whoop_boot"):
        st.session_state.pop(k, None)
    _js_eval("localStorage.removeItem('ea_whoop')", key="whoop_clear")
    _st_rerun()


def _handle_whoop_callback() -> None:
    """Process the WHOOP OAuth redirect (?code&state where state starts 'whoop')."""
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

    # Access token expired → refresh (once per run) using the refresh token.
    rt = st.session_state.get("whoop_rt")
    if rt:
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

def main() -> None:
    """Main application entry point."""
    # WHOOP OAuth: handle logout + redirect before the Notion login gate
    _handle_whoop_logout()
    _handle_whoop_callback()

    # Require login
    _require_notion_login()

    # Theme preference: restore from this device, persist changes, apply overlay
    if "ea_view_pref" not in st.session_state:
        _saved_view = _js_eval("localStorage.getItem('ea_view') || ''", key="ea_view_load")
        if _saved_view in ("Chart", "Table"):
            st.session_state["ea_view_pref"] = _saved_view
    if st.session_state.pop("ea_view_dirty", False):
        _js_eval("localStorage.setItem('ea_view', "
                 + json.dumps(st.session_state.get("ea_view_pref", "Chart")) + ")",
                 key="ea_view_save")
    if "ea_theme_pref" not in st.session_state:
        _saved_theme = _js_eval("localStorage.getItem('ea_theme') || ''", key="ea_theme_load")
        if _saved_theme in ("dark", "light"):
            st.session_state["ea_theme_pref"] = _saved_theme
    if st.session_state.pop("ea_theme_dirty", False):
        _js_eval("localStorage.setItem('ea_theme', "
                 + json.dumps(st.session_state.get("ea_theme_pref", "light")) + ")",
                 key="ea_theme_save")
    if st.session_state.get("ea_theme_pref") == "dark":
        inject_dark_overlay()

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
