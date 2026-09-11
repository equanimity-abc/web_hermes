"""Context compression — summarize older turns when history grows too large.

Invariants:
  - Keep the first system message intact (byte-stable base prompt within a session).
  - Never split an assistant(tool_calls) + tool results group.
  - Insert a summary bridge so role alternation stays valid (no double user/assistant).
"""

from __future__ import annotations

import json
from typing import Any

from config import config
from llm_client import LLMClient, llm_client


def estimate_chars(messages: list[dict[str, Any]]) -> int:
    total = 0
    for m in messages:
        total += len(str(m.get("content") or ""))
        for tc in m.get("tool_calls") or []:
            fn = tc.get("function") or {}
            total += len(str(fn.get("name") or ""))
            total += len(str(fn.get("arguments") or ""))
    return total


def _snap_recent_start(messages: list[dict[str, Any]], start: int) -> int:
    """Move start so recent region does not begin mid tool-group."""
    start = max(1, min(start, len(messages)))
    while start < len(messages) and messages[start].get("role") == "tool":
        start -= 1
        if start <= 1:
            break
    return max(1, start)


def _flatten_for_summary(messages: list[dict[str, Any]], limit: int = 12_000) -> str:
    parts: list[str] = []
    for m in messages:
        role = m.get("role")
        if role == "system":
            continue
        content = str(m.get("content") or "").strip()
        if role == "user" and content:
            parts.append(f"用户: {content}")
        elif role == "assistant":
            if m.get("tool_calls"):
                names = []
                for tc in m["tool_calls"]:
                    fn = tc.get("function") or {}
                    names.append(str(fn.get("name") or "tool"))
                parts.append(f"助手: [调用工具 {', '.join(names)}]")
            if content:
                parts.append(f"助手: {content}")
        elif role == "tool":
            name = m.get("name") or "tool"
            preview = content[:200] + ("…" if len(content) > 200 else "")
            parts.append(f"工具({name}): {preview}")
    text = "\n".join(parts)
    if len(text) > limit:
        text = text[:limit] + "\n…"
    return text


def _heuristic_summary(messages: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for m in messages:
        if m.get("role") != "user":
            continue
        text = str(m.get("content") or "").strip().replace("\n", " ")
        if not text or text.startswith("[此前对话摘要]"):
            continue
        lines.append("- " + (text[:120] + ("…" if len(text) > 120 else "")))
        if len(lines) >= 12:
            break
    if not lines:
        return "此前有多轮对话与工具调用，细节已压缩。"
    return "此前对话要点：\n" + "\n".join(lines)


async def _llm_summary(client: LLMClient, transcript: str) -> str:
    prompt = [
        {
            "role": "system",
            "content": (
                "你是对话摘要器。根据记录写出简洁中文摘要，保留："
                "用户目标、关键事实/偏好、已完成步骤、未完成事项、重要文件路径。"
                "不要编造。不超过 400 字。"
            ),
        },
        {"role": "user", "content": transcript or "(空)"},
    ]
    msg = await client.chat_completion(
        prompt, tools=None, temperature=0.2, max_tokens=600
    )
    text = (msg.get("content") or "").strip()
    return text or _heuristic_summary([])


def _bridge_messages(
    summary: str, recent: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Attach summary without stacking two users or two assistants."""
    summary_user = {
        "role": "user",
        "content": f"[此前对话摘要]\n{summary}",
    }
    if not recent:
        return [
            summary_user,
            {"role": "assistant", "content": "好的，我已了解此前对话的要点，我们继续。"},
        ]

    first_role = recent[0].get("role")
    if first_role == "user":
        first = dict(recent[0])
        first["content"] = (
            f"[此前对话摘要]\n{summary}\n\n---\n" + str(first.get("content") or "")
        )
        return [first] + recent[1:]
    if first_role == "assistant":
        return [summary_user] + recent
    # tool at head should have been snapped away; keep a valid user/assistant pair
    return [
        summary_user,
        {"role": "assistant", "content": "好的，我已了解此前对话的要点，我们继续。"},
    ] + recent


async def maybe_compress(
    messages: list[dict[str, Any]],
    *,
    client: LLMClient | None = None,
    max_chars: int | None = None,
    keep_recent: int | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Return (messages, info). info.compressed True when a summary bridge was inserted."""
    max_chars = max_chars if max_chars is not None else config.CONTEXT_MAX_CHARS
    keep_recent = keep_recent if keep_recent is not None else config.CONTEXT_KEEP_RECENT
    info: dict[str, Any] = {
        "compressed": False,
        "before_chars": estimate_chars(messages),
        "after_chars": 0,
        "removed": 0,
    }

    if len(messages) < keep_recent + 3:
        info["after_chars"] = info["before_chars"]
        return messages, info
    if info["before_chars"] <= max_chars:
        info["after_chars"] = info["before_chars"]
        return messages, info

    start = _snap_recent_start(messages, len(messages) - keep_recent)
    if start <= 1:
        info["after_chars"] = info["before_chars"]
        return messages, info

    head = messages[:1]
    old = messages[1:start]
    recent = messages[start:]
    if not old:
        info["after_chars"] = info["before_chars"]
        return messages, info

    transcript = _flatten_for_summary(old)
    try:
        summary = await _llm_summary(client or llm_client, transcript)
    except Exception:
        summary = _heuristic_summary(old)

    new_messages = head + _bridge_messages(summary, recent)
    info["compressed"] = True
    info["removed"] = len(old)
    info["after_chars"] = estimate_chars(new_messages)
    return new_messages, info


def dump_compress_preview(info: dict[str, Any]) -> str:
    return json.dumps(info, ensure_ascii=False)
