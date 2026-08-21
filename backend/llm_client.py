"""LLM 客户端 - DeepSeek / OpenAI-compatible API。

P2-14: 增加进程级用量计量（调用次数 / token）。P2-11: 支持每次调用覆盖
model，并提供草稿→精修的 refine 辅助（供 script 节点接线，不改 loop）。
"""

from __future__ import annotations

import json
import threading
from typing import Any, AsyncGenerator

import httpx

from config import config


class UsageMeter:
    """Thread-safe, process-local LLM usage counters (P2-14)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.calls = 0
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.total_tokens = 0
        self.estimated_chars = 0

    def record(
        self,
        *,
        model: str = "",
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        estimated_chars: int = 0,
    ) -> None:
        with self._lock:
            self.calls += 1
            self.prompt_tokens += max(0, int(prompt_tokens))
            self.completion_tokens += max(0, int(completion_tokens))
            self.total_tokens += max(0, int(prompt_tokens)) + max(0, int(completion_tokens))
            self.estimated_chars += max(0, int(estimated_chars))

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "calls": self.calls,
                "prompt_tokens": self.prompt_tokens,
                "completion_tokens": self.completion_tokens,
                "total_tokens": self.total_tokens,
                "estimated_chars": self.estimated_chars,
            }


class LLMClient:
    def __init__(self):
        self.api_key = config.DEEPSEEK_API_KEY
        self.base_url = config.DEEPSEEK_BASE_URL.rstrip("/")
        self.model = config.DEEPSEEK_MODEL
        self.usage = UsageMeter()

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _payload(
        self,
        messages: list[dict],
        *,
        stream: bool,
        temperature: float,
        max_tokens: int,
        tools: list[dict] | None = None,
        model: str | None = None,
    ) -> dict:
        body: dict[str, Any] = {
            "model": (model or "").strip() or self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": stream,
            "thinking": {"type": "disabled"},
        }
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"
        return body

    async def _raise_http(self, response: httpx.Response) -> None:
        if response.status_code < 400:
            return
        body = response.text
        if hasattr(response, "aread") and not body:
            try:
                body = (await response.aread()).decode("utf-8", errors="replace")
            except Exception:
                body = ""
        raise httpx.HTTPStatusError(
            f"{response.status_code} {response.reason_phrase}: {body}",
            request=response.request,
            response=response,
        )

    async def chat_completion(
        self,
        messages: list[dict],
        *,
        tools: list[dict] | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        model: str | None = None,
    ) -> dict[str, Any]:
        """Non-stream completion. Returns the assistant message dict (OpenAI shape)."""
        chosen = (model or "").strip() or self.model
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                f"{self.base_url}/v1/chat/completions",
                headers=self._headers(),
                json=self._payload(
                    messages,
                    stream=False,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    tools=tools,
                    model=chosen,
                ),
            )
            await self._raise_http(response)
            data = response.json()
            usage = data.get("usage") or {}
            self.usage.record(
                model=chosen,
                prompt_tokens=usage.get("prompt_tokens") or 0,
                completion_tokens=usage.get("completion_tokens") or 0,
            )
            message = data["choices"][0]["message"]
            # Normalize to plain dict
            return {
                "role": message.get("role", "assistant"),
                "content": message.get("content"),
                "tool_calls": message.get("tool_calls") or None,
            }

    async def chat_stream(
        self,
        messages: list[dict],
        temperature: float = 0.7,
        max_tokens: int = 4096,
        *,
        model: str | None = None,
    ) -> AsyncGenerator[str, None]:
        """Stream plain-text tokens (no tools). Used when the model will not call tools."""
        chosen = (model or "").strip() or self.model
        total = 0
        async with httpx.AsyncClient(timeout=120.0) as client:
            async with client.stream(
                "POST",
                f"{self.base_url}/v1/chat/completions",
                headers=self._headers(),
                json=self._payload(
                    messages,
                    stream=True,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    tools=None,
                    model=chosen,
                ),
            ) as response:
                if response.status_code >= 400:
                    body = (await response.aread()).decode("utf-8", errors="replace")
                    raise httpx.HTTPStatusError(
                        f"{response.status_code} {response.reason_phrase}: {body}",
                        request=response.request,
                        response=response,
                    )
                async for line in response.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    data = line[6:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                        delta = chunk.get("choices", [{}])[0].get("delta", {})
                        content = delta.get("content") or ""
                        if content:
                            total += len(content)
                            yield content
                    except json.JSONDecodeError:
                        continue
        self.usage.record(model=chosen, estimated_chars=total)

    async def chat(
        self,
        messages: list[dict],
        temperature: float = 0.7,
        max_tokens: int = 4096,
        *,
        model: str | None = None,
    ) -> str:
        msg = await self.chat_completion(
            messages, temperature=temperature, max_tokens=max_tokens, model=model
        )
        return msg.get("content") or ""

    async def refine(
        self,
        draft: str,
        *,
        instruction: str = "精修改写，保留原意并提升表达。",
        model: str | None = None,
    ) -> str:
        """P2-11: one-pass refine (draft → polished). Caller supplies the model.

        This is a library helper; the drama `script` node decides which model
        to pass (flash draft vs reasoner refine). Core loop stays untouched.
        """
        chosen = (model or "").strip() or self.model
        messages = [
            {"role": "system", "content": instruction},
            {"role": "user", "content": draft},
        ]
        return await self.chat(messages, temperature=0.4, max_tokens=4096, model=chosen)


llm_client = LLMClient()
