"""End-of-week / end-of-month scorecard, R only, that goes into Notion.

His note (27 Sep): "I like that end of week or end of month scorecard that you
can send into the Notion ... maybe that would be good in the refined section."

One period (this or last week, this or last month) of the book in view:
the result, the process, where it came from, how trades were managed and the
lessons written, as markdown to paste into Notion, a download, or a page
created next to the journal when the Notion connection may insert content.
No dollars anywhere.
"""
from __future__ import annotations

from typing import Optional

import pandas as pd
import requests

from edge_analysis.core.clock import local_now

PERIODS = ["This week", "Last week", "This month", "Last month"]
_API = "https://api.notion.com/v1"
_NV = {"Notion-Version": "2022-06-28"}


def _txt(v) -> str:
    from edge_analysis.ui.reshape import _txt as t
    return t(v)


def _r(v: float, d: int = 1) -> str:
    return f"{v:+.{d}f}R".replace("-", "−")


def period_bounds(kind: str, now: Optional[pd.Timestamp] = None):
    now = now if now is not None else local_now()
    if getattr(now, "tzinfo", None) is not None:
        now = now.tz_localize(None)
    if kind in ("This week", "Last week"):
        p = pd.Period(now, "W-SUN") - (1 if kind == "Last week" else 0)
        return p, f"Week of {p.start_time.strftime('%-d %b %Y')}"
    p = pd.Period(now, "M") - (1 if kind == "Last month" else 0)
    return p, p.start_time.strftime("%B %Y")


def build(g: pd.DataFrame, kind: str, now: Optional[pd.Timestamp] = None) -> Optional[dict]:
    """g: the journal with __dt and __rr (focus.dated). None when the period
    has no trades."""
    if g is None or g.empty:
        return None
    p, title = period_bounds(kind, now)
    per = g["__dt"].dt.to_period(p.freqstr)
    w = g[per == p]
    if w.empty:
        return {"title": title, "kind": kind, "n": 0}
    from edge_analysis.ui.focus import _res_series
    from edge_analysis.ui import lessons as _ls, reshape as _rx
    rr = w["__rr"]
    res = _res_series(w)
    sc = {"title": title, "kind": kind, "n": len(w), "net": float(rr.sum()), "exp": float(rr.mean()),
          "win": int((res == "win").sum()), "be": int((res == "be").sum()), "loss": int((res == "loss").sum()),
          "best": float(rr.max()), "worst": float(rr.min())}
    if "Rules Followed?" in w.columns:
        rf = w["Rules Followed?"].map(_rx._yes)
        sc["rules"] = (int((rf == True).sum()), int(rf.notna().sum()), int(rf.isna().sum()))  # noqa: E712
    if "Mistake" in w.columns:
        mk = w["Mistake"].map(_txt).str.split(r"\s*,\s*").explode().str.strip()
        mk = mk[~mk.str.lower().isin(["", "na", "none", "no mistake"])]
        sc["mistakes"] = [(k, int(v)) for k, v in mk.value_counts().items()]
    sess = next((c for c in ("Session Norm", "Session") if c in w.columns), None)
    if sess:
        by = rr.groupby(w[sess].map(_txt)).agg(["sum", "count"])
        by = by[by.index.str.len() > 0]
        if len(by) >= 2:
            sc["best_sess"] = (by["sum"].idxmax(), float(by["sum"].max()), int(by.loc[by["sum"].idxmax(), "count"]))
            sc["worst_sess"] = (by["sum"].idxmin(), float(by["sum"].min()), int(by.loc[by["sum"].idxmin(), "count"]))
    tg = _rx.targets_frame(w.assign(**{"Closed RR": rr}) if "Closed RR" not in w.columns else w)
    if tg is not None:
        ts = _rx.targets_summary(tg)
        sc["targets"] = (ts["reached"], ts["n"])
    if "Breakeven Criteria" in w.columns:
        be = w["Breakeven Criteria"].map(_txt).str.split(",").str[0].str.strip()
        bad = be.str.contains(r"loss before|failed", case=False, regex=True, na=False)
        if bad.any():
            sc["lost_before_be"] = (int(bad.sum()), float(rr[bad].sum()))
    lf = _ls.lessons_frame(w)
    sc["lessons"] = list(lf["text"].head(6))
    grp = _ls.summary(g)["groups"]
    if grp:
        sc["focus"] = (_ls.THEME_CHECK.get(grp[0]["theme"], grp[0]["theme"]), grp[0]["theme"], grp[0]["n"])
    return sc


