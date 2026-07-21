"""
Filter controls module for Edge Analysis.

This module contains helper functions for rendering the various filter
controls used in the dashboard. Extracting these functions into a
separate module helps keep the main application entry point cleaner.
"""

from __future__ import annotations

from typing import Optional, Union, Tuple
from datetime import date as DateType

import streamlit as st
import pandas as pd

# Replicate SessionKeys and PageNames here to avoid circular imports.

class SessionKeys:
    """Session state key constants (replicated from the main app)."""
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
    """Navigation page names (replicated from the main app)."""
    DASHBOARD = "Dashboard"
    CONNECT = "Change Template"


# Type alias for date range selection
DateRange = Union[DateType, Tuple[DateType, DateType]]


def apply_date_filter(df: pd.DataFrame, date_range: Optional[DateRange]) -> pd.Series:
    """
    Apply a date range filter to a dataframe and return a boolean mask.

    Args:
        df: DataFrame with a 'Date' column.
        date_range: Either a single date or a tuple (start, end) indicating
            inclusive start and exclusive end dates.

    Returns:
        A boolean Series mask indexing the dataframe.
    """
    if date_range is None:
        return pd.Series(True, index=df.index)

    if isinstance(date_range, tuple) and len(date_range) == 2:
        start, end = date_range
        return df["Date"].dt.date.between(start, end)

    # Single date selection
    return df["Date"].dt.date == date_range


