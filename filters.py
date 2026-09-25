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
    CONNECT = "Journals"


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


def _st_rerun():
    try:
        st.rerun()
    except Exception:
        st.experimental_rerun()


def _render_focus_toggle(marker: str = "ea-bfo") -> None:
    """Focus switch (owner): track record + what needs work, nothing else."""
    _want = st.session_state.get("ea_density_pref") == "Focus"
    # Boot guard (r169): until the prefs blob has been read once, the switch
    # FOLLOWS the stored pref — a replayed default during the boot reruns must
    # not flip a fresh session into Focus. After boot, the switch is the truth.
    if not st.session_state.get("ea_density_booted"):
        st.session_state["ea_focus_tgl"] = _want
        if ("ea_prefs" in st.session_state
                or int(st.session_state.get("ea_prefs_tries", 0) or 0) >= 6):
            st.session_state["ea_density_booted"] = True
    elif "ea_focus_tgl" not in st.session_state:
        st.session_state["ea_focus_tgl"] = _want   # dropped while not drawn
    st.markdown(f'<div class="ea-mk {marker}"></div>', unsafe_allow_html=True)
    _on = st.toggle("Focus", key="ea_focus_tgl")
    # value-compare instead of on_change: callbacks can be dropped across
    # reruns, but the returned value never lies
    _want_pref = "Focus" if _on else "All"
    if st.session_state.get("ea_density_pref", "All") != _want_pref:
        st.session_state["ea_density_pref"] = _want_pref
        st.session_state["ea_density_dirty"] = True
        _st_rerun()


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
    brand: tuple | None = None,
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

    # Focus = the track record plus what needs work. "What needs work" is the
    # verdict layer, owner-only until it passes its null test (1.12), so for
    # members and the demo Focus would be one card — not offered there, and a
    # stored Focus pref falls back to Everything.
    from edge_analysis.ui.tabs import _verdicts_on
    _focus_ok = _verdicts_on()
    if not _focus_ok and st.session_state.get("ea_density_pref") == "Focus":
        st.session_state["ea_density_pref"] = "All"
        st.session_state.pop("ea_focus_tgl", None)

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
    _flabel = f"Filters · {_active}" if _active else "Filters"
    _fmark = "ea-bf ea-bf-on" if _active else "ea-bf"
    _logo_html, _sync_html = brand if brand else ("", "")
    _focus_now = st.session_state.get("ea_density_pref") == "Focus"
    _dark_now = st.session_state.get("ea_theme_pref", "light") == "dark"
    _TABS = ["Performance", "Entry", "Externals", "Psychology", "Plan", "Review"]

    def _flip_theme():
        st.session_state["ea_theme_pref"] = "light" if _dark_now else "dark"
        st.session_state["ea_theme_dirty"] = True

    def _nav():
        # The one nav. Focus mode shows the briefing only, so no tabs there.
        if _focus_now:
            st.session_state.pop("ea_nav_external", None)
            st.markdown("<div class='ea-rail-focus' style='font-size:13px;font-weight:700;"
                        "letter-spacing:0.08em;color:#64748b;padding:0 12px;'>FOCUS \u00b7 "
                        "your briefing</div>", unsafe_allow_html=True)
            return
        st.radio("View", _TABS, horizontal=True, key="ea_tab", label_visibility="collapsed")
        st.session_state["ea_nav_external"] = True

    def _popover(label, icon, help_=None):
        try:
            return st.popover(label, icon=icon, help=help_, use_container_width=False)
        except Exception:
            return st.expander(label)

    from edge_analysis.ui.theme import inject_bar_css
    inject_bar_css()
    if not mobile:
        # One bar: logo · tabs · status · Filters · Focus · theme · menu
        with st.container():
            st.markdown('<div class="ea-mk ea-bar"></div>', unsafe_allow_html=True)
            _cols = st.columns(7 if _focus_ok else 6, vertical_alignment="center")
            _c_logo, _c_nav, _c_sync, _c_flt = _cols[:4]
            _c_focus = _cols[4] if _focus_ok else None
            _c_theme, _c_more = _cols[-2], _cols[-1]
            with _c_logo:
                st.markdown(f"<div class='ea-bar-logo'>{_logo_html}</div>", unsafe_allow_html=True)
            with _c_nav:
                st.markdown('<div class="ea-mk ea-bn"></div>', unsafe_allow_html=True)
                _nav()
            with _c_sync:
                st.markdown('<div class="ea-mk ea-bs"></div>', unsafe_allow_html=True)
                if _sync_html:
                    st.markdown(_sync_html, unsafe_allow_html=True)
            with _c_flt:
                st.markdown(f'<div class="ea-mk {_fmark}"></div>', unsafe_allow_html=True)
                flt = _popover(_flabel, ":material/tune:")
            if _c_focus is not None:
                with _c_focus:
                    _render_focus_toggle()
            with _c_theme:
                st.markdown('<div class="ea-mk ea-bt"></div>', unsafe_allow_html=True)
                st.button("Theme", key="ea_theme_btn", on_click=_flip_theme,
                          icon=":material/light_mode:" if _dark_now else ":material/dark_mode:",
                          help="Light mode" if _dark_now else "Dark mode")
            with _c_more:
                st.markdown('<div class="ea-mk ea-bm"></div>', unsafe_allow_html=True)
                _more = _popover("Menu", ":material/more_horiz:")
    else:
        # Phone: row 1 = logo · status · theme · menu; row 2 = swipeable tabs + Filters
        with st.container():
            st.markdown('<div class="ea-mk ea-pbar"></div>', unsafe_allow_html=True)
            _p1 = st.columns(4, vertical_alignment="center")
            with _p1[0]:
                st.markdown('<div class="ea-mk ea-pl"></div>', unsafe_allow_html=True)
                st.markdown(f"<div class='ea-pbar-logo'>{_logo_html}</div>", unsafe_allow_html=True)
            with _p1[1]:
                st.markdown('<div class="ea-mk ea-ps"></div>', unsafe_allow_html=True)
                if _sync_html:
                    st.markdown(_sync_html, unsafe_allow_html=True)
            with _p1[2]:
                st.markdown('<div class="ea-mk ea-pbt"></div>', unsafe_allow_html=True)
                st.button("Theme", key="ea_theme_btn", on_click=_flip_theme,
                          icon=":material/light_mode:" if _dark_now else ":material/dark_mode:",
                          help="Light mode" if _dark_now else "Dark mode")
            with _p1[3]:
                st.markdown('<div class="ea-mk ea-pbm"></div>', unsafe_allow_html=True)
                _more = _popover("Menu", ":material/more_horiz:")
            _p2 = st.columns(2, vertical_alignment="center")
            with _p2[0]:
                st.markdown('<div class="ea-mk ea-pn"></div>', unsafe_allow_html=True)
                _nav()
            with _p2[1]:
                st.markdown(f'<div class="ea-mk ea-pf{" ea-pf-on" if _active else ""}"></div>',
                            unsafe_allow_html=True)
                flt = _popover(_flabel, ":material/tune:")
    with flt:
        st.markdown("<div style='font-size:11px;font-weight:700;letter-spacing:0.06em;"
                    "color:#64748b;margin-bottom:2px;'>FILTERS</div>", unsafe_allow_html=True)
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
                "Entry model",
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
                    "Trade type",
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
        # This visitor's journal only — clearing every cache made one member's
        # refresh cost every other member a full refetch.
        _tok = (st.session_state.get(SessionKeys.USER_TOKEN)
                or st.session_state.get("override_NOTION_TOKEN"))
        _db = st.session_state.get(SessionKeys.DB_ID)
        try:
            if _tok and _db:
                from data_loading import forget_journal_cache
                forget_journal_cache(_tok, _db)
        except Exception:
            pass
        st.session_state.pop("ea_last_sync", None)
        st.session_state.pop("ea_warm_served", None)

    def _flag(k):
        st.session_state[k] = True

    _eyebrow = ("<div class='ea-menu-eyebrow' style='font-size:10.5px;font-weight:700;"
                "letter-spacing:0.07em;color:#64748b;'>{}</div>")
    _eyebrow_div = ("<div class='ea-menu-sep' style='border-top:1px solid "
                    "rgba(148,163,184,0.22);'></div>" + _eyebrow)
    with _more:
        st.markdown('<div class="ea-moremenu"></div>', unsafe_allow_html=True)
        _cur = st.session_state.get(SessionKeys.NAV_PAGE, PageNames.DASHBOARD)
        st.markdown(_eyebrow.format("VIEW"), unsafe_allow_html=True)
        if mobile and _focus_ok:
            _render_focus_toggle("ea-mfo")
        st.button(("\u2713 " if _cur == PageNames.DASHBOARD else "") + PageNames.DASHBOARD,
                  key="mm_dash", use_container_width=True,
                  on_click=_go, args=(PageNames.DASHBOARD,))
        st.button(PageNames.CONNECT, key="mm_tmpl", use_container_width=True,
                  on_click=_go, args=(PageNames.CONNECT,))

        def _flip_privacy():
            st.session_state["ea_privacy"] = not st.session_state.get("ea_privacy")
            st.session_state["ea_privacy_dirty"] = True

        _pv_lab = ("Show dollar amounts"
                   if st.session_state.get("ea_privacy")
                   else "✓  Dollars shown \u00b7 hide them")
        st.button(_pv_lab, key="mm_privacy", use_container_width=True,
                  on_click=_flip_privacy)
        st.markdown(_eyebrow_div.format("ACTIONS"), unsafe_allow_html=True)
        st.button("Refresh data", key="mm_refresh", use_container_width=True,
                  on_click=_refresh)
        # Auto-log writes MT5-shaped rows (Symbol, Position ID, Open Time…): a
        # journal on another template rejects every one and it retries forever
        # (roadmap 1.10, D6). Offered to MT5 journals and the demo only.
        if (st.session_state.get("ea_demo")
                or st.session_state.get("detected_schema") == "mt5"):
            st.button("Auto-log my trades", key="mm_broker", use_container_width=True,
                      on_click=_flag, args=("ea_show_broker",))
        if _fb:
            st.button("Send feedback", key="mm_fb", use_container_width=True,
                      on_click=_flag, args=("ea_show_feedback",))
        st.markdown(_eyebrow_div.format("HELP"), unsafe_allow_html=True)
        st.button("Getting started", key="mm_setup", use_container_width=True,
                  on_click=_flag, args=("ea_show_setup",))
        st.button("What the stats mean", key="mm_help", use_container_width=True,
                  on_click=_flag, args=("ea_show_help",))
        st.button("Privacy & terms", key="mm_legal", use_container_width=True,
                  on_click=_flag, args=("ea_show_legal",))
        if st.session_state.get("ea_is_owner"):
            st.markdown(_eyebrow_div.format("OWNER"), unsafe_allow_html=True)
            st.button("Send a test error", key="mm_testerr", use_container_width=True,
                      on_click=_flag, args=("ea_send_test_error",))
            st.caption(_server_clock_line())
            st.caption(_store_line())
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
            with st.expander("Auto-log my trades", expanded=True):
                _broker_body()
    if st.session_state.pop("ea_show_setup", False):
        if _setup_dialog is not None:
            _setup_dialog()
        else:
            with st.expander("Getting started", expanded=True):
                _setup_body()
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


