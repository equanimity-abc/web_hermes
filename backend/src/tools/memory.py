"""Memory tools — read/write the shared MEMORY.md file."""

from __future__ import annotations

import json

from agent.memory_store import memory_path, read_memory, write_memory
from tools.registry import register


def _memory_read(_args: dict) -> str:
    text = read_memory()
    return json.dumps(
        {
            "path": str(memory_path()),
            "chars": len(text),
            "content": text or "(空)",
        },
        ensure_ascii=False,
    )


def _memory_write(args: dict) -> str:
    content = args.get("content")
    if content is None:
        return json.dumps({"error": "content 不能为空"}, ensure_ascii=False)
    mode = str(args.get("mode") or "append").strip().lower()
    append = mode != "replace"
    stored = write_memory(str(content), append=append)
    return json.dumps(
        {
            "ok": True,
            "mode": "append" if append else "replace",
            "chars": len(stored),
            "path": str(memory_path()),
        },
        ensure_ascii=False,
    )


def register_memory_tools() -> None:
    register(
        "memory_read",
        description="读取跨会话长期记忆（偏好、事实、约定）。新会话也会自动注入该内容。",
        parameters={"type": "object", "properties": {}},
        handler=_memory_read,
    )
    register(
        "memory_write",
        description="写入跨会话长期记忆。mode=append（默认）追加；mode=replace 整文件覆盖。",
        parameters={
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "要写入的记忆文本（简洁条目更好）",
                },
                "mode": {
                    "type": "string",
                    "description": "append 或 replace，默认 append",
                    "enum": ["append", "replace"],
                },
            },
            "required": ["content"],
        },
        handler=_memory_write,
    )


register_memory_tools()
