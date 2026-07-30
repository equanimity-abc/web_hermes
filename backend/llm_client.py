"""LLM 客户端 - DeepSeek / OpenAI-compatible API。"""

from __future__ import annotations

import json
from typing import Any, AsyncGenerator

import httpx

from config import config


class LLMClient:
    def __init__(self):
        self.api_key = config.DEEPSEEK_API_KEY
        self.base_url = config.DEEPSEEK_BASE_URL.rstrip("/")
        self.model = config.DEEPSEEK_MODEL

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
    ) -> dict:
        body: dict[str, Any] = {
            "model": self.model,
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
    ) -> dict[str, Any]:
        """Non-stream completion. Returns the assistant message dict (OpenAI shape)."""
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
                ),
            )
            await self._raise_http(response)
            data = response.json()
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
    ) -> AsyncGenerator[str, None]:
        """Stream plain-text tokens (no tools). Used when the model will not call tools."""
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
                            yield content
                    except json.JSONDecodeError:
                        continue

    async def chat(
        self, messages: list[dict], temperature: float = 0.7, max_tokens: int = 4096
    ) -> str:
        msg = await self.chat_completion(
            messages, temperature=temperature, max_tokens=max_tokens
        )
        return msg.get("content") or ""


llm_client = LLMClient()
