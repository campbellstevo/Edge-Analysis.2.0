"""Feedback & ideas: notes are kept on disk first, copied to Notion when set up."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from edge_analysis import feedback as fb  # noqa: E402
from edge_analysis import user_store  # noqa: E402

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64


class _R:
    def __init__(self, status=200, body=None):
        self.status_code, self._b, self.headers = status, body or {}, {}

    @property
    def ok(self):
        return 200 <= self.status_code < 300

    def json(self):
        return self._b


@pytest.fixture
def box(tmp_path, monkeypatch):
    monkeypatch.setattr(fb, "_DIR", tmp_path / "inbox")
    monkeypatch.setattr(fb, "_AUTO_PAGE_ID", None)
    for k in ("FEEDBACK_NOTION_TOKEN", "FEEDBACK_PAGE_ID", "STORE_NOTION_TOKEN", "STORE_PAGE_ID"):
        monkeypatch.delenv(k, raising=False)
    return tmp_path


def _fake_notion(monkeypatch, database=False):
    calls = []

    def call(method, url, **kw):
        calls.append((method, url, kw))
        if url.endswith("/file_uploads"):
            return _R(200, {"id": "fu1"})
        if "/databases/" in url:
            return _R(200, {"properties": {"Task": {"type": "title"}}}) if database else _R(404)
        return _R(200, {"id": "p1", "results": []})
    monkeypatch.setattr(user_store, "_notion_call", call)
    return calls


def test_without_notion_the_note_is_kept_on_the_server(box):
    note = fb.submit("broken", "Plan", "Accept button does nothing", [("s.png", PNG, "image/png")],
                     who="member ab12cd34")
    assert note["notion"] is False
    kept = fb.inbox()
    assert kept[0]["text"] == "Accept button does nothing" and kept[0]["area"] == "Plan"
    assert fb.image_path(kept[0]["images"][0]).read_bytes() == PNG
    assert fb.destination()[0] == "disk"


def test_page_destination_appends_the_note_with_its_screenshot(box, monkeypatch):
    monkeypatch.setenv("FEEDBACK_NOTION_TOKEN", "t")
    monkeypatch.setenv("FEEDBACK_PAGE_ID", "page1")
    calls = _fake_notion(monkeypatch)
    note = fb.submit("idea", "Review", "Weekly email?", [("s.png", PNG, "image/png")], who="owner")
    assert note["notion"] is True and fb.inbox()[0]["notion"] is True
    urls = [c[1] for c in calls]
    assert any(u.endswith("/file_uploads/fu1/send") for u in urls)
    append = [c for c in calls if c[0] == "patch" and c[1].endswith("/blocks/page1/children")][0]
    callout = append[2]["json"]["children"][0]["callout"]
    kids = callout["children"]
    assert kids[1]["image"]["file_upload"]["id"] == "fu1"
    assert "Weekly email?" in kids[0]["paragraph"]["rich_text"][0]["text"]["content"]


def test_database_destination_gets_one_row_per_note(box, monkeypatch):
    monkeypatch.setenv("FEEDBACK_NOTION_TOKEN", "t")
    monkeypatch.setenv("FEEDBACK_PAGE_ID", "db1")
    calls = _fake_notion(monkeypatch, database=True)
    fb.submit("dislike", "Menu & settings", "Too many toggles", [], who="member x")
    row = [c for c in calls if c[0] == "post" and c[1].endswith("/pages")][0][2]["json"]
    assert row["parent"] == {"database_id": "db1"}
    assert "Too many toggles" in row["properties"]["Task"]["title"][0]["text"]["content"]


def test_store_page_is_reused_when_no_feedback_page_is_set(box, monkeypatch):
    monkeypatch.setenv("STORE_NOTION_TOKEN", "t")
    monkeypatch.setenv("STORE_PAGE_ID", "store1")
    calls = _fake_notion(monkeypatch)
    assert fb.destination()[0] == "notion"
    fb.submit("idea", "Plan", "x", [], who="owner")
    created = [c for c in calls if c[0] == "post" and c[1].endswith("/pages")][0][2]["json"]
    assert created["parent"] == {"page_id": "store1"}


def test_email_only_when_they_ask_for_a_reply(box, monkeypatch):
    monkeypatch.setenv("FEEDBACK_NOTION_TOKEN", "t")
    monkeypatch.setenv("FEEDBACK_PAGE_ID", "page1")
    calls = _fake_notion(monkeypatch)
    fb.submit("idea", "Plan", "no reply please", [], who="member 1")
    fb.submit("idea", "Plan", "reply please", [], who="member 2", reply_to="a@b.co")
    heads = [c[2]["json"]["children"][0]["callout"]["rich_text"][0]["text"]["content"]
             for c in calls if c[0] == "patch"]
    assert "a@b.co" not in heads[0] and "reply to a@b.co" in heads[1]


def test_limits_hold(box):
    big = b"0" * (fb.MAX_IMAGE_BYTES + 1)
    files = [("a.png", PNG, "image/png")] * 5 + [("big.png", big, "image/png")]
    note = fb.submit("idea", "Plan", "y" * (fb.MAX_TEXT + 50), files, who="m")
    assert len(note["images"]) == fb.MAX_IMAGES and len(note["text"]) == fb.MAX_TEXT


def test_done_and_rate_count(box):
    n = fb.submit("idea", "Plan", "one", [], who="m1")
    fb.submit("idea", "Plan", "two", [], who="m1")
    assert fb.recent_count("m1") == 2 and fb.recent_count("m2") == 0
    fb.set_done(n["id"])
    assert [i["done"] for i in fb.inbox()] == [False, True]


def test_who_hash_never_carries_the_id():
    h = fb.who_hash("notion-user-1234")
    assert len(h) == 8 and "1234" not in h