def to_markdown(sc: dict) -> str:
    if not sc or not sc.get("n"):
        return f"# Scorecard · {sc.get('title', '')}\n\nNo trades in this period."
    L = [f"# Scorecard · {sc['title']}", "",
         f"**{_r(sc['net'])}** over {sc['n']} trade{'s' if sc['n'] != 1 else ''} · {_r(sc['exp'], 2)} a trade "
         f"· {sc['win']} won, {sc['be']} break-even, {sc['loss']} lost · best {_r(sc['best'])}, "
         f"worst {_r(sc['worst'])}", "", "## Process"]
    if "rules" in sc:
        k, known, untagged = sc["rules"]
        L.append(f"- Rules followed on **{k} of {known}** tagged trades"
                 + (f" ({untagged} not tagged)" if untagged else ""))
    if sc.get("mistakes"):
        L.append("- Mistakes logged: " + ", ".join(f"{m} ×{c}" for m, c in sc["mistakes"]))
    elif "mistakes" in sc:
        L.append("- No mistakes logged")
    if "best_sess" in sc or "targets" in sc or "lost_before_be" in sc:
        L += ["", "## Where it came from"]
        if "best_sess" in sc:
            b, w_ = sc["best_sess"], sc["worst_sess"]
            L.append(f"- Best session: {b[0]} ({_r(b[1])} over {b[2]})")
            if w_[0] != b[0]:
                L.append(f"- Weakest session: {w_[0]} ({_r(w_[1])} over {w_[2]})")
        if "targets" in sc:
            L.append(f"- Price reached the target on {sc['targets'][0]} of {sc['targets'][1]} trades")
        if "lost_before_be" in sc:
            n_, r_ = sc["lost_before_be"]
            L.append(f"- {n_} trade{'s' if n_ != 1 else ''} lost before breakeven was set ({_r(r_)})")
    if sc.get("lessons"):
        L += ["", "## Lessons written"] + [f"- {x}" for x in sc["lessons"]]
    if sc.get("focus"):
        q, theme, n = sc["focus"]
        L += ["", "## Next period", f"- {q} (the lesson you've written most: {theme.lower()}, {n}×)"]
    L += ["", "_From Edge Analysis. R only, no dollar figures._"]
    return "\n".join(L)


def _rich(text: str) -> list:
    """Markdown **bold** into Notion rich text."""
    out, parts = [], str(text).split("**")
    for i, part in enumerate(parts):
        if part:
            out.append({"type": "text", "text": {"content": part[:1900]},
                        "annotations": {"bold": bool(i % 2)}})
    return out or [{"type": "text", "text": {"content": ""}}]


def notion_blocks(md: str) -> list:
    blocks = []
    for line in md.splitlines()[1:]:          # the H1 becomes the page title
        if not line.strip():
            continue
        if line.startswith("## "):
            blocks.append({"object": "block", "type": "heading_2", "heading_2": {"rich_text": _rich(line[3:])}})
        elif line.startswith("- "):
            blocks.append({"object": "block", "type": "bulleted_list_item",
                           "bulleted_list_item": {"rich_text": _rich(line[2:])}})
        else:
            txt = line.strip("_")
            blocks.append({"object": "block", "type": "paragraph", "paragraph": {"rich_text": _rich(txt)}})
    return blocks[:90]


def send_to_notion(token: str, database_id: str, title: str, md: str) -> tuple[bool, str]:
    """Create the scorecard as a page beside the journal (same parent page).
    Returns (ok, url or a plain reason)."""
    if not token or not database_id:
        return False, "Connect your Notion journal first."
    h = {"Authorization": f"Bearer {token}", "Content-Type": "application/json", **_NV}
    try:
        r = requests.get(f"{_API}/databases/{database_id}", headers=h, timeout=15)
        if r.status_code != 200:
            return False, "Edge Analysis couldn't read where your journal lives in Notion."
        parent = (r.json() or {}).get("parent") or {}
        if parent.get("type") != "page_id":
            return False, ("Your journal sits at the top of your workspace, and Notion won't let apps "
                           "add pages there. Copy the scorecard instead.")
        body = {"parent": {"page_id": parent["page_id"]},
                "properties": {"title": {"title": [{"type": "text", "text": {"content": f"Scorecard · {title}"}}]}},
                "children": notion_blocks(md)}
        r = requests.post(f"{_API}/pages", headers=h, json=body, timeout=20)
        if r.status_code == 200:
            return True, str((r.json() or {}).get("url") or "")
        if r.status_code in (401, 403):
            return False, ("Your Notion connection can read but not add pages. In Notion: Settings → "
                           "Connections → Edge Analysis, allow it to insert content, or copy the "
                           "scorecard instead.")
        return False, f"Notion said no (error {r.status_code}). Copy the scorecard instead."
    except requests.RequestException:
        return False, "Couldn't reach Notion just now. Copy the scorecard instead."
