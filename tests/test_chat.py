"""Round 8: the chat box knows what the rest of the site knows.

    python -m pytest tests/test_chat.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "src"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from edge_analysis.ui import chat  # noqa: E402


def _journal(n=24, seed=2):
    rng = np.random.default_rng(seed)
    rr = np.round(rng.normal(0.2, 1.1, n), 2)
    return pd.DataFrame({
        "Date": pd.date_range("2026-08-01 10:00", periods=n, freq="D"),
        "Closed RR": rr,
        "Outcome": ["Win" if x > 0.15 else ("Loss" if x < -0.15 else "BE") for x in rr],
        "Session": rng.choice(["Asian", "London", "New York"], n),
        "Planned R:R": [3.0] * n,
        "MFE (R)": np.round(np.abs(rng.normal(1.2, 0.8, n)), 2),
        "Hold Time (min)": rng.integers(2, 200, n),
        "Breakeven Criteria": [["Loss before BE"]] * 4 + [["At structure"]] * (n - 4),
        "Teachings/Learning Curve": ["Dont be greedy past TP2"] * 3 + ["Swept first, wait"] * 2 + [""] * (n - 5),
    })


def test_context_carries_the_rundown_lessons_and_last_trades():
    ctx = chat._stats_context(_journal())
    assert "RUNDOWN" in ctx and "Your record:" in ctx and "[tab: Performance]" in ctx
    assert "Targets:" in ctx and "Breakeven:" in ctx
    assert "LESSONS WRITTEN MORE THAN ONCE: Taking profit (3x" in ctx
    assert "LAST TRADES (newest first):" in ctx and ctx.count("\n- ") >= 15
    assert "<b>" not in ctx                       # the model gets plain text


def test_builtin_answers_the_new_questions():
    df = _journal()
    assert "Your record:" in chat._builtin_answer("give me the rundown", df)
    assert "reached your target on" in chat._builtin_answer("do I reach my targets?", df)
    assert "lost before breakeven" in chat._builtin_answer("what does breakeven cost me", df)
    assert "Taking profit" in chat._builtin_answer("what do my lessons say?", df)
    assert "winners held a median" in chat._builtin_answer("what's my hold time?", df)
    assert chat._builtin_answer("show my last trades", df).count("\n") == 4
    # the old intents still own their words
    assert "reached your target" not in (chat._builtin_answer("am I on pace to hit my targets this month?", df) or "")
    assert "held a median" not in (chat._builtin_answer("what's holding me back?", df) or "")


def test_md_lite_allows_bold_and_bullets_but_no_markup():
    html = chat._md_lite("**Yes.** Two things:\n- <script>x</script> first\n- **second**")
    assert "<b>Yes.</b>" in html and "<ul><li>" in html and "<b>second</b></li></ul>" in html
    assert "<script>" not in html and "&lt;script&gt;" in html


def test_llm_call_sends_the_full_context(monkeypatch):
    sent = {}

    class _R:
        status_code = 200
        def json(self): return {"content": [{"type": "text", "text": "**Asia** carries it."}]}
    monkeypatch.setattr(chat, "_secret", lambda k: {"ANTHROPIC_API_KEY": "k"}.get(k))
    monkeypatch.setattr(chat.requests, "post", lambda url, headers, json, timeout: sent.update(json) or _R())
    out = chat._ask_llm(chat._stats_context(_journal()), [("user", "where does my R come from?")])
    assert out == "**Asia** carries it."
    assert sent["model"] == "claude-sonnet-5" and sent["max_tokens"] == 700
    assert "RUNDOWN" in sent["system"] and "early read" in sent["system"]
    assert sent["messages"] == [{"role": "user", "content": "where does my R come from?"}]
