"""Feedback inbox: what members (and the owner) send from the Feedback page.

Every note is written to the server's disk first, so nothing is lost if
Notion is down, then copied to Notion when a destination is configured:

1. FEEDBACK_PAGE_ID — a page (notes are appended) or a database (one row per
   note), with FEEDBACK_NOTION_TOKEN, or STORE_NOTION_TOKEN when that is the
   only token set.
2. Otherwise, when the user store already mirrors to Notion (STORE_PAGE_ID),
   an "Edge Analysis feedback" page the app creates once under that page — so
   a site that mirrors its store needs no new setup.
3. Otherwise disk only: kept until the next redeploy, and the owner's inbox
   says so.

Screenshots go up through Notion's file-upload API and sit under the note.
A member's email is sent only when they tick "let the builder reply"; the
note otherwise carries a short hash of their user id, never their name.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_ROOT = Path(__file__).resolve().parent
_DIR = Path(os.environ.get("EA_FEEDBACK_DIR") or (_ROOT / "feedback_inbox"))
_LOCK = threading.Lock()
_NV = {"Notion-Version": "2022-06-28"}
_API = "https://api.notion.com/v1"

KINDS = {
    "broken": ("Broken", "\U0001F41E"),
    "dislike": ("Don't like", "\U0001F44E"),
    "idea": ("Idea", "\U0001F4A1"),
}
MAX_TEXT = 4000
MAX_IMAGES = 3
MAX_IMAGE_BYTES = 5 * 1024 * 1024          # Notion's free-workspace upload limit
_AUTO_PAGE_TITLE = "Edge Analysis feedback"
_AUTO_PAGE_ID: Optional[str] = None
_LAST_ERROR: Dict[str, Any] = {"at": None, "msg": None}


# ----------------------------- config ----------------------------------------

def _secret(key: str) -> Optional[str]:
    try:
        import streamlit as st  # type: ignore
        v = st.secrets.get(key)
        if v:
            return str(v).strip()
    except Exception:
        pass
    v = os.environ.get(key)
    return str(v).strip() if v else None


def _token() -> Optional[str]:
    return _secret("FEEDBACK_NOTION_TOKEN") or _secret("STORE_NOTION_TOKEN")


def destination() -> Tuple[str, str]:
    """(kind, detail) for the owner's inbox: 'notion' with where, or 'disk'."""
    tok = _token()
    if tok and _secret("FEEDBACK_PAGE_ID"):
        return "notion", "your feedback page in Notion"
    if tok and _secret("STORE_PAGE_ID"):
        return "notion", f"the “{_AUTO_PAGE_TITLE}” page under your user-store page in Notion"
    return "disk", "this server only, until the next redeploy"


def last_error() -> Dict[str, Any]:
    return dict(_LAST_ERROR)


def _fail(msg: str) -> None:
    _LAST_ERROR["at"] = time.strftime("%d %b %H:%M")
    _LAST_ERROR["msg"] = msg
    try:
        import sys
        print(f"[feedback] {msg}", file=sys.stderr)
    except Exception:
        pass


def who_hash(user_id: str) -> str:
    """A stable, short stand-in for a member: enough to group their notes."""
    return hashlib.sha256((user_id or "anon").encode()).hexdigest()[:8]


# ----------------------------- disk -------------------------------------------

def _index_path() -> Path:
    return _DIR / "inbox.json"


def _read_index() -> List[Dict[str, Any]]:
    try:
        return json.loads(_index_path().read_text()) or []
    except Exception:
        return []


def _write_index(items: List[Dict[str, Any]]) -> None:
    _DIR.mkdir(parents=True, exist_ok=True)
    tmp = _index_path().with_suffix(".tmp")
    tmp.write_text(json.dumps(items, indent=1))
    os.replace(tmp, _index_path())


def inbox(limit: int = 100) -> List[Dict[str, Any]]:
    """Newest first — what this server has received since it started."""
    with _LOCK:
        items = _read_index()
    return list(reversed(items))[:limit]