def render_filters(
    mobile: bool,
    inst_opts: list,
    em_opts: list,
    sess_opts: list,
    date_mode_options: list,
    min_date: DateType,
    max_date: DateType,
    acct_opts: list | None = None,
    tot_opts: list | None = None,
) -> Tuple[str, str, str, Optional[DateRange], str]:
    """
    Render filter controls for both desktop and mobile layouts.

    This function mirrors the original `_render_filters` but avoids
    dependencies on the main application by reproducing the necessary
    session key and page name constants locally.

    Args:
        mobile: Whether to render in mobile mode.
        inst_opts: List of instrument options.
        em_opts: List of entry model options.
        sess_opts: List of session options.
        date_mode_options: List of date mode options (e.g., "All", "Custom").
        min_date: Minimum date allowed for the date picker.
        max_date: Maximum date allowed for the date picker.

    Returns:
        A tuple containing the selected instrument, selected entry model,
        selected session, an optional date range (single date or tuple),
        and the selected account.
    """
    if acct_opts is None:
        acct_opts = ["All"]
    if tot_opts is None:
        tot_opts = ["All"]

    def _inst_label(v: str) -> str:
        return "GOLD" if v == "Gold" else v

    _active = sum(1 for k in ["filters_inst_select", "filters_sess_select",
                              "filters_em_select", "filters_tot_select"]
                  if st.session_state.get(k, "All") != "All")
    if st.session_state.get("filters_date_mode", "All") != "All":
        _active += 1
    _flabel = f"Settings · {_active} filters on" if _active else "Settings"
    try:
        flt = st.popover(_flabel, use_container_width=False)
    except Exception:
        flt = st.expander(_flabel)
    with flt:
        c1, c2 = st.columns(2, gap="small")
        with c1:
            sel_inst = st.selectbox(
                "Instrument",
                inst_opts,
                index=inst_opts.index(st.session_state.get("filters_inst_select", "All"))
                if st.session_state.get("filters_inst_select", "All") in inst_opts
                else 0,
                format_func=_inst_label,
                key="filters_inst_select",
            )
            sel_em = st.selectbox(
                "Entry Model",
                em_opts,
                index=em_opts.index(st.session_state.get("filters_em_select", "All"))
                if st.session_state.get("filters_em_select", "All") in em_opts
                else 0,
                key="filters_em_select",
            )
        with c2:
            sel_sess = st.selectbox(
                "Session",
                sess_opts,
                index=sess_opts.index(st.session_state.get("filters_sess_select", "All"))
                if st.session_state.get("filters_sess_select", "All") in sess_opts
                else 0,
                key="filters_sess_select",
            )
            sel_acct = "All"
        c3, c4 = st.columns(2, gap="small")
        sel_tot = "All"
        with c3:
            current_mode = st.session_state.get("filters_date_mode", "All")
            if current_mode not in date_mode_options:
                current_mode = "All"
            date_mode = st.selectbox(
                "Date range",
                date_mode_options,
                index=date_mode_options.index(current_mode),
                key="filters_date_mode",
            )
        with c4:
            # one box, two journals: MT5 templates filter by Trade Type,
            # the SR template filters by Account
            _has_tot = bool(tot_opts) and len(tot_opts) > 1
            _has_acct = (not _has_tot) and bool(acct_opts) and len(acct_opts) > 1
            if _has_tot:
                _cur_tot = st.session_state.get("filters_tot_select", "All")
                if _cur_tot not in tot_opts:
                    _cur_tot = "All"
                sel_tot = st.selectbox(
                    "Trade Type",
                    tot_opts,
                    index=tot_opts.index(_cur_tot),
                    key="filters_tot_select",
                )
            elif _has_acct:
                _cur_acct = st.session_state.get("filters_acct_select", "All")
                if _cur_acct not in acct_opts:
                    _cur_acct = "All"
                sel_acct = st.selectbox(
                    "Account",
                    acct_opts,
                    index=acct_opts.index(_cur_acct),
                    key="filters_acct_select",
                )
        date_range: Optional[DateRange] = None
        if date_mode == "Last 30 days":
            date_range = (max_date - __import__("datetime").timedelta(days=29), max_date)
        elif date_mode == "Last 90 days":
            date_range = (max_date - __import__("datetime").timedelta(days=89), max_date)
        elif date_mode == "This year":
            date_range = (max_date.replace(month=1, day=1), max_date)
        elif date_mode == "Custom":
            date_range = st.date_input(
                "Custom dates",
                value=st.session_state.get("filters_date_range", (min_date, max_date)),
                key="filters_date_range",
            )
        _theme_label = ("Light theme" if st.session_state.get("ea_theme_pref") == "dark"
                        else "Dark theme")
        _view_label = ("Show tables by default"
                       if st.session_state.get("ea_view_pref") == "Chart"
                       else "Show charts by default")
        _menu_opts = [PageNames.DASHBOARD, PageNames.CONNECT, "Getting started",
                      "Refresh data", "Sign in on iPhone", "What the stats mean",
                      _theme_label, _view_label]

        def _menu_cb():
            choice = st.session_state.get("ea_menu")
            page_now = st.session_state.get(SessionKeys.NAV_PAGE, PageNames.DASHBOARD)
            if choice in (PageNames.DASHBOARD, PageNames.CONNECT):
                st.session_state[SessionKeys.NAV_TARGET] = choice
                st.session_state["ea_show_qr"] = False
            elif choice == "Refresh data":
                try:
                    st.cache_data.clear()
                except Exception:
                    pass
                st.session_state.pop("ea_last_sync", None)
                st.session_state["ea_menu"] = page_now
            elif choice == "Sign in on iPhone":
                st.session_state["ea_show_qr"] = True
                st.session_state["ea_menu"] = page_now
            elif choice == "What the stats mean":
                st.session_state["ea_show_help"] = True
                st.session_state["ea_menu"] = page_now
            elif choice == "Getting started":
                st.session_state["ea_show_setup"] = True
                st.session_state["ea_menu"] = page_now
            elif choice in ("Show tables by default", "Show charts by default"):
                cur = st.session_state.get("ea_view_pref", "Table")
                st.session_state["ea_view_pref"] = "Chart" if cur != "Chart" else "Table"
                st.session_state["ea_view_dirty"] = True
                for k in list(st.session_state.keys()):
                    if str(k).endswith("_flip"):
                        st.session_state.pop(k, None)
                st.session_state["ea_menu"] = page_now
            else:  # theme toggle
                cur = st.session_state.get("ea_theme_pref", "light")
                st.session_state["ea_theme_pref"] = "dark" if cur != "dark" else "light"
                st.session_state["ea_theme_dirty"] = True
                st.session_state["ea_menu"] = page_now

        if st.session_state.get("ea_menu") not in _menu_opts:
            _cur_page = st.session_state.get(SessionKeys.NAV_PAGE, PageNames.DASHBOARD)
            st.session_state["ea_menu"] = (_cur_page if _cur_page in _menu_opts
                                           else PageNames.DASHBOARD)
        st.selectbox("Page", _menu_opts, key="ea_menu", on_change=_menu_cb)
    if st.session_state.pop("ea_show_qr", False):
        if _qr_dialog is not None:
            _qr_dialog()
        else:
            with st.expander("Sign in on your phone", expanded=True):
                _phone_qr_body()
    if st.session_state.pop("ea_show_help", False):
        if _help_dialog is not None:
            _help_dialog()
        else:
            with st.expander("What the stats mean", expanded=True):
                _help_body()
    if st.session_state.pop("ea_show_setup", False):
        if _setup_dialog is not None:
            _setup_dialog()
        else:
            with st.expander("Getting started", expanded=True):
                _setup_body()

    return sel_inst, sel_em, sel_sess, date_range, sel_acct, sel_tot


