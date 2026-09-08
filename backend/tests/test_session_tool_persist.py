"""Session tool_result persistence for async drama terminals."""

from __future__ import annotations

import json
from pathlib import Path

from session_store import SessionStore


def test_update_tool_result_and_assistant(tmp_path: Path):
    store = SessionStore(tmp_path / "sessions")
    session = store._create("abcd1234efgh5678")
    sid = session["id"]
    session["messages"] = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "渲一集"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "tiktok_drama", "arguments": "{}"},
                }
            ],
        },
        {"role": "tool", "tool_call_id": "call_1", "content": json.dumps({"job_id": "abc", "ok": True})},
        {"role": "assistant", "content": "已开始渲染"},
    ]
    store.save(session)

    final = json.dumps(
        {
            "job_id": "abc",
            "ok": False,
            "status": "error",
            "error": "闪烁未通过",
            "ui": {"state": "error", "line": "❌ 失败", "pct": 100},
        },
        ensure_ascii=False,
    )
    store.update_tool_result(sid, "call_1", final, assistant_content="❌ 第1集渲染失败")
    again = store.get(sid)
    tool = next(m for m in again["messages"] if m.get("role") == "tool")
    assert "闪烁未通过" in tool["content"]
    assert '"ui"' in tool["content"]
    text = next(
        m
        for m in again["messages"]
        if m.get("role") == "assistant" and not m.get("tool_calls")
    )
    assert text["content"] == "❌ 第1集渲染失败"
