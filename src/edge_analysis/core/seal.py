"""SEC-01: the Notion sign-in never sits in the browser in the clear.

The device remembers a login so phones don't have to go through Notion's
consent page every visit. Before this, that memory was the raw Notion token in
localStorage: anything that could read the page's storage (an extension, a
shared computer, an XSS bug) walked away with a token that reads the member's
whole Notion workspace, forever, from anywhere.

Now the browser only ever holds a sealed blob (Fernet: AES-128-CBC with an
HMAC-SHA256 tag). The key is derived on the server from a server-only secret,
so the blob is useless outside this app and can't be edited. Blobs expire
after MAX_AGE_DAYS; every visit re-seals, so anyone who comes back within that
window never has to sign in again.

Keys: `EA_SEAL_KEY` if it is set, and always one derived from the Notion
OAuth client secret. New blobs use the first; old blobs open with either, so
adding EA_SEAL_KEY later signs nobody out.
"""
from __future__ import annotations

import base64

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

PREFIX = "v1."
MAX_AGE_DAYS = 60
_SALT = b"edge-analysis/device-auth/v1"


def _fernet_key(secret: str) -> bytes:
    raw = HKDF(algorithm=hashes.SHA256(), length=32, salt=_SALT,
               info=b"ea_auth").derive(secret.encode("utf-8"))
    return base64.urlsafe_b64encode(raw)


def sealer(secrets: list[str | None]) -> MultiFernet | None:
    """A sealer from the server secrets, strongest first. None without any."""
    keys = [Fernet(_fernet_key(s)) for s in secrets if s and str(s).strip()]
    return MultiFernet(keys) if keys else None


def seal(token: str, box: MultiFernet | None) -> str | None:
    if not token or box is None:
        return None
    return PREFIX + box.encrypt(token.encode("utf-8")).decode("ascii")


def unseal(blob: str, box: MultiFernet | None, max_age_days: int = MAX_AGE_DAYS) -> str | None:
    """The token, or None when the blob is foreign, edited, expired or unreadable."""
    if not blob or box is None or not str(blob).startswith(PREFIX):
        return None
    try:
        return box.decrypt(str(blob)[len(PREFIX):].encode("ascii"),
                           ttl=int(max_age_days * 86400)).decode("utf-8")
    except (InvalidToken, ValueError, UnicodeError):
        return None
