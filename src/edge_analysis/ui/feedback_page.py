"""Feedback & ideas page: write what's broken, what you'd change or what you
wish the site did, attach a screenshot, send. The owner also sees the inbox.

Asked for 26 Sep ("a whole new tab where you can just send a screenshot or
write in things you don't like or potential improvements")."""
from __future__ import annotations

import html

import streamlit as st

from edge_analysis import feedback as fb

AREAS = ["Performance", "Entry", "Externals", "Psychology", "Plan", "Review",
         "Menu & settings", "Sign-in & journal setup", "Somewhere else"]
_PLACEHOLDER = {
    "broken": "What did you do, and what happened instead?",
    "dislike": "What don't you like, and what would you rather see?",
    "idea": "What would make this more useful to you?",
}
_HOURLY_CAP = 10


def _mask(e: str) -> str:
    e = str(e or "").strip()
    if "@" not in e:
        return e
    local, dom = e.split("@", 1)
    return (local[:3] + "•••@" + dom) if local else e


def leave() -> None:
    """Back to the views, on the tab they came from (a tab tapped in the
    header sets its own)."""
    if st.session_state.pop("ea_page", None) == "feedback" and not st.session_state.get("ea_tab"):
        st.session_state["ea_tab"] = st.session_state.pop("ea_fb_prev_tab", None) or "Performance"


def open_page(area: str | None = None) -> None:
    """Callback: show the Feedback page. The header's tab row is cleared so no
    view looks selected while you're here, and tapping any tab leaves."""
    if st.session_state.get("ea_page") != "feedback":
        st.session_state["ea_fb_prev_tab"] = st.session_state.get("ea_tab") or "Performance"
        st.session_state["ea_fb_area_pick"] = area or st.session_state.get("ea_tab")
        st.session_state.pop("ea_fb_area", None)
    st.session_state["ea_page"] = "feedback"
    st.session_state["ea_tab"] = None


def _who(is_owner: bool) -> str:
    if is_owner:
        return "owner"
    uid = str(st.session_state.get("ea_user_id") or st.session_state.get("user_id") or "")
    return "demo" if st.session_state.get("ea_demo") else "member " + fb.who_hash(uid)


def _form(is_owner: bool) -> None:
    from edge_analysis.ui.tabs import _card_header
    with st.container(border=True):
        st.markdown('<div class="ea-card-anchor ea-fb"></div>', unsafe_allow_html=True)
        _card_header("Feedback & ideas",
                     "What's broken, what you'd change, what you wish it did — "
                     "it goes straight to the person building this. A screenshot says it fastest.")
        sent = st.session_state.pop("ea_fb_sent", None)
        if sent:
            st.success("Got it — thank you. It's with the builder.")
            if is_owner and sent == "disk-only":
                st.caption("Kept on this server only — see the Inbox below.")
        who = _who(is_owner)
        if not is_owner and fb.recent_count(who) >= _HOURLY_CAP:
            st.caption("That's a lot of notes in an hour — thank you. Send the next one in a little while.")
            return
        if "ea_fb_kind" not in st.session_state:
            st.session_state["ea_fb_kind"] = "idea"
        kind = st.segmented_control(
            "What is it?", list(fb.KINDS), key="ea_fb_kind",
            format_func=lambda k: f"{fb.KINDS[k][1]}  {fb.KINDS[k][0]}") or "idea"
        _default_area = st.session_state.get("ea_fb_area_pick") or "Performance"
        if st.session_state.get("ea_fb_area") not in AREAS:
            st.session_state["ea_fb_area"] = _default_area if _default_area in AREAS else "Somewhere else"
        with st.form("ea_fb_form", clear_on_submit=True, border=False):
            area = st.selectbox("Which part of the site?", AREAS, key="ea_fb_area")
            text = st.text_area("Tell us", height=140, max_chars=fb.MAX_TEXT,
                                placeholder=_PLACEHOLDER.get(kind, _PLACEHOLDER["idea"]))
            shots = st.file_uploader(
                "Screenshots — up to 3, 5 MB each", type=["png", "jpg", "jpeg", "webp"],
                accept_multiple_files=True,
                help="On a phone: take the screenshot, then pick it from Photos here.")
            email = str(st.session_state.get("ea_user_email") or "")
            reply = False
            if email and not is_owner:
                reply = st.checkbox(f"Let the builder reply to me at {_mask(email)}", value=False,
                                    help="Off by default: your note arrives without your email.")
            go = st.form_submit_button("Send", type="primary", use_container_width=True)
        if go:
            files = []
            too_big = 0
            for f in (shots or [])[:fb.MAX_IMAGES]:
                data = f.getvalue()
                if len(data) > fb.MAX_IMAGE_BYTES:
                    too_big += 1
                    continue
                files.append((f.name, data, f.type or "image/png"))
            if not (text or "").strip() and not files:
                st.warning("Write a line or attach a screenshot first.")
                return
            note = fb.submit(kind, area, text, files, who=who,
                             reply_to=email if reply else None)
            st.session_state["ea_fb_sent"] = "notion" if note.get("notion") else "disk-only"
            if too_big:
                st.session_state["ea_fb_sent"] = "disk-only"
            st.rerun()


