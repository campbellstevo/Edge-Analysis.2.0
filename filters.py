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

    def _filters_dirty():
        st.session_state["ea_filters_dirty"] = True

    # Apply the saved filter set once per session, before these widgets exist
    _fsaved = st.session_state.get("ea_filters_saved")
    if _fsaved and not st.session_state.get("ea_filters_applied"):
        st.session_state["ea_filters_applied"] = True
        for _k, _opts in (("filters_inst_select", inst_opts), ("filters_em_select", em_opts),
                          ("filters_sess_select", sess_opts), ("filters_acct_select", acct_opts),
                          ("filters_tot_select", tot_opts),
                          ("filters_date_mode", date_mode_options)):
            _v = _fsaved.get(_k)
            if _v is not None and _v in (_opts or []):
                st.session_state[_k] = _v

    # A restored value that no longer exists in this journal must not stick
    for _k, _opts in (("filters_inst_select", inst_opts), ("filters_em_select", em_opts),
                      ("filters_sess_select", sess_opts), ("filters_acct_select", acct_opts),
                      ("filters_tot_select", tot_opts), ("filters_date_mode", date_mode_options)):
        if _k in st.session_state and st.session_state.get(_k) not in (_opts or []):
            st.session_state.pop(_k, None)

    _active = sum(1 for k in ["filters_inst_select", "filters_sess_select",
                              "filters_em_select", "filters_tot_select"]
                  if st.session_state.get(k, "All") != "All")
    if st.session_state.get("filters_date_mode", "All") != "All":
        _active += 1
    _flabel = f"Filters · {_active} on" if _active else "Filters"
    st.markdown('<div class="ea-hdrbar"></div>', unsafe_allow_html=True)
    _hc1, _hcd, _hc2, _hc3 = st.columns([5.3, 2.1, 1.5, 0.9])
    with _hcd:
        # Density: Focus = track record + what needs work; All = the six tabs.
        _dwant = "Focus" if st.session_state.get("ea_density_pref") == "Focus" else "All"
        if st.session_state.get("ea_density_seg") not in ("Focus", "All"):
            st.session_state["ea_density_seg"] = _dwant
        elif st.session_state.get("ea_density_seg") != _dwant:
            # keep the toggle locked to the pref — a boot rerun that recreated
            # the widget must never drag the pref the other way
            st.session_state["ea_density_seg"] = _dwant

        def _density_cb():
            want = st.session_state.get("ea_density_seg") or "All"
            if st.session_state.get("ea_density_pref", "All") != want:
                st.session_state["ea_density_pref"] = want
                st.session_state["ea_density_dirty"] = True

        st.markdown('<div class="ea-densityseg"></div>', unsafe_allow_html=True)
        st.radio("Density", ["Focus", "All"], key="ea_density_seg",
                 horizontal=True, on_change=_density_cb, label_visibility="collapsed",
                 help="Focus shows your track record and what needs work. All shows every tab.")
    with _hc1:
        try:
            flt = st.popover(_flabel, use_container_width=False)
        except Exception:
            flt = st.expander(_flabel)
    with _hc2:
        _dark_now = st.session_state.get("ea_theme_pref", "light") == "dark"
        _want = "\u263e" if _dark_now else "\u2600"
        if st.session_state.get("ea_theme_seg") not in ("\u2600", "\u263e"):
            st.session_state["ea_theme_seg"] = _want

        def _theme_cb():
            want = "dark" if st.session_state.get("ea_theme_seg") == "\u263e" else "light"
            if st.session_state.get("ea_theme_pref", "light") != want:
                st.session_state["ea_theme_pref"] = want
                st.session_state["ea_theme_dirty"] = True

        st.markdown('<div class="ea-themeseg"></div>', unsafe_allow_html=True)
        st.radio("Theme", ["\u2600", "\u263e"], key="ea_theme_seg",
                 horizontal=True, on_change=_theme_cb, label_visibility="collapsed")
    with _hc3:
        st.markdown('<div class="ea-dots"></div>', unsafe_allow_html=True)
        try:
            _more = st.popover("\u22ef", use_container_width=False)
        except Exception:
            _more = st.expander("More")
    with flt:
        st.markdown("<div style='font-size:11px;font-weight:700;letter-spacing:0.06em;"
                    "color:#94a3b8;margin-bottom:2px;'>FILTERS</div>", unsafe_allow_html=True)
        c1, c2 = st.columns(2, gap="small")
        with c1:
            sel_inst = st.selectbox(
                "Instrument",
                inst_opts,
                index=inst_opts.index(st.session_state.get("filters_inst_select", "All"))
                if st.session_state.get("filters_inst_select", "All") in inst_opts
                else 0,
                format_func=_inst_label,
                key="filters_inst_select", on_change=_filters_dirty,
            )
            sel_em = st.selectbox(
                "Entry Model",
                em_opts,
                index=em_opts.index(st.session_state.get("filters_em_select", "All"))
                if st.session_state.get("filters_em_select", "All") in em_opts
                else 0,
                key="filters_em_select", on_change=_filters_dirty,
            )
        with c2:
            sel_sess = st.selectbox(
                "Session",
                sess_opts,
                index=sess_opts.index(st.session_state.get("filters_sess_select", "All"))
                if st.session_state.get("filters_sess_select", "All") in sess_opts
                else 0,
                key="filters_sess_select", on_change=_filters_dirty,
            )
            sel_acct = "All"
            sel_tot = "All"
            # one box, two journals: MT5 templates filter by Trade Type,
            # the SR template filters by Account
            _has_tot = bool(tot_opts) and len(tot_opts) > 1
            # Both render: Trade Type answers "what kind of trading", Account
            # answers "whose money" — a multi-account journal needs both.
            _has_acct = bool(acct_opts) and len(acct_opts) > 1
            if _has_tot:
                _tot_default = next((o for o in ("Executed", "Real money only")
                                     if o in tot_opts), "All")
                _cur_tot = st.session_state.get("filters_tot_select", _tot_default)
                if _cur_tot not in tot_opts:
                    _cur_tot = _tot_default
                sel_tot = st.selectbox(
                    "Trade Type",
                    tot_opts,
                    index=tot_opts.index(_cur_tot),
                    key="filters_tot_select", on_change=_filters_dirty,
                    help="Executed = every real fill (challenges included). "
                         "All also counts forward and back tests.",
                )
        c3, c4 = st.columns(2, gap="small")
        with c4:
            if _has_acct:
                _acct_default = acct_opts[0]  # "All executed" when real accounts exist
                _cur_acct = st.session_state.get("filters_acct_select", _acct_default)
                if _cur_acct not in acct_opts:
                    _cur_acct = _acct_default
                sel_acct = st.selectbox(
                    "Account",
                    acct_opts,
                    index=acct_opts.index(_cur_acct),
                    key="filters_acct_select", on_change=_filters_dirty,
                    help="Money cards follow your main account; pick one here "
                         "to switch everything to it.",
                )
        with c3:
            current_mode = st.session_state.get("filters_date_mode", "All")
            if current_mode not in date_mode_options:
                current_mode = "All"
            date_mode = st.selectbox(
                "Date range",
                date_mode_options,
                index=date_mode_options.index(current_mode),
                key="filters_date_mode", on_change=_filters_dirty,
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

    try:
        from edge_analysis.ui.chat import feedback_enabled as _fb_on
        _fb = _fb_on()
    except Exception:
        _fb = False

    def _go(page):
        st.session_state[SessionKeys.NAV_TARGET] = page
        st.session_state["ea_show_qr"] = False

    def _refresh():
        try:
            st.cache_data.clear()
        except Exception:
            pass
        st.session_state.pop("ea_last_sync", None)
        st.session_state.pop("ea_warm_served", None)

    def _flag(k):
        st.session_state[k] = True

    _eyebrow = ("<div class='ea-menu-eyebrow' style='font-size:10.5px;font-weight:700;"
                "letter-spacing:0.07em;color:#94a3b8;'>{}</div>")
    _eyebrow_div = ("<div class='ea-menu-sep' style='border-top:1px solid "
                    "rgba(148,163,184,0.22);'></div>" + _eyebrow)
    with _more:
        st.markdown('<div class="ea-moremenu"></div>', unsafe_allow_html=True)
        _cur = st.session_state.get(SessionKeys.NAV_PAGE, PageNames.DASHBOARD)
        st.markdown(_eyebrow.format("VIEW"), unsafe_allow_html=True)
        st.button(("\u2713 " if _cur == PageNames.DASHBOARD else "") + PageNames.DASHBOARD,
                  key="mm_dash", use_container_width=True,
                  on_click=_go, args=(PageNames.DASHBOARD,))
        st.button(PageNames.CONNECT, key="mm_tmpl", use_container_width=True,
                  on_click=_go, args=(PageNames.CONNECT,))
        st.markdown(_eyebrow_div.format("ACTIONS"), unsafe_allow_html=True)
        st.button("Refresh data", key="mm_refresh", use_container_width=True,
                  on_click=_refresh)
        st.button("Sign in on iPhone", key="mm_qr", use_container_width=True,
                  on_click=_flag, args=("ea_show_qr",))
        st.button("MT5 auto-sync", key="mm_mt5sync", use_container_width=True,
                  on_click=_flag, args=("ea_show_mt5sync",))
        if _fb:
            st.button("Send feedback", key="mm_fb", use_container_width=True,
                      on_click=_flag, args=("ea_show_feedback",))
        st.markdown(_eyebrow_div.format("HELP"), unsafe_allow_html=True)
        st.button("Getting started", key="mm_setup", use_container_width=True,
                  on_click=_flag, args=("ea_show_setup",))
        st.button("Connect your broker", key="mm_broker", use_container_width=True,
                  on_click=_flag, args=("ea_show_broker",))
        st.button("What the stats mean", key="mm_help", use_container_width=True,
                  on_click=_flag, args=("ea_show_help",))
        st.button("Privacy & terms", key="mm_legal", use_container_width=True,
                  on_click=_flag, args=("ea_show_legal",))
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
    if st.session_state.pop("ea_show_broker", False):
        if _broker_dialog is not None:
            _broker_dialog()
        else:
            with st.expander("Connect your broker", expanded=True):
                _broker_body()
    if st.session_state.pop("ea_show_setup", False):
        if _setup_dialog is not None:
            _setup_dialog()
        else:
            with st.expander("Getting started", expanded=True):
                _setup_body()
    if st.session_state.pop("ea_show_mt5sync", False):
        if _mt5sync_dialog is not None:
            _mt5sync_dialog()
        else:
            with st.expander("MT5 auto-sync", expanded=True):
                _mt5sync_body()
    if st.session_state.pop("ea_show_legal", False):
        if _legal_dialog is not None:
            _legal_dialog()
        else:
            with st.expander("Privacy & terms", expanded=True):
                _legal_body()
    if st.session_state.pop("ea_show_feedback", False):
        if _feedback_dialog is not None:
            _feedback_dialog()
        else:
            with st.expander("Send feedback", expanded=True):
                _fb_body_safe()

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


LEGAL_MD = """
**Your data.** Your trading journal stays in **your** Notion workspace — the app reads
it to draw your dashboard. This server keeps only your account link (Notion name,
email, chosen template) and a short-lived cache of your journal for speed. Sign-in
and preferences live in your own browser. If you connect WHOOP, its token is stored
in a private page inside your own Notion, not here.

**What we never do.** No selling or sharing of data, no ads, no training on your
journal, no ability to place trades. The optional AI chat sends only your question
plus a compact statistical summary — never your raw journal — to Anthropic's API.

**Deleting.** Disconnect in the app or email campbellstevo@gmail.com and we delete
your account link and cache. Your journal in Notion is untouched either way.

---

**Not financial advice.** Statistics, projections and chat answers describe your own
past data. They are not recommendations or predictions; trading involves substantial
risk of loss. The service is provided as-is, may change or pause, and we are not
liable for trading decisions made with it. Governed by the laws of Victoria,
Australia. Continued use after an update to these terms is acceptance.

_Contact: campbellstevo@gmail.com \u00b7 Full text: PRIVACY.md and TERMS.md in the repository._
"""


def _mt5sync_body() -> None:
    st.markdown(
        "Every trade you close in **MetaTrader 5** lands in your Notion journal "
        "by itself — prices, P&L, session, R multiple, MAE/MFE. You only fill in "
        "the thinking.\n\n"
        "Your download is personal: your journal and its key are already inside. "
        "Unzip, double-click **run_sync.bat** on the Windows PC where MT5 lives, "
        "leave it running. That's the whole setup.")
    try:
        from edge_analysis.mt5_sync_pack import build_zip
        _dbid = str(st.session_state.get("override_DATABASE_ID") or "")
        _utok = str(st.session_state.get("user_notion_token")
                    or st.session_state.get("override_NOTION_TOKEN") or "")
        st.download_button("⬇ Download your sync (zip)",
                           data=build_zip(_dbid, _utok),
                           file_name="edge-analysis-mt5-sync.zip",
                           mime="application/zip", use_container_width=True)
    except Exception:
        st.info("The download isn't available right now — refresh and reopen this.")
    st.caption("Windows + Python required. Already-journaled trades are never "
               "duplicated, so it's safe to stop and start any time.")


try:
    @st.dialog("MT5 auto-sync")
    def _mt5sync_dialog():
        _mt5sync_body()
except Exception:
    _mt5sync_dialog = None


def _broker_body() -> None:
    """Per-platform truth: what syncs itself today, what doesn't, no pretending."""
    st.markdown("**MetaTrader 5** — automatic. Your personal sync is ready below; "
                "every closed trade writes itself into your journal.")
    _mt5sync_body()
    st.markdown("---")
    st.markdown(
        "**cTrader, TradingView, DXtrade, others** — manual for now, honestly. "
        "Log trades straight into the Notion journal and the dashboard works "
        "identically — every chart, stat and verdict. Auto-sync for more "
        "platforms is on the roadmap; MT5 came first because it's what most "
        "prop firms and brokers run.\n\n"
        "**Prop-firm challenge accounts** count as executed trades here — "
        "they're real fills under real pressure. Money cards stay pinned to "
        "the one account you nominate, so a combine never inflates your "
        "track record.")


try:
    @st.dialog("Connect your broker")
    def _broker_dialog():
        _broker_body()
except Exception:
    _broker_dialog = None


def _legal_body() -> None:
    st.markdown(LEGAL_MD)


try:
    @st.dialog("Privacy & terms")
    def _legal_dialog():
        _legal_body()
except Exception:
    _legal_dialog = None


def _setup_body() -> None:
    st.markdown(
        "**1. Get the journal template**\n"
        "Duplicate it into your own Notion — one click, every column ready. "
        "Already journal in Notion? Skip this; the app recognises your journal "
        "when you sign in.\n\n"
        "**2. Sign in with Notion**\n"
        "No keys, no setup. Notion shows a checklist of your pages — tick your "
        "Trade Journal and the app finds it by itself.\n\n"
        "**3. Get your trades in**\n"
        "**MetaTrader 5:** ⋯ menu → *MT5 auto-sync* — your download comes with "
        "everything pre-filled; unzip and run it on the PC where MT5 lives, and "
        "every closed trade writes itself into your journal.\n"
        "**Any other broker:** log trades straight into the Notion journal — "
        "the dashboard works identically; auto-sync for other platforms is on "
        "the roadmap.\n\n"
        "**4. Phone**\n"
        "⋯ menu → *Sign in on iPhone*, scan once, add to home screen. Stays "
        "signed in.\n\n"
        "**5. Tag the thinking**\n"
        "The numbers arrive on their own; the edge is in the manual fields — "
        "A+ Setup, Conviction, Mental State, Mistake. Every tagged trade sharpens "
        "Plan, Psychology and What-needs-work."
    )
    st.caption("Analytics on your own journal — not financial advice.")


try:
    @st.dialog("Getting started")
    def _setup_dialog():
        _setup_body()
except Exception:
    _setup_dialog = None


def _fb_body_safe() -> None:
    try:
        from edge_analysis.ui.chat import feedback_body
        feedback_body()
    except Exception:
        st.caption("Feedback isn't available right now.")


try:
    @st.dialog("Send feedback")
    def _feedback_dialog():
        _fb_body_safe()
except Exception:
    _feedback_dialog = None
