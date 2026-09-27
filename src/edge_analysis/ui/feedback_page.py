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
# one hint for every kind: a hint that changed with the kind gave the box a new
# identity each time, and Streamlit drew a fresh, empty one
_PLACEHOLDER = "What happened, what you'd change, or what you wish it did."
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


_PASTE_CSS = """
.ea-fb-paste { display: flex; flex-wrap: wrap; align-items: center; gap: 6px 12px; margin: 2px 0 4px; }
.ea-fb-pastebtn { font: inherit; font-size: 14.5px; font-weight: 600; color: #4800ff; background: #f3efff;
  border: 1px solid #d9ceff; border-radius: 10px; padding: 9px 16px; min-height: 42px; cursor: pointer;
  -webkit-tap-highlight-color: transparent; touch-action: manipulation; }
.ea-fb-pastebtn:hover { background: #e9e2ff; border-color: #b9a6ff; }
.ea-fb-pastebtn:active { transform: translateY(1px); }
.ea-fb-pastehow { font-size: 13px; color: #5b6475; }
.ea-fb-pastemsg { flex-basis: 100%; font-size: 13.5px; font-weight: 600; min-height: 0; }
.ea-fb-pastemsg:empty { display: none; }
.ea-fb-pastemsg[data-ok="1"] { color: #047857; }
.ea-fb-pastemsg[data-ok="0"] { color: #b45309; }
body:has(.ea-dark-css) .ea-fb-pastebtn { color: #d4c8ff; background: rgba(124,92,255,0.16); border-color: rgba(124,92,255,0.55); }
body:has(.ea-dark-css) .ea-fb-pastehow { color: #9aa3b5; }
body:has(.ea-dark-css) .ea-fb-pastemsg[data-ok="1"] { color: #6ee7b7; }
body:has(.ea-dark-css) .ea-fb-pastemsg[data-ok="0"] { color: #fcd34d; }
"""


def _paste_bar(mobile: bool) -> str:
    """The Paste button and its one-line how-to. The button is plain HTML: the
    page script below gives it its job, since a Streamlit button inside a form
    could only submit it."""
    how = ("Screenshot, tap its preview, Share → Copy, then come back and tap Paste."
           if mobile else "Or press Ctrl+V (⌘V on a Mac) anywhere on this page.")
    return ('<div class="ea-fb-paste">'
            '<button type="button" class="ea-fb-pastebtn">📋&nbsp; Paste screenshot</button>'
            f'<span class="ea-fb-pastehow">{html.escape(how)}</span>'
            '<div class="ea-fb-pastemsg" aria-live="polite"></div></div>')


# Runs once in the page itself (not the component's frame, whose listeners die
# with it): a paste anywhere on the Feedback page, or a tap on Paste
# screenshot, hands the picture to the form's own file box — the same path as
# Browse files, so the upload, the limits and the Send are unchanged.
_PASTE_PAGE_JS = r"""
(function () {
  var W = window, D = document;
  if (W.__eaPasteV === 3) return;
  W.__eaPasteV = 3;
  var OK = /^image\/(png|jpe?g|webp)$/;
  var n = 0;
  function form() { return D.querySelector('[data-testid="stForm"]:has(.ea-fb-paste)'); }
  function fileInput() { var f = form(); return f && f.querySelector('[data-testid="stFileUploader"] input[type="file"]'); }
  function say(msg, ok) {
    var m = D.querySelector('.ea-fb-pastemsg');
    if (m) { m.textContent = msg; m.setAttribute('data-ok', ok ? '1' : '0'); }
  }
  // a big retina PNG (or an odd format) becomes a JPEG under the 5 MB limit
  function fit(blob) {
    if (OK.test(blob.type) && blob.size <= 4.5 * 1024 * 1024) return Promise.resolve(blob);
    return new Promise(function (res) {
      var url = URL.createObjectURL(blob), img = new Image();
      img.onload = function () {
        var s = Math.min(1, 3000 / Math.max(img.naturalWidth, img.naturalHeight));
        var c = D.createElement('canvas');
        c.width = Math.round(img.naturalWidth * s); c.height = Math.round(img.naturalHeight * s);
        c.getContext('2d').drawImage(img, 0, 0, c.width, c.height);
        URL.revokeObjectURL(url);
        c.toBlob(function (b) { res(b || blob); }, 'image/jpeg', 0.86);
      };
      img.onerror = function () { URL.revokeObjectURL(url); res(blob); };
      img.src = url;
    });
  }
  function add(blobs) {
    var inp = fileInput();
    if (!inp) { say("Couldn't find the picture box — use Browse files below.", false); return; }
    Promise.all(blobs.map(fit)).then(function (bs) {
      var dt = new DataTransfer(), names = [];
      bs.forEach(function (b) {
        n += 1;
        var ext = b.type === 'image/jpeg' ? 'jpg' : (b.type === 'image/webp' ? 'webp' : 'png');
        names.push('pasted-' + n + '.' + ext);
        dt.items.add(new File([b], names[names.length - 1], { type: b.type || 'image/png' }));
      });
      inp.files = dt.files;
      inp.dispatchEvent(new Event('input', { bubbles: true }));
      inp.dispatchEvent(new Event('change', { bubbles: true }));
      say('Added ' + names.join(', ') + ' \u2014 it\u2019s in the list below. Press Send when you\u2019re ready.', true);
    });
  }
  D.addEventListener('paste', function (e) {
    if (!form() || !e.clipboardData) return;
    if (e.target && e.target.closest && e.target.closest('[data-testid="stPopoverBody"]')) return;
    var imgs = [], items = e.clipboardData.items || [];
    for (var i = 0; i < items.length; i++) {
      if (items[i].kind === 'file' && /^image\//.test(items[i].type)) {
        var f = items[i].getAsFile(); if (f) imgs.push(f);
      }
    }
    if (!imgs.length) return;
    var types = Array.prototype.slice.call(e.clipboardData.types || []);
    if (types.indexOf('text/plain') < 0) e.preventDefault();
    add(imgs);
  }, true);
  D.addEventListener('click', function (e) {
    var b = e.target && e.target.closest && e.target.closest('.ea-fb-pastebtn');
    if (!b) return;
    e.preventDefault();
    var mac = /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent);
    if (!navigator.clipboard || !navigator.clipboard.read) {
      say('This browser can’t paste from a button — press ' + (mac ? '⌘V' : 'Ctrl+V') + ' instead.', false);
      return;
    }
    // called straight from the tap: Safari only allows it inside the gesture
    navigator.clipboard.read().then(function (items) {
      var pending = [];
      items.forEach(function (it) {
        var t = (it.types || []).filter(function (x) { return /^image\//.test(x); })[0];
        if (t) pending.push(it.getType(t));
      });
      if (!pending.length) { say('No picture on your clipboard — copy a screenshot first.', false); return; }
      Promise.all(pending).then(add);
    }).catch(function () {
      say('Your browser didn’t allow reading the clipboard — press ' + (mac ? '⌘V' : 'Ctrl+V') + ', or use Browse files.', false);
    });
  }, true);
})();
"""