def image_path(name: str) -> Optional[Path]:
    p = (_DIR / "img" / Path(name).name)
    return p if p.exists() else None


def set_done(note_id: str, done: bool = True) -> None:
    with _LOCK:
        items = _read_index()
        for it in items:
            if it.get("id") == note_id:
                it["done"] = bool(done)
        _write_index(items)


def recent_count(who: str, seconds: int = 3600) -> int:
    cut = time.time() - seconds
    return sum(1 for it in inbox(500) if it.get("who") == who and it.get("ts", 0) >= cut)


# ----------------------------- Notion -----------------------------------------

def _call(method: str, url: str, **kw):
    try:
        from edge_analysis.user_store import _notion_call
    except Exception:  # pragma: no cover
        return None
    return _notion_call(method, url, **kw)


def _hdr(tok: str, json_body: bool = True) -> Dict[str, str]:
    h = {"Authorization": f"Bearer {tok}", **_NV}
    if json_body:
        h["Content-Type"] = "application/json"
    return h


def _auto_page(tok: str) -> Optional[str]:
    """Find or create the feedback page under the user-store page."""
    global _AUTO_PAGE_ID
    if _AUTO_PAGE_ID:
        return _AUTO_PAGE_ID
    parent = _secret("STORE_PAGE_ID")
    if not parent:
        return None
    r = _call("get", f"{_API}/blocks/{parent}/children", params={"page_size": 100},
              headers=_hdr(tok, False))
    if r is not None and r.ok:
        for blk in (r.json() or {}).get("results", []):
            if (blk.get("type") == "child_page"
                    and (blk.get("child_page") or {}).get("title") == _AUTO_PAGE_TITLE):
                _AUTO_PAGE_ID = blk.get("id")
                return _AUTO_PAGE_ID
    r = _call("post", f"{_API}/pages", headers=_hdr(tok), json={
        "parent": {"page_id": parent},
        "properties": {"title": {"title": [{"text": {"content": _AUTO_PAGE_TITLE}}]}},
    })
    if r is not None and r.ok:
        _AUTO_PAGE_ID = (r.json() or {}).get("id")
        return _AUTO_PAGE_ID
    _fail(f"couldn't create the feedback page: HTTP {getattr(r, 'status_code', 'network')}")
    return None


def _upload(tok: str, name: str, data: bytes, mime: str) -> Optional[str]:
    """Notion file upload (single part): create, then send the bytes."""
    r = _call("post", f"{_API}/file_uploads", headers=_hdr(tok),
              json={"filename": name, "content_type": mime})
    if r is None or not r.ok:
        _fail(f"screenshot upload refused: HTTP {getattr(r, 'status_code', 'network')}")
        return None
    fid = (r.json() or {}).get("id")
    r2 = _call("post", f"{_API}/file_uploads/{fid}/send", headers=_hdr(tok, False),
               files={"file": (name, data, mime)})
    if r2 is None or not r2.ok:
        _fail(f"screenshot send refused: HTTP {getattr(r2, 'status_code', 'network')}")
        return None
    return fid


def _text(s: str, bold: bool = False) -> Dict[str, Any]:
    return {"type": "text", "text": {"content": s[:2000]}, "annotations": {"bold": bold}}


def _blocks(note: Dict[str, Any], upload_ids: List[Optional[str]]) -> List[Dict[str, Any]]:
    label, emoji = KINDS.get(note["kind"], KINDS["idea"])
    head = f"{label} · {note['area']} · {note['when']} · from {note['who']}"
    if note.get("reply_to"):
        head += f" · reply to {note['reply_to']}"
    body = note["text"] or "(screenshot only)"
    kids: List[Dict[str, Any]] = [
        {"object": "block", "type": "paragraph",
         "paragraph": {"rich_text": [_text(body[i:i + 2000]) for i in range(0, len(body), 2000)]}}]
    for fid, img in zip(upload_ids, note["images"]):
        if fid:
            kids.append({"object": "block", "type": "image",
                         "image": {"type": "file_upload", "file_upload": {"id": fid}}})
        else:
            kids.append({"object": "block", "type": "paragraph", "paragraph": {"rich_text": [
                _text(f"(screenshot {img} couldn't be uploaded — it's on the server)")]}})
    return [{"object": "block", "type": "callout",
             "callout": {"rich_text": [_text(head, bold=True)],
                         "icon": {"type": "emoji", "emoji": emoji},
                         "children": kids}}]