def _phone_qr_body() -> None:
    """Phone handoff: scan once, phone stays signed in (device-persistent login)."""
    token = (
        st.session_state.get(SessionKeys.USER_TOKEN)
        or st.session_state.get(SessionKeys.OAUTH_TOKEN)
    )
    if not token:
        st.caption("Sign in on this computer first, then come back here.")
        return
    from urllib.parse import urlencode
    params = {"notion_token": token}
    dbid = st.session_state.get(SessionKeys.DB_ID)
    if dbid:
        params["database_id"] = dbid
    url = "https://edge-analysis2.streamlit.app/?" + urlencode(params)
    qr_html = ""
    try:
        import qrcode
        import qrcode.image.svg as _qsvg
        _svg = qrcode.make(url, image_factory=_qsvg.SvgPathImage).to_string().decode("utf-8")
        qr_html = _svg.replace(
            "<svg",
            "<svg style='width:210px;height:210px;background:#fff;padding:10px;"
            "border:1px solid rgba(0,0,0,0.08);border-radius:14px;'", 1)
    except Exception:
        pass
    st.markdown(
        "<div style='text-align:center;padding:4px 0 2px;'>" + qr_html + "</div>"
        "<div style='font-size:14px;color:#334155;line-height:2;padding:10px 6px 2px;'>"
        "<b>1.</b> Point your phone camera at the code<br>"
        "<b>2.</b> Open the link — the dashboard signs in by itself<br>"
        "<b>3.</b> Add it to your home screen and you're set"
        "</div>",
        unsafe_allow_html=True,
    )
    if not qr_html:
        st.code(url, language=None)
    st.caption("This code signs anyone in to your dashboard — don't share or screenshot it.")


try:
    @st.dialog("Sign in on your phone")
    def _qr_dialog():
        _phone_qr_body()
except Exception:
    _qr_dialog = None


def _help_body() -> None:
    st.markdown(
        "- **R** — your risk unit. +2R = twice what you risked.\n"
        "- **Win / BE / Loss %** — trades that made money, scratched, or lost.\n"
        "- **Expectancy** — average R per trade. Positive = profitable over time.\n"
        "- **MFE / MAE** — how far a trade went for / against you before closing.\n"
        "- **Give-back** — profit shown (MFE) but not banked.\n"
        "- **Profit factor** — gross wins ÷ gross losses. Above 1 = profitable.")


try:
    @st.dialog("What the stats mean")
    def _help_dialog():
        _help_body()
except Exception:
    _help_dialog = None


def _setup_body() -> None:
    st.markdown(
        "**1. Get the trading journal template**\n"
        "Duplicate the Edge Analysis MT5 journal template into your own Notion workspace. "
        "Every column the dashboard reads is already set up in it.\n\n"
        "**2. Connect it here**\n"
        "Settings → Page → *Change Template*, sign in with Notion, and pick the journal "
        "you just duplicated. Your data appears within seconds.\n\n"
        "**3. Automatic MT5 import (optional)**\n"
        "If you trade on MetaTrader 5, the sync tool fills your journal automatically after "
        "every trade — R multiples, MFE/MAE, timings, costs. Without it you can still log "
        "trades in Notion by hand.\n\n"
        "**4. Put it on your phone**\n"
        "Settings → Page → *Sign in on iPhone*, scan the code once, add to home screen. "
        "Stays signed in.\n\n"
        "**5. Make it yours**\n"
        "Log the manual fields (A+ Setup, Conviction, Mental State, Mistake) — the Plan, "
        "Psychology and Refinements tabs get sharper with every tagged trade."
    )
    st.caption("Analytics on your own journal — not financial advice.")


try:
    @st.dialog("Getting started")
    def _setup_dialog():
        _setup_body()
except Exception:
    _setup_dialog = None
