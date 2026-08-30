"""Find the visitor's trade journal automatically after Notion sign-in.

Searches every database the user shared during OAuth and scores each one
against the known journal templates by column fingerprint — so nobody ever
has to paste a database link.
"""
from __future__ import annotations

from typing import List, Optional

import requests

from edge_analysis.data.notion_adapter import (
    _SR_SIGNATURE_COLS, _SALTY_SIGNATURE_COLS, _MT5_SIGNATURE_COLS)

_NV = {"Notion-Version": "2022-06-28"}
_LABEL = {"mt5": "MT5 Trade Log template", "sr": "SR journal template",
          "salty": "Salty journal template"}


def score_columns(prop_names) -> tuple:
    """(schema, hits) for a set of column names; ('unknown', 0) when nothing fits."""
    cols = {str(c).strip() for c in prop_names}
    scores = {"mt5": len(cols & _MT5_SIGNATURE_COLS),
              "salty": len(cols & _SALTY_SIGNATURE_COLS),
              "sr": len(cols & _SR_SIGNATURE_COLS)}
    best = max(scores, key=lambda k: scores[k])
    return (best, scores[best]) if scores[best] >= 3 else ("unknown", scores[best])


def schema_label(schema: str) -> str:
    return _LABEL.get(schema, "journal")


def find_journals(token: str, timeout: int = 10) -> Optional[List[dict]]:
    """All shared databases that look like a trade journal, best first.
    Returns None on network/auth failure (callers keep the manual path)."""
    try:
        out, cursor = [], None
        for _ in range(4):  # up to 400 shared databases
            body = {"filter": {"value": "database", "property": "object"},
                    "page_size": 100}
            if cursor:
                body["start_cursor"] = cursor
            r = requests.post("https://api.notion.com/v1/search",
                              headers={"Authorization": f"Bearer {token}",
                                       "Content-Type": "application/json", **_NV},
                              json=body, timeout=timeout)
            if r.status_code != 200:
                return None
            data = r.json() or {}
            for res in data.get("results", []):
                props = (res.get("properties") or {}).keys()
                schema, hits = score_columns(props)
                title = "".join(t.get("plain_text", "")
                                for t in (res.get("title") or [])) or "Untitled"
                out.append({"id": str(res.get("id", "")).replace("-", ""),
                            "title": title.strip(), "schema": schema, "hits": hits})
            cursor = data.get("next_cursor")
            if not data.get("has_more") or not cursor:
                break
        journals = [d for d in out if d["schema"] != "unknown"]
        journals.sort(key=lambda d: -d["hits"])
        return journals
    except Exception:
        return None


def sibling_journals(token: str, current_dbid: str, timeout: int = 10):
    """Journals living NEXT TO the current one, found without /v1/search.

    Notion's search index lags on newly shared databases (sometimes days),
    which hides a brand-new journal even though direct access works. The
    parent page of the CURRENT journal is where people create the next one —
    walk its children and probe each child database directly."""
    out = []
    try:
        hdr = {"Authorization": f"Bearer {token}", **_NV}
        r = requests.get(f"https://api.notion.com/v1/databases/{current_dbid}",
                         headers=hdr, timeout=timeout)
        if r.status_code != 200:
            return out
        parent = (r.json() or {}).get("parent") or {}
        pid = parent.get("page_id")
        if not pid:
            return out
        kids = requests.get(f"https://api.notion.com/v1/blocks/{pid}/children",
                            headers=hdr, params={"page_size": 100}, timeout=timeout)
        if kids.status_code != 200:
            return out
        for blk in (kids.json() or {}).get("results", []):
            if blk.get("type") != "child_database":
                continue
            did = str(blk.get("id", "")).replace("-", "")
            if did == str(current_dbid).replace("-", ""):
                continue
            det = requests.get(f"https://api.notion.com/v1/databases/{did}",
                               headers=hdr, timeout=timeout)
            if det.status_code != 200:
                continue
            dd = det.json() or {}
            props = (dd.get("properties") or {}).keys()
            schema, hits = score_columns(props)
            if schema == "unknown":
                continue
            title = "".join(t.get("plain_text", "")
                            for t in (dd.get("title") or [])) or "Untitled"
            out.append({"id": did, "title": title.strip(),
                        "schema": schema, "hits": hits})
    except Exception:
        pass
    return out