def _to_notion(note: Dict[str, Any], files: List[Tuple[str, bytes, str]]) -> bool:
    tok = _token()
    if not tok:
        return False
    target = _secret("FEEDBACK_PAGE_ID") or _auto_page(tok)
    if not target:
        return False
    ids = [_upload(tok, n, d, m) for n, d, m in files]
    blocks = _blocks(note, ids)
    # a database takes one row per note; a page takes the note appended
    db = _call("get", f"{_API}/databases/{target}", headers=_hdr(tok, False))
    if db is not None and db.ok:
        props = (db.json() or {}).get("properties", {})
        title_prop = next((k for k, v in props.items() if v.get("type") == "title"), "Name")
        label = KINDS.get(note["kind"], KINDS["idea"])[0]
        title = f"{label} · {note['area']}: {(note['text'] or 'screenshot')[:60]}"
        r = _call("post", f"{_API}/pages", headers=_hdr(tok), json={
            "parent": {"database_id": target},
            "properties": {title_prop: {"title": [{"text": {"content": title}}]}},
            "children": blocks})
    else:
        r = _call("patch", f"{_API}/blocks/{target}/children", headers=_hdr(tok),
                  json={"children": blocks})
    if r is None or not r.ok:
        _fail(f"note not written to Notion: HTTP {getattr(r, 'status_code', 'network')}")
        return False
    return True


# ----------------------------- submit -----------------------------------------

def submit(kind: str, area: str, text: str, files: List[Tuple[str, bytes, str]],
           who: str, reply_to: Optional[str] = None) -> Dict[str, Any]:
    """Keep the note on disk, then copy it to Notion when one is set up.
    Returns the stored note with `notion` True/False."""
    text = (text or "").strip()[:MAX_TEXT]
    files = [(n, d, m) for n, d, m in (files or []) if d and len(d) <= MAX_IMAGE_BYTES][:MAX_IMAGES]
    nid = uuid.uuid4().hex[:10]
    now = time.time()
    try:
        from zoneinfo import ZoneInfo
        from datetime import datetime
        when = datetime.fromtimestamp(now, ZoneInfo(os.environ.get("EDGE_LOCAL_TZ")
                                                    or "Australia/Melbourne")).strftime("%a %d %b %H:%M")
    except Exception:
        when = time.strftime("%a %d %b %H:%M")
    names = []
    with _LOCK:
        (_DIR / "img").mkdir(parents=True, exist_ok=True)
        for i, (n, d, m) in enumerate(files):
            ext = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}.get(m, ".img")
            fn = f"{nid}-{i}{ext}"
            (_DIR / "img" / fn).write_bytes(d)
            names.append(fn)
        note = {"id": nid, "ts": now, "when": when, "kind": kind if kind in KINDS else "idea",
                "area": (area or "Somewhere else")[:40], "text": text, "who": who,
                "reply_to": reply_to or None, "images": names, "done": False, "notion": False}
        items = _read_index()
        items.append(note)
        _write_index(items[-500:])
    ok = False
    try:
        ok = _to_notion(note, [(names[i], files[i][1], files[i][2]) for i in range(len(names))])
    except Exception as e:
        _fail(f"note not written to Notion: {type(e).__name__}")
    if ok:
        with _LOCK:
            items = _read_index()
            for it in items:
                if it.get("id") == nid:
                    it["notion"] = True
            _write_index(items)
        note["notion"] = True
    return note
