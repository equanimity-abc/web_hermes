"""LLM 客户端 - 多厂商 OpenAI 兼容 API（DeepSeek / Kimi / 火山方舟）。

剧本与分镜默认：deepseek-v4-pro 与 kimi-k3 可互相替代（有 Key 即用，失败自动换另一家）。
"""

from __future__ import annotations

import json
import logging
import threading
from typing import Any, AsyncGenerator

import httpx

from config import config

log = logging.getLogger("llm")


class _Cancelled(Exception):
    """Raised when a caller-provided cancel_event is set mid-request."""


class UsageMeter:
    """Thread-safe, process-local LLM usage counters."""

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


def _merge_tool_calls(target: list[dict[str, Any]] | None, delta_tc: list[dict[str, Any]] | None) -> list[dict[str, Any]] | None:
    if not delta_tc:
        return target
    target = target if target is not None else []
    for dtc in delta_tc:
        idx = int(dtc.get("index") or 0)
        while len(target) <= idx:
            target.append({"id": "", "type": "function", "function": {"name": "", "arguments": ""}})
        cur = target[idx]
        d_fn = dtc.get("function") or {}
        if dtc.get("id"):
            cur["id"] = dtc["id"]
        if d_fn.get("name"):
            cur["function"]["name"] = cur["function"].get("name", "") + d_fn["name"]
        if d_fn.get("arguments"):
            cur["function"]["arguments"] = cur["function"].get("arguments", "") + d_fn["arguments"]
    return target


def llm_endpoint(provider: str | None = None) -> dict[str, str]:
    """Resolve api_key / base_url / default_model / chat_path for a provider id."""
    name = str(provider or "deepseek").strip().lower() or "deepseek"
    if name in ("kimi", "moonshot"):
        return {
            "provider": "kimi",
            "api_key": str(getattr(config, "KIMI_API_KEY", "") or "").strip(),
            "base_url": str(getattr(config, "KIMI_BASE_URL", "") or "https://api.moonshot.cn/v1").rstrip("/"),
            "model": str(getattr(config, "KIMI_MODEL", "") or "kimi-k3").strip(),
            "chat_path": "/chat/completions",
        }
    if name in ("ark", "volcengine", "火山", "doubao"):
        return {
            "provider": "ark",
            "api_key": str(getattr(config, "ARK_API_KEY", "") or "").strip(),
            "base_url": str(
                getattr(config, "ARK_BASE_URL", "") or "https://ark.cn-beijing.volces.com/api/v3"
            ).rstrip("/"),
            "model": str(getattr(config, "ARK_TEXT_MODEL", "") or "doubao-seed-character-260628").strip(),
            "chat_path": "/chat/completions",
        }
    # deepseek default
    return {
        "provider": "deepseek",
        "api_key": str(getattr(config, "DEEPSEEK_API_KEY", "") or "").strip(),
        "base_url": str(getattr(config, "DEEPSEEK_BASE_URL", "") or "https://api.deepseek.com").rstrip("/"),
        "model": str(getattr(config, "DEEPSEEK_MODEL", "") or "deepseek-v4-pro").strip(),
        "chat_path": "/v1/chat/completions",
    }


def script_provider_chain(
    preferred: str | None = None,
    alternatives: list[str] | None = None,
) -> list[dict[str, str]]:
    """Script LLMs in preference order (ark / deepseek / kimi). Only endpoints with keys."""

    def _norm(name: str) -> str:
        n = str(name or "").strip().lower()
        if n in ("moonshot",):
            return "kimi"
        if n in ("volcengine", "doubao", "火山", "ark"):
            return "ark"
        return n

    pref = _norm(preferred) or "ark"
    if pref not in ("deepseek", "kimi", "ark"):
        pref = "ark"
    order = [pref]
    alts = alternatives if isinstance(alternatives, list) and alternatives else ["ark", "deepseek", "kimi"]
    for raw in alts:
        n = _norm(raw)
        if n in ("deepseek", "kimi", "ark") and n not in order:
            order.append(n)
    for n in ("ark", "deepseek", "kimi"):
        if n not in order:
            order.append(n)

    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for name in order:
        ep = llm_endpoint(name)
        if ep["provider"] in seen:
            continue
        seen.add(ep["provider"])
        if ep["api_key"]:
            out.append(ep)
    if not out:
        out.append(llm_endpoint(pref))
    return out


def default_llm_provider() -> str:
    """First configured chat LLM (ark → deepseek → kimi)."""
    for name in ("ark", "deepseek", "kimi"):
        ep = llm_endpoint(name)
        if ep["api_key"]:
            return ep["provider"]
    return "ark"


