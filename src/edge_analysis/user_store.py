"""Server-side user store: which Notion database + template each user picked.

Public-readiness hardening:
- writes are atomic (temp file + os.replace) and serialized behind a lock
- a corrupted file is set aside, never crashed on
- EA_STORE_PATH env var can point the store at a persistent disk
- optional Notion mirror (STORE_PAGE_ID + STORE_NOTION_TOKEN or
  FEEDBACK_NOTION_TOKEN): every save is mirrored to a private Notion page,
  and an empty store on boot restores from it — so redeploys on hosts with
  ephemeral disks (Streamlit Cloud) no longer lose user registrations.
- per-user daily LLM usage counter for the chat cap
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Dict, Any, Optional

_ROOT = Path(__file__).resolve().parent
_STORE_FILE = Path(os.environ.get("EA_STORE_PATH") or (_ROOT / "user_store.json"))

_LOCK = threading.Lock()
_MIRROR_BLOCK_ID: Optional[str] = None
_MIRROR_CHECKED = False
_NV = {"Notion-Version": "2022-06-28"}


# ----------------------------- config helpers --------------------------------

def _secret(key: str) -> Optional[str]:
    try:
        import streamlit as st  # type: ignore
        v = st.secrets.get(key)
        if v:
            return str(v)
    except Exception:
        pass
    v = os.environ.get(key)
    return str(v) if v else None


def _mirror_cfg():
    page = _secret("STORE_PAGE_ID")
    tok = _secret("STORE_NOTION_TOKEN") or _secret("FEEDBACK_NOTION_TOKEN")
    return (page, tok) if (page and tok) else (None, None)


# ----------------------------- store shape ------------------------------------

def _empty_store() -> Dict[str, Any]:
    return {"version": 1, "users": {}}


def _normalise(data: Any) -> Dict[str, Any]:
    if not isinstance(data, dict):
        return _empty_store()
    if "users" not in data or not isinstance(data["users"], dict):
        data["users"] = {}
    if "version" not in data:
        data["version"] = 1
    return data


# ----------------------------- Notion mirror ----------------------------------

# One Notion code block holds at most 100 rich-text pieces of 2000 characters.
# The store is written compact; a store that no longer fits is NOT written
# (a cut-off JSON restores nobody after a redeploy) and the failure is reported.
_CHUNK = 2000
_MAX_CHUNKS = 100
MIRROR_CAPACITY = _CHUNK * _MAX_CHUNKS
_MIRROR_STATUS: Dict[str, Any] = {"ok_at": None, "error": None, "chars": 0}


def _report(msg: str) -> None:
    """A store failure is loud: the server log, Sentry when it's on, and the
    owner's ⋯ menu (mirror_status)."""
    _MIRROR_STATUS["error"] = f"{time.strftime('%d %b %H:%M')} {msg}"
    try:
        import sys
        print(f"[user_store] {msg}", file=sys.stderr)
    except Exception:
        pass
    if os.environ.get("_EA_SENTRY_ON"):
        try:
            import sentry_sdk
            sentry_sdk.capture_message(f"user store: {msg}", level="error")
        except Exception:
            pass


def _notion_call(method: str, url: str, **kw):
    """One Notion request that honours a 429: up to three tries, waiting what
    Notion asks (Retry-After) or 1s, 2s. Returns the response, or None when
    the network failed."""
    import requests
    for attempt in range(3):
        try:
            r = getattr(requests, method)(url, timeout=8, **kw)
        except Exception as e:  # network
            if attempt == 2:
                _report(f"{method.upper()} failed: {type(e).__name__}")
                return None
            time.sleep(2 ** attempt)
            continue
        if r.status_code != 429 or attempt == 2:
            return r
        try:
            wait = float(r.headers.get("Retry-After") or 0) or 2 ** attempt
        except (TypeError, ValueError, AttributeError):
            wait = 2 ** attempt
        time.sleep(min(wait, 8))
    return None


def mirror_status() -> Dict[str, Any]:
    """For the owner: how full the mirror is and whether the last write held."""
    return dict(_MIRROR_STATUS, capacity=MIRROR_CAPACITY)


def _mirror_pull() -> Optional[Dict[str, Any]]:
    """Restore the whole store from the mirror page."""
    global _MIRROR_BLOCK_ID
    page, tok = _mirror_cfg()
    if not page:
        return None
    r = _notion_call("get", f"https://api.notion.com/v1/blocks/{page}/children",
                     params={"page_size": 100},
                     headers={"Authorization": f"Bearer {tok}", **_NV})
    if r is None:
        return None
    if not r.ok:
        _report(f"mirror read refused: HTTP {r.status_code}")
        return None
    try:
        for blk in (r.json() or {}).get("results", []):
            if blk.get("type") == "code":
                _MIRROR_BLOCK_ID = blk.get("id")
                txt = "".join(t.get("plain_text", "")
                              for t in blk.get("code", {}).get("rich_text", []))
                if txt.strip().startswith("{"):
                    return _normalise(json.loads(txt))
                return None
    except ValueError:
        _report("mirror unreadable: the stored JSON does not parse")
    except Exception as e:
        _report(f"mirror read failed: {type(e).__name__}")
    return None


