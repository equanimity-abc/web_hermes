"""Minimal tool registry (P2/P3 footprint ladder: tiny core, grow at the edges)."""

from __future__ import annotations

import json
from typing import Any, Callable

Handler = Callable[[dict[str, Any]], str]

_REGISTRY: dict[str, dict[str, Any]] = {}


def register(
    name: str,
    *,
    description: str,
    parameters: dict[str, Any],
    handler: Handler,
) -> None:
    _REGISTRY[name] = {
        "name": name,
        "description": description,
        "parameters": parameters,
        "handler": handler,
    }


def openai_tools() -> list[dict[str, Any]]:
    """Schemas for chat.completions `tools=`."""
    return [
        {
            "type": "function",
            "function": {
                "name": meta["name"],
                "description": meta["description"],
                "parameters": meta["parameters"],
            },
        }
        for meta in _REGISTRY.values()
    ]


def dispatch(name: str, arguments: dict[str, Any] | str | None) -> str:
    meta = _REGISTRY.get(name)
    if not meta:
        return json.dumps({"error": f"unknown tool: {name}"}, ensure_ascii=False)

    if isinstance(arguments, str):
        try:
            args = json.loads(arguments or "{}")
        except json.JSONDecodeError:
            return json.dumps(
                {"error": "invalid JSON arguments", "raw": arguments},
                ensure_ascii=False,
            )
    else:
        args = arguments or {}

    try:
        result = meta["handler"](args)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)

    if isinstance(result, str):
        return result
    return json.dumps(result, ensure_ascii=False)


def list_tool_names() -> list[str]:
    return list(_REGISTRY.keys())
