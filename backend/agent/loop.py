"""Slim agent loop — Hermes-inspired, not a copy of run_agent.py.

Contract:
  while turns < max_turns:
    msg = LLM(messages, tools)
    if msg.tool_calls:
      append assistant(tool_calls)
      for each call: dispatch → append role=tool
      continue
    else:
      append assistant(content) → done
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from config import config
from llm_client import LLMClient, llm_client
from tools import dispatch, openai_tools

EventCallback = Callable[[dict[str, Any]], Awaitable[None] | None]


class Agent:
    def __init__(
        self,
        client: LLMClient | None = None,
        *,
        max_turns: int | None = None,
    ):
        self.client = client or llm_client
        self.max_turns = max_turns if max_turns is not None else config.AGENT_MAX_TURNS

    async def run(
        self,
        messages: list[dict[str, Any]],
        *,
        use_tools: bool = True,
        on_event: EventCallback | None = None,
    ) -> str:
        """Run the agent loop in-place on `messages`. Returns final assistant text."""
        tools = openai_tools() if use_tools else None

        async def emit(event: dict[str, Any]) -> None:
            if on_event:
                result = on_event(event)
                if hasattr(result, "__await__"):
                    await result  # type: ignore[misc]

        for _ in range(self.max_turns):
            msg = await self.client.chat_completion(messages, tools=tools)
            tool_calls = msg.get("tool_calls") or []

            if tool_calls:
                messages.append(
                    {
                        "role": "assistant",
                        "content": msg.get("content"),
                        "tool_calls": tool_calls,
                    }
                )
                await emit({"type": "assistant_tools", "tool_calls": tool_calls})

                for tc in tool_calls:
                    fn = tc.get("function") or {}
                    name = fn.get("name") or ""
                    raw_args = fn.get("arguments") or "{}"
                    tc_id = tc.get("id") or ""

                    await emit(
                        {
                            "type": "tool",
                            "name": name,
                            "arguments": raw_args,
                            "tool_call_id": tc_id,
                        }
                    )
                    result = dispatch(name, raw_args)
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc_id,
                            "name": name,
                            "content": result,
                        }
                    )
                    await emit(
                        {
                            "type": "tool_result",
                            "name": name,
                            "tool_call_id": tc_id,
                            "content": result,
                        }
                    )
                continue

            final = msg.get("content") or ""
            messages.append({"role": "assistant", "content": final})
            await emit({"type": "final", "content": final})
            return final

        final = f"（已达到最大工具轮次 {self.max_turns}，请重试或简化问题）"
        messages.append({"role": "assistant", "content": final})
        await emit({"type": "final", "content": final})
        return final

    async def run_stream(
        self,
        messages: list[dict[str, Any]],
        *,
        use_tools: bool = True,
        cancel_event: Any | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Yield SSE-oriented events while running the loop.

        Event shapes:
          {"type": "status", "text": "..."}
          {"type": "tool", "name": "...", "arguments": "..."}
          {"type": "tool_result", ...}
          {"type": "token", "text": "..."}
          {"type": "cancelled"}
          {"type": "error", "message": "..."}
        """
        tools = openai_tools() if use_tools else None

        def cancelled() -> bool:
            return bool(cancel_event is not None and cancel_event.is_set())

        try:
            for _ in range(self.max_turns):
                if cancelled():
                    yield {"type": "cancelled"}
                    return

                if tools:
                    msg = await self.client.chat_completion(messages, tools=tools)
                    if cancelled():
                        yield {"type": "cancelled"}
                        return

                    tool_calls = msg.get("tool_calls") or []

                    if tool_calls:
                        messages.append(
                            {
                                "role": "assistant",
                                "content": msg.get("content"),
                                "tool_calls": tool_calls,
                            }
                        )
                        for tc in tool_calls:
                            if cancelled():
                                # Keep OpenAI alternation valid: every tool_call needs a result.
                                for remaining in tool_calls:
                                    rid = remaining.get("id") or ""
                                    already = any(
                                        m.get("role") == "tool"
                                        and m.get("tool_call_id") == rid
                                        for m in messages
                                    )
                                    if already:
                                        continue
                                    rfn = remaining.get("function") or {}
                                    rname = rfn.get("name") or ""
                                    messages.append(
                                        {
                                            "role": "tool",
                                            "tool_call_id": rid,
                                            "name": rname,
                                            "content": json.dumps(
                                                {"error": "cancelled"},
                                                ensure_ascii=False,
                                            ),
                                        }
                                    )
                                yield {"type": "cancelled"}
                                return
                            fn = tc.get("function") or {}
                            name = fn.get("name") or ""
                            raw_args = fn.get("arguments") or "{}"
                            tc_id = tc.get("id") or ""
                            yield {
                                "type": "tool",
                                "name": name,
                                "arguments": raw_args,
                                "tool_call_id": tc_id,
                            }
                            yield {
                                "type": "status",
                                "text": f"正在调用工具：{name}",
                            }
                            result = dispatch(name, raw_args)
                            messages.append(
                                {
                                    "role": "tool",
                                    "tool_call_id": tc_id,
                                    "name": name,
                                    "content": result,
                                }
                            )
                            yield {
                                "type": "tool_result",
                                "name": name,
                                "tool_call_id": tc_id,
                                "content": result,
                            }
                        continue

                    final = msg.get("content") or ""
                    messages.append({"role": "assistant", "content": final})
                    chunk_size = 24
                    for i in range(0, len(final), chunk_size):
                        if cancelled():
                            yield {"type": "cancelled"}
                            return
                        yield {"type": "token", "text": final[i : i + chunk_size]}
                    return

                full = ""
                async for token in self.client.chat_stream(messages):
                    if cancelled():
                        if full:
                            messages.append({"role": "assistant", "content": full})
                        yield {"type": "cancelled"}
                        return
                    full += token
                    yield {"type": "token", "text": token}
                messages.append({"role": "assistant", "content": full})
                return

            final = f"（已达到最大工具轮次 {self.max_turns}）"
            messages.append({"role": "assistant", "content": final})
            yield {"type": "token", "text": final}
        except Exception as e:
            yield {"type": "error", "message": str(e)}


agent = Agent()


def messages_for_api(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Strip UI-only fields before sending to the model."""
    cleaned: list[dict[str, Any]] = []
    for m in messages:
        role = m.get("role")
        if role == "tool":
            item: dict[str, Any] = {
                "role": "tool",
                "tool_call_id": m.get("tool_call_id"),
                "content": m.get("content") or "",
            }
            if m.get("name"):
                item["name"] = m["name"]
            cleaned.append(item)
        elif role == "assistant":
            item = {"role": "assistant", "content": m.get("content")}
            if m.get("tool_calls"):
                item["tool_calls"] = m["tool_calls"]
            cleaned.append(item)
        elif role in ("system", "user"):
            cleaned.append({"role": role, "content": m.get("content") or ""})
    return cleaned


def dump_tool_preview(arguments: str, limit: int = 120) -> str:
    try:
        parsed = json.loads(arguments or "{}")
        text = json.dumps(parsed, ensure_ascii=False)
    except json.JSONDecodeError:
        text = arguments or ""
    return text if len(text) <= limit else text[: limit - 1] + "…"