def _mirror_push(store: Dict[str, Any]) -> None:
    """Mirror the whole store to one code block on the page."""
    global _MIRROR_BLOCK_ID
    page, tok = _mirror_cfg()
    if not page:
        return
    raw = json.dumps(store, sort_keys=True, separators=(",", ":"))
    _MIRROR_STATUS["chars"] = len(raw)
    if len(raw) > MIRROR_CAPACITY:
        _report(f"mirror FULL: {len(store.get('users', {}))} users, {len(raw)} chars "
                f"> {MIRROR_CAPACITY}; not written — the last good copy stands. "
                "Move the user store to a real database (roadmap 5.5).")
        return
    chunks = [raw[i:i + _CHUNK] for i in range(0, len(raw), _CHUNK)] or [raw]
    rich = [{"type": "text", "text": {"content": c}} for c in chunks]
    hdr = {"Authorization": f"Bearer {tok}", "Content-Type": "application/json", **_NV}
    if _MIRROR_BLOCK_ID is None:
        _mirror_pull()  # discovers the block id if the page has one
    if _MIRROR_BLOCK_ID:
        r = _notion_call("patch", f"https://api.notion.com/v1/blocks/{_MIRROR_BLOCK_ID}",
                         headers=hdr,
                         json={"code": {"rich_text": rich, "language": "json"}})
    else:
        r = _notion_call("patch", f"https://api.notion.com/v1/blocks/{page}/children",
                         headers=hdr,
                         json={"children": [{"object": "block", "type": "code",
                               "code": {"rich_text": rich, "language": "json"}}]})
        if r is not None and r.ok:
            try:
                for blk in (r.json() or {}).get("results", []):
                    if blk.get("type") == "code":
                        _MIRROR_BLOCK_ID = blk.get("id")
            except Exception:
                pass
    if r is None:
        return  # already reported
    if not r.ok:
        _report(f"mirror write refused: HTTP {r.status_code}")
        return
    _MIRROR_STATUS["ok_at"] = time.strftime("%d %b %H:%M")
    _MIRROR_STATUS["error"] = None


# ----------------------------- disk io ----------------------------------------

def _load_raw_store() -> Dict[str, Any]:
    global _MIRROR_CHECKED
    data: Optional[Dict[str, Any]] = None
    if _STORE_FILE.exists():
        try:
            data = _normalise(json.loads(_STORE_FILE.read_text(encoding="utf-8")))
        except Exception:
            try:  # set the broken file aside so it can be inspected, start fresh
                _STORE_FILE.rename(_STORE_FILE.with_suffix(f".corrupt-{int(time.time())}"))
            except Exception:
                pass
            data = None
    if (data is None or not data["users"]) and not _MIRROR_CHECKED:
        _MIRROR_CHECKED = True
        pulled = _mirror_pull()
        if pulled and pulled.get("users"):
            data = pulled
            _write_disk(data)
    return data if data is not None else _empty_store()


def _write_disk(store: Dict[str, Any]) -> None:
    try:
        _STORE_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = _STORE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(store, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(tmp, _STORE_FILE)
    except Exception:
        pass  # read-only env: mirror still gets the write


# Kept once, read by nothing (SEC-09): purged from every record on each save.
# A Notion workspace name is usually the person's name ("Jane's Notion").
_DROPPED_FIELDS = ("name", "email", "workspace")


def _save_raw_store(store: Dict[str, Any]) -> None:
    for rec in store.get("users", {}).values():
        if isinstance(rec, dict):
            for k in _DROPPED_FIELDS:
                rec.pop(k, None)
    _write_disk(store)
    _mirror_push(store)


# ----------------------------- public API --------------------------------------

def get_user(user_id: str) -> Optional[Dict[str, Any]]:
    if not user_id:
        return None
    with _LOCK:
        return _load_raw_store()["users"].get(str(user_id))


def upsert_user(user_id: str, **fields: Any) -> Dict[str, Any]:
    with _LOCK:
        store = _load_raw_store()
        rec = store["users"].setdefault(str(user_id), {})
        for k, v in fields.items():
            if v is not None:
                rec[k] = v
        rec["last_updated"] = int(time.time())  # whole seconds: the mirror has a size cap
        _save_raw_store(store)
        return rec


def set_user_db(user_id: str, db_id: str, template: Optional[str] = None) -> Dict[str, Any]:
    fields: Dict[str, Any] = {"db_id": db_id}
    if template:
        fields["template"] = template
    return upsert_user(user_id, **fields)


def list_users() -> Dict[str, Dict[str, Any]]:
    with _LOCK:
        return dict(_load_raw_store()["users"])


def delete_user(user_id: str) -> None:
    with _LOCK:
        store = _load_raw_store()
        if str(user_id) in store["users"]:
            del store["users"][str(user_id)]
            _save_raw_store(store)


def bump_llm_use(user_id: str, cap: int) -> bool:
    """Count one LLM question against the user's daily cap, server-side.
    Returns True when the question is allowed."""
    day = time.strftime("%Y-%m-%d")
    with _LOCK:
        store = _load_raw_store()
        rec = store["users"].setdefault(str(user_id or "anon"), {})
        usage = rec.get("llm_usage") or {}
        if usage.get("day") != day:
            usage = {"day": day, "n": 0}
        if int(usage.get("n", 0)) >= cap:
            return False
        usage["n"] = int(usage.get("n", 0)) + 1
        rec["llm_usage"] = usage
        _write_disk(store)  # counters don't need the mirror round-trip
        return True
