"""Script node helpers (P2-11).

The `script` node in models.json (provider / model / refine_model) was stored
but never consumed. This module reads the three-layer effective config and
exposes draft / refine shortcuts — so the drama plugin and future skills can
produce a flash draft then reasoner-refine it, without the core loop knowing
anything about per-project script routing.
"""

from __future__ import annotations

import asyncio
from typing import Any

from llm_client import llm_client


def script_node_config(slug: str) -> dict[str, Any]:
    """Effective `script` node config for a project (three-layer merged)."""
    from tools.drama_models import load_models, models_with_overrides

    try:
        models = models_with_overrides(slug)
    except Exception:
        models = load_models(slug)
    cfg = (models or {}).get("script") if isinstance((models or {}).get("script"), dict) else {}
    return {
        "provider": str(cfg.get("provider") or "deepseek").strip() or "deepseek",
        "model": str(cfg.get("model") or "").strip(),
        "refine_model": str(cfg.get("refine_model") or "").strip(),
    }


async def draft_text(
    slug: str,
    prompt: str,
    *,
    system: str = "你是专业漫剧编剧，输出简体中文。",
    temperature: float = 0.7,
) -> str:
    """Draft a piece of text using the project's `script.model` (default fallback)."""
    cfg = script_node_config(slug)
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": prompt},
    ]
    return await llm_client.chat(
        messages,
        temperature=temperature,
        max_tokens=4096,
        model=cfg["model"] or None,
    )


async def refine_text(
    slug: str,
    draft: str,
    *,
    instruction: str = "精修改写，保留原意并提升剧本表达。",
) -> str:
    """Refine a draft using the project's `script.refine_model` (fallback: default)."""
    cfg = script_node_config(slug)
    return await llm_client.refine(
        draft,
        instruction=instruction,
        model=cfg["refine_model"] or None,
    )


def draft_text_sync(slug: str, prompt: str, *, system: str = "你是专业漫剧编剧，输出简体中文。") -> str:
    """Synchronous wrapper for plugin dispatch (blocking tool call)."""
    return asyncio.run(draft_text(slug, prompt, system=system))


def refine_text_sync(slug: str, draft: str, *, instruction: str = "精修改写，保留原意并提升剧本表达。") -> str:
    """Synchronous wrapper for plugin dispatch (blocking tool call)."""
    return asyncio.run(refine_text(slug, draft, instruction=instruction))