class LLMClient:
    def __init__(self):
        self.usage = UsageMeter()

    @property
    def api_key(self) -> str:
        return llm_endpoint(default_llm_provider())["api_key"]

    @property
    def base_url(self) -> str:
        return llm_endpoint(default_llm_provider())["base_url"]

    @property
    def model(self) -> str:
        return llm_endpoint(default_llm_provider())["model"]

    def _headers(self, api_key: str) -> dict:
        return {
            "Authorization": f"Bearer {api_key}",
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
        provider: str = "deepseek",
    ) -> dict:
        body: dict[str, Any] = {
            "model": (model or "").strip() or llm_endpoint(provider)["model"],
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": stream,
        }
        # DeepSeek-specific optional flag; harmless if ignored elsewhere.
        if provider == "deepseek":
            body["thinking"] = {"type": "disabled"}
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"
        return body

    async def chat_completion(
        self,
        messages: list[dict],
        *,
        tools: list[dict] | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        model: str | None = None,
        provider: str | None = None,
        cancel_event: Any | None = None,
    ) -> dict[str, Any]:
        async for _token, msg in self.chat_completion_stream(
            messages,
            tools=tools,
            temperature=temperature,
            max_tokens=max_tokens,
            model=model,
            provider=provider,
            cancel_event=cancel_event,
            need_tokens=False,
        ):
            pass
        return msg

    async def chat_completion_stream(
        self,
        messages: list[dict],
        *,
        tools: list[dict] | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        model: str | None = None,
        provider: str | None = None,
        cancel_event: Any | None = None,
        need_tokens: bool = True,
    ) -> AsyncGenerator[tuple[str, dict[str, Any]], None]:
        ep = llm_endpoint(provider or default_llm_provider())
        chosen = (model or "").strip() or ep["model"]
        api_key = ep["api_key"]
        if not api_key:
            raise RuntimeError(f"未配置 {ep['provider']} API Key，请在设置里填写")

        timeout = httpx.Timeout(config.LLM_TIMEOUT)
        content_parts: list[str] = []
        tool_calls: list[dict[str, Any]] | None = None
        full: dict[str, Any] = {"role": "assistant", "content": None, "tool_calls": None}
        usage: dict[str, Any] = {}
        url = f"{ep['base_url']}{ep['chat_path']}"

        async with httpx.AsyncClient(timeout=timeout) as client:
            if cancel_event is not None and cancel_event.is_set():
                raise _Cancelled()
            async with client.stream(
                "POST",
                url,
                headers=self._headers(api_key),
                json=self._payload(
                    messages,
                    stream=True,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    tools=tools,
                    model=chosen,
                    provider=ep["provider"],
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
                    if cancel_event is not None and cancel_event.is_set():
                        raise _Cancelled()
                    if not line.startswith("data: "):
                        continue
                    data = line[6:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    delta = (chunk.get("choices") or [{}])[0].get("delta", {})
                    tc = delta.get("tool_calls")
                    if tc:
                        tool_calls = _merge_tool_calls(tool_calls, tc)
                        full["tool_calls"] = tool_calls
                    text = delta.get("content") or ""
                    if text:
                        content_parts.append(text)
                        full["content"] = "".join(content_parts)
                        if need_tokens:
                            yield (text, full)
                    ud = chunk.get("usage")
                    if ud:
                        usage = ud

        if full.get("content") is None and not (full.get("tool_calls") or []):
            full["content"] = ""
        self.usage.record(
            model=f"{ep['provider']}:{chosen}",
            prompt_tokens=usage.get("prompt_tokens") or 0,
            completion_tokens=usage.get("completion_tokens") or 0,
            estimated_chars=sum(len(p) for p in content_parts) if not tools else 0,
        )
        yield ("", full)

    async def chat_stream(
        self,
        messages: list[dict],
        temperature: float = 0.7,
        max_tokens: int = 4096,
        *,
        model: str | None = None,
        provider: str | None = None,
    ) -> AsyncGenerator[str, None]:
        async for tok, _full in self.chat_completion_stream(
            messages,
            tools=None,
            temperature=temperature,
            max_tokens=max_tokens,
            model=model,
            provider=provider,
            need_tokens=True,
        ):
            if tok:
                yield tok

    async def chat(
        self,
        messages: list[dict],
        temperature: float = 0.7,
        max_tokens: int = 4096,
        *,
        model: str | None = None,
        provider: str | None = None,
        alternatives: bool = False,
        alternative_providers: list[str] | None = None,
    ) -> str:
        """Chat with optional multi-provider failover when alternatives=True."""
        if alternatives:
            chain = script_provider_chain(provider, alternative_providers)
        else:
            chain = [llm_endpoint(provider)]

        last_err: Exception | None = None
        pref = str(provider or "").strip().lower()
        if pref in ("moonshot",):
            pref = "kimi"
        if pref in ("volcengine", "doubao", "火山"):
            pref = "ark"
        for ep in chain:
            try:
                use_model = (model or "").strip() or ep["model"]
                # When failover, always use that endpoint's native model unless explicit.
                if alternatives and pref and ep["provider"] != pref:
                    use_model = ep["model"]
                msg = await self.chat_completion(
                    messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    model=use_model,
                    provider=ep["provider"],
                )
                return msg.get("content") or ""
            except Exception as e:
                last_err = e
                log.warning("LLM %s failed: %s", ep["provider"], e)
                continue
        if last_err:
            raise last_err
        return ""

    async def refine(
        self,
        draft: str,
        *,
        instruction: str = "精修改写，保留原意并提升表达。",
        model: str | None = None,
        provider: str | None = None,
        alternative_providers: list[str] | None = None,
    ) -> str:
        messages = [
            {"role": "system", "content": instruction},
            {"role": "user", "content": draft},
        ]
        return await self.chat(
            messages,
            temperature=0.4,
            max_tokens=4096,
            model=model,
            provider=provider,
            alternatives=True,
            alternative_providers=alternative_providers,
        )


llm_client = LLMClient()