def _server_clock_line() -> str:
    """Owner-only: what this server thinks the time is, and in which zone —
    the 'this week / this month' surfaces read this clock (TZ-04)."""
    import os as _os
    import time as _time
    from datetime import datetime as _dt
    now = _dt.now().astimezone()
    local = _os.environ.get("EDGE_LOCAL_TZ") or "Australia/Sydney (default)"
    return (f"Server clock {now:%a %d %b %H:%M} {now.tzname() or _time.tzname[0]} · "
            f"app zone {local}")


def _store_line() -> str:
    """Owner-only: the user store's size against its mirror ceiling, and
    whether the last mirror write held (roadmap 1.13)."""
    try:
        from edge_analysis.user_store import list_users, mirror_status
        n = len(list_users())
        ms = mirror_status()
        pct = int(round(100 * ms.get("chars", 0) / max(1, ms["capacity"])))
        state = (f"FAILED {ms['error']}" if ms.get("error")
                 else (f"saved {ms['ok_at']}" if ms.get("ok_at") else "no write yet this run"))
        return f"User store {n} users \u00b7 mirror {pct}% full \u00b7 {state}"
    except Exception as e:
        return f"User store unreadable: {type(e).__name__}"


def _phone_qr_body() -> None:
    """Phone sign-in. The old QR carried the Notion token in its URL — anyone
    with the picture was signed in as you (SEC-06) — so it is gone until a
    single-use pairing code replaces it (roadmap 5.6)."""
    st.markdown(
        "<div style='font-size:14px;color:#334155;line-height:2;padding:4px 6px 2px;'>"
        "<b>1.</b> Open this site on your phone<br>"
        "<b>2.</b> Tap <b>Sign in with Notion</b> once<br>"
        "<b>3.</b> Add it to your home screen — that phone stays signed in"
        "</div>",
        unsafe_allow_html=True,
    )


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
it to draw your dashboard. This server keeps only which journal you connected, a count
of chat questions for the daily limit, and a cached copy of your journal (at most a
day old) so pages load fast. It does not keep your name or email. Your sign-in and
preferences are saved in your own browser.

