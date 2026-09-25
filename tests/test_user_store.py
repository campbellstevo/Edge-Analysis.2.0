"""The user store survives a redeploy and fails loudly (roadmap 1.13, 1.15).

Streamlit Cloud's disk is wiped on every deploy; the store comes back from
one Notion code block. A fake Notion here holds that block.

    python -m pytest tests/test_user_store.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from edge_analysis import user_store as us  # noqa: E402


class _Resp:
    def __init__(self, status, body=None, headers=None):
        self.status_code = status
        self.ok = 200 <= status < 300
        self._body = body or {}
        self.headers = headers or {}

    def json(self):
        return self._body


class FakeNotion:
    """One page holding (at most) one code block; can be told to answer 429
    or 500 a few times."""

    def __init__(self):
        self.rich = None
        self.fail = []  # statuses to return before behaving

    def _maybe_fail(self):
        return _Resp(self.fail.pop(0)) if self.fail else None

    def get(self, url, **kw):
        f = self._maybe_fail()
        if f:
            return f
        if self.rich is None:
            return _Resp(200, {"results": []})
        text = [{"plain_text": t["text"]["content"]} for t in self.rich]
        return _Resp(200, {"results": [{"type": "code", "id": "blk",
                                        "code": {"rich_text": text}}]})

    def patch(self, url, json=None, **kw):
        f = self._maybe_fail()
        if f:
            return f
        if url.endswith("/children"):
            self.rich = json["children"][0]["code"]["rich_text"]
            return _Resp(200, {"results": [{"type": "code", "id": "blk"}]})
        self.rich = json["code"]["rich_text"]
        return _Resp(200, {"id": "blk"})


@pytest.fixture
def notion(monkeypatch, tmp_path):
    import requests
    fake = FakeNotion()
    monkeypatch.setattr(requests, "get", fake.get)
    monkeypatch.setattr(requests, "patch", fake.patch)
    monkeypatch.setattr(us, "_mirror_cfg", lambda: ("page", "tok"))
    monkeypatch.setattr(us, "_STORE_FILE", tmp_path / "store.json")
    monkeypatch.setattr(us.time, "sleep", lambda s: None)
    monkeypatch.setattr(us, "_MIRROR_BLOCK_ID", None)
    monkeypatch.setattr(us, "_MIRROR_CHECKED", False)
    us._MIRROR_STATUS.update(ok_at=None, error=None, chars=0)
    return fake


def _redeploy(monkeypatch):
    """A fresh process on a wiped disk."""
    us._STORE_FILE.unlink(missing_ok=True)
    monkeypatch.setattr(us, "_MIRROR_BLOCK_ID", None)
    monkeypatch.setattr(us, "_MIRROR_CHECKED", False)


def test_a_member_registered_before_a_redeploy_is_still_registered_after(notion, monkeypatch):
    us.set_user_db("member-1", "db-1", template="salty")
    us.set_user_db("owner", "db-2", template="mt5")
    assert us.mirror_status()["ok_at"]
    _redeploy(monkeypatch)
    assert us.get_user("member-1")["db_id"] == "db-1"
    assert us.get_user("owner")["db_id"] == "db-2"


def test_a_429_is_retried(notion):
    notion.fail = [429, 429]
    us.set_user_db("m", "d")
    assert us.mirror_status()["error"] is None
    assert notion.rich


def test_a_refused_write_is_reported(notion, monkeypatch):
    us.set_user_db("m", "d")  # creates the block
    notion.fail = [500]
    us.set_user_db("m2", "d2")
    assert "HTTP 500" in (us.mirror_status()["error"] or "")


def test_a_store_too_big_for_the_mirror_is_refused_not_cut_off(notion, monkeypatch):
    import json
    us.set_user_db("keep-me", "db-keep")
    monkeypatch.setattr(us, "MIRROR_CAPACITY", 400)
    for i in range(20):
        us.set_user_db(f"user-{i}", f"db-{i}")
    assert "FULL" in (us.mirror_status()["error"] or "")
    # the mirror holds the last copy that fitted — whole, never cut off
    stored = json.loads("".join(t["text"]["content"] for t in notion.rich))
    assert "keep-me" in stored["users"] and len(stored["users"]) < 21
    _redeploy(monkeypatch)
    assert us.get_user("keep-me")["db_id"] == "db-keep"


def test_capacity_holds_well_over_a_thousand_members():
    rec = {"db_id": "0" * 32, "template": "salty", "last_updated": 1790000000,
           "llm_usage": {"day": "2026-10-23", "n": 3}}
    import json
    per_user = len(json.dumps({"x" * 36: rec}, separators=(",", ":")))
    assert us.MIRROR_CAPACITY // per_user > 1000
