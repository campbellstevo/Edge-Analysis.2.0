"""Who may use the app — the launch access switch (roadmap item 1.3).

One secret decides it, read on every run so a change takes effect on the
visitor's next click:

    EA_ACCESS = "owner"      only the owner (the default)
    EA_ACCESS = "allowlist"  the owner plus the Notion sign-in emails in EA_ALLOW
    EA_ACCESS = "open"       anyone with a Notion account
    EA_ACCESS = "paused"     the kill switch: only the owner; everyone else
                             sees a paused page

    EA_OWNER  = "you@example.com"          email(s) or Notion user id(s),
                                           comma-separated; falls back to
                                           WHOOP_OWNER when unset
    EA_ALLOW  = "a@example.com, b@x.com"   used by "allowlist"

Unset or unrecognised EA_ACCESS means owner-only — never open. With no owner
configured at all, nobody is admitted and the page says which secret to set.

The demo (?demo=1) needs no account and is not gated.
"""
from __future__ import annotations

import os
import re
from typing import Iterable, Optional, Set, Tuple

MODES = ("owner", "allowlist", "open", "paused")
_ALIASES = {"allow-list": "allowlist", "allow_list": "allowlist", "allow": "allowlist",
            "beta": "allowlist", "public": "open", "pause": "paused", "off": "paused"}


def _secret(key: str) -> str:
    try:
        import streamlit as st
        v = st.secrets.get(key)
        if v:
            return str(v)
    except Exception:
        pass
    return str(os.environ.get(key) or "")


def _split(raw: str) -> Set[str]:
    return {p.strip().lower() for p in re.split(r"[,;\s]+", raw or "") if p.strip()}


def mode() -> str:
    raw = _secret("EA_ACCESS").strip().lower()
    raw = _ALIASES.get(raw, raw)
    return raw if raw in MODES else "owner"


def owners() -> Set[str]:
    return _split(_secret("EA_OWNER") or _secret("WHOOP_OWNER"))


def allowlist() -> Set[str]:
    return _split(_secret("EA_ALLOW"))


def notion_identity(user_info: Optional[dict]) -> Tuple[Set[str], str]:
    """(ids, email) for a Notion /v1/users/me response.

    An OAuth token's /users/me is the integration's *bot*; the person who
    signed in is its owner (bot.owner.user). Both ids count as the visitor's,
    so an owner or allow-list entry may name either, or the email."""
    ids: Set[str] = set()
    email = ""
    info = user_info if isinstance(user_info, dict) else {}
    if info.get("id"):
        ids.add(str(info["id"]).lower())
    person = info.get("person")
    if isinstance(person, dict) and person.get("email"):
        email = str(person["email"])
    owner_user = ((info.get("bot") or {}).get("owner") or {}).get("user")
    if isinstance(owner_user, dict):
        if owner_user.get("id"):
            ids.add(str(owner_user["id"]).lower())
        op = owner_user.get("person")
        if not email and isinstance(op, dict) and op.get("email"):
            email = str(op["email"])
    return ids, email.strip().lower()


def decide(access_mode: str, owner_set: Iterable[str], allow_set: Iterable[str],
           ids: Iterable[str], email: str) -> Tuple[bool, str]:
    """(admitted, reason). reason is one of: owner, allowed, open, paused,
    not_open, no_owner."""
    me = {str(i).strip().lower() for i in ids if str(i).strip()}
    if email:
        me.add(email.strip().lower())
    owner_set = {o.strip().lower() for o in owner_set if o.strip()}
    if me & owner_set:
        return True, "owner"
    if access_mode == "open":
        return True, "open"
    if access_mode == "allowlist" and email and email.strip().lower() in {a.strip().lower() for a in allow_set}:
        return True, "allowed"
    if access_mode == "paused":
        return False, "paused"
    if not owner_set:
        return False, "no_owner"
    return False, "not_open"


def check(ids: Iterable[str], email: str) -> Tuple[bool, str]:
    """decide() against the live secrets."""
    return decide(mode(), owners(), allowlist(), ids, email)