**What we never do.** No selling or sharing of data, no ads, no training on your
journal, no ability to place trades. The analyst chat answers from your own numbers
on this server. If a page fails to draw, an error report (what broke and where — not
your journal) goes to our crash reporter so it can be fixed.

**Deleting.** ⋯ menu → Journals → **Disconnect** deletes your account link and the
cached copy of your journal from this server, and this browser's saved sign-in. Your
journal in Notion is untouched either way.

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
        "Every trade you close in **MetaTrader 5** will appear in your journal "
        "by itself. Three steps, once:\n\n"
        "**1. Press the download button below.** A zip file downloads \u2014 it's "
        "yours only, your journal key is already inside.\n\n"
        "**2. Right-click the downloaded file \u2192 Extract All.**\n\n"
        "**3. Open the new folder and double-click `run_sync.bat`** on the "
        "Windows PC where MetaTrader 5 is installed.\n\n"
        "Done. A small black window appears when it runs \u2014 that's normal. "
        "Run it again any time; trades are never duplicated.")
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
    st.caption("Windows + Python required. Safe to stop and start any time.")


try:
    @st.dialog("Auto-log my trades")
    def _mt5sync_dialog():
        _mt5sync_body()
except Exception:
    _mt5sync_dialog = None


def _broker_body() -> None:
    """Per-platform truth: what syncs itself today, what doesn't, no pretending."""
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
    @st.dialog("Auto-log my trades")
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
        "**MetaTrader 5 journals:** ⋯ menu → *Auto-log my trades* — your download comes with "
        "everything pre-filled; unzip and run it on the PC where MT5 lives, and "
        "every closed trade writes itself into your journal.\n"
        "**Any other broker:** log trades straight into the Notion journal — "
        "the dashboard works identically; auto-sync for other platforms is on "
        "the roadmap.\n\n"
        "**4. Phone**\n"
        "Open the site on your phone and sign in with Notion once, then add it "
        "to your home screen. It stays signed in.\n\n"
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
