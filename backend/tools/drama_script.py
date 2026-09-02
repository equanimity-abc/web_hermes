"""Script node helpers — draft/refine via Ark / DeepSeek / Kimi."""

from __future__ import annotations

import asyncio
from typing import Any

from llm_client import llm_client, script_provider_chain


def script_node_config(slug: str) -> dict[str, Any]:
    """Effective `script` node config for a project (three-layer merged)."""
    from tools.drama_models import load_models, models_with_overrides

    try:
        models = models_with_overrides(slug)
    except Exception:
        models = load_models(slug)
    cfg = (models or {}).get("script") if isinstance((models or {}).get("script"), dict) else {}
    provider = str(cfg.get("provider") or "ark").strip().lower() or "ark"
    if provider == "moonshot":
        provider = "kimi"
    if provider in ("volcengine", "doubao", "火山"):
        provider = "ark"
    alts = cfg.get("alternatives")
    if not isinstance(alts, list) or not alts:
        alts = ["ark", "deepseek", "kimi"]
    return {
        "provider": provider,
        "model": str(cfg.get("model") or "").strip(),
        "refine_model": str(cfg.get("refine_model") or "").strip(),
        "alternatives": [str(a).strip().lower() for a in alts if str(a).strip()],
    }


async def draft_text(
    slug: str,
    prompt: str,
    *,
    system: str = "你是专业漫剧编剧，输出简体中文。",
    temperature: float = 0.7,
) -> str:
    """Draft using project script provider; failover across ark / deepseek / kimi."""
    cfg = script_node_config(slug)
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": prompt},
    ]
    chain = script_provider_chain(cfg["provider"], cfg["alternatives"])
    preferred = chain[0]
    if preferred["provider"] == cfg["provider"] and cfg["model"]:
        model = cfg["model"]
    else:
        model = preferred["model"]
    return await llm_client.chat(
        messages,
        temperature=temperature,
        max_tokens=4096,
        model=model,
        provider=preferred["provider"],
        alternatives=True,
        alternative_providers=cfg["alternatives"],
    )


async def refine_text(
    slug: str,
    draft: str,
    *,
    instruction: str = "精修改写，保留原意并提升剧本表达。",
) -> str:
    cfg = script_node_config(slug)
    return await llm_client.refine(
        draft,
        instruction=instruction,
        model=cfg["refine_model"] or cfg["model"] or None,
        provider=cfg["provider"],
        alternative_providers=cfg["alternatives"],
    )


def draft_text_sync(slug: str, prompt: str, *, system: str = "你是专业漫剧编剧，输出简体中文。") -> str:
    return asyncio.run(draft_text(slug, prompt, system=system))


def refine_text_sync(slug: str, draft: str, *, instruction: str = "精修改写，保留原意并提升剧本表达。") -> str:
    return asyncio.run(refine_text(slug, draft, instruction=instruction))