def _inbox() -> None:
    from edge_analysis.ui.tabs import _card_header
    items = fb.inbox(100)
    new = [i for i in items if not i.get("done")]
    with st.container(border=True):
        st.markdown('<div class="ea-card-anchor"></div>', unsafe_allow_html=True)
        _card_header("Inbox" + (f" · {len(new)} new" if new else ""),
                     "Only you see this. What members sent since this server started.")
        kind, where = fb.destination()
        if kind == "notion":
            st.caption(f"Every note is also copied to {where}, where it stays for good.")
        else:
            st.warning("Notes are kept on this server only and are lost at the next redeploy. "
                       "To keep them, add FEEDBACK_NOTION_TOKEN and FEEDBACK_PAGE_ID in Streamlit "
                       "→ Settings → Secrets (steps below).")
            with st.expander("Keep feedback in Notion — 3 steps"):
                st.markdown(
                    "1. notion.so/my-integrations → **New integration** (internal) → copy its secret.\n"
                    "2. Make a Notion page (or database) called *Edge Analysis feedback*; in its "
                    "⋯ menu → **Connections** → add that integration.\n"
                    "3. In Streamlit Secrets add `FEEDBACK_NOTION_TOKEN = \"<the secret>\"` and "
                    "`FEEDBACK_PAGE_ID = \"<the 32 characters at the end of the page link>\"`.")
        err = fb.last_error()
        if err.get("msg"):
            st.caption(f"Last Notion problem ({err['at']}): {err['msg']}")
        if not items:
            st.caption("Nothing yet.")
            return
        show_done = st.toggle("Show done", value=False, key="ea_fb_show_done")
        for it in items:
            if it.get("done") and not show_done:
                continue
            label, emoji = fb.KINDS.get(it.get("kind"), fb.KINDS["idea"])
            with st.container(border=True):
                meta = f"{it.get('area')} · {it.get('when')} · {it.get('who')}"
                if it.get("reply_to"):
                    meta += f" · reply to {it['reply_to']}"
                if not it.get("notion"):
                    meta += " · not in Notion"
                done = " · done" if it.get("done") else ""
                st.markdown(
                    f"<div style='font-weight:700;font-size:15px;'>{emoji} {html.escape(label)}{done}</div>"
                    f"<div style='font-size:12.5px;color:#64748b;margin:2px 0 6px;'>{html.escape(meta)}</div>"
                    f"<div style='font-size:14px;white-space:pre-wrap;'>{html.escape(it.get('text') or '')}</div>",
                    unsafe_allow_html=True)
                imgs = [fb.image_path(n) for n in it.get("images") or []]
                imgs = [p for p in imgs if p]
                if imgs:
                    st.image([str(p) for p in imgs], width=220)
                st.button("Mark not done" if it.get("done") else "Mark done", key=f"ea_fb_done_{it['id']}",
                          on_click=fb.set_done, args=(it["id"], not it.get("done")))


def render_feedback_page(is_owner: bool = False, mobile: bool = False) -> None:
    # Streamlit's "Limit 200MB per file" line is the server's ceiling, not this
    # form's: the label carries the real one
    st.markdown("<style>div[data-testid='stVerticalBlock']:has(.ea-fb) "
                "[data-testid='stFileUploaderDropzoneInstructions'] small { display: none !important; }"
                "</style>", unsafe_allow_html=True)
    st.button("← Back to your dashboard", key="ea_fb_back", on_click=leave)
    _form(is_owner)
    if is_owner:
        _inbox()