def _paste_script() -> None:
    import json
    import streamlit.components.v1 as components
    components.html(
        "<script>(function(){var D=window.parent.document;"
        "if(window.parent.__eaPasteV===3)return;"
        "var s=D.createElement('script');s.textContent=" + json.dumps(_PASTE_PAGE_JS) + ";"
        "D.head.appendChild(s);})();</script>", height=0)


def _who(is_owner: bool) -> str:
    if is_owner:
        return "owner"
    uid = str(st.session_state.get("ea_user_id") or st.session_state.get("user_id") or "")
    return "demo" if st.session_state.get("ea_demo") else "member " + fb.who_hash(uid)


def _form(is_owner: bool, mobile: bool = False) -> None:
    from edge_analysis.ui.tabs import _card_header
    with st.container(border=True):
        st.markdown('<div class="ea-card-anchor ea-fb"></div>', unsafe_allow_html=True)
        _card_header("Feedback & ideas",
                     "What's broken, what you'd change, what you wish it did — "
                     "it goes straight to the person building this. A screenshot says it fastest.")
        sent = st.session_state.pop("ea_fb_sent", None)
        if sent:
            st.success("Got it — thank you. It's with the builder.")
            _big = st.session_state.pop("ea_fb_too_big", 0)
            if _big:
                st.caption(f"{_big} picture{'s were' if _big > 1 else ' was'} over 5 MB and didn't go with it.")
            if is_owner and sent == "disk-only":
                st.caption("Kept on this server only — see the Inbox below.")
        who = _who(is_owner)
        if not is_owner and fb.recent_count(who) >= _HOURLY_CAP:
            st.caption("That's a lot of notes in an hour — thank you. Send the next one in a little while.")
            return
        # Everything sits inside the form, so nothing reruns while you write:
        # the kind picker used to live outside it, and picking one after typing
        # redrew the text box (its hint changed with the kind) and wiped it.
        if not st.session_state.get("ea_fb_kind"):
            st.session_state["ea_fb_kind"] = "idea"
        _default_area = st.session_state.get("ea_fb_area_pick") or "Performance"
        if st.session_state.get("ea_fb_area") not in AREAS:
            st.session_state["ea_fb_area"] = _default_area if _default_area in AREAS else "Somewhere else"
        with st.form("ea_fb_form", clear_on_submit=True, border=False):
            kind = st.segmented_control(
                "What is it?", list(fb.KINDS), key="ea_fb_kind",
                format_func=lambda k: f"{fb.KINDS[k][1]}  {fb.KINDS[k][0]}")
            area = st.selectbox("Which part of the site?", AREAS, key="ea_fb_area")
            text = st.text_area("Tell us", height=140, max_chars=fb.MAX_TEXT, key="ea_fb_text",
                                placeholder=_PLACEHOLDER)
            st.markdown(_paste_bar(mobile), unsafe_allow_html=True)
            shots = st.file_uploader(
                "Or attach from your files — up to 3 pictures, 5 MB each",
                type=["png", "jpg", "jpeg", "webp"], accept_multiple_files=True, key="ea_fb_shots")
            email = str(st.session_state.get("ea_user_email") or "")
            reply = False
            if email and not is_owner:
                reply = st.checkbox(f"Let the builder reply to me at {_mask(email)}", value=False,
                                    help="Off by default: your note arrives without your email.")
            go = st.form_submit_button("Send", type="primary", use_container_width=True)
        _paste_script()
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
            note = fb.submit(kind or "idea", area, text, files, who=who,
                             reply_to=email if reply else None)
            st.session_state["ea_fb_sent"] = "notion" if note.get("notion") else "disk-only"
            st.session_state["ea_fb_too_big"] = too_big
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
                + _PASTE_CSS + "</style>", unsafe_allow_html=True)
    st.button("← Back to your dashboard", key="ea_fb_back", on_click=leave)
    _form(is_owner, mobile)
    if is_owner:
        _inbox()
