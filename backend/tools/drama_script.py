"""Script node helpers — draft/refine via Ark / DeepSeek / Kimi."""

from __future__ import annotations

import asyncio
import re
from typing import Any

from llm_client import llm_client, script_provider_chain

_SCRIPT_START_RE = re.compile(
    r"^(?:#\s+\S|##\s*分镜|###\s*Shot\b)",
    re.I,
)
_SCRIPT_LINE_RE = re.compile(
    r"^(?:#{1,3}\s|"
    r"-\s*\*{0,2}(?:时长|钩子|悬念|画面|字幕|旁白|角色|对白)\*{0,2}\s*[:：]|"
    r"```)",
)
_TRAILING_PROSE_RE = re.compile(
    r"^(?:"
    r"好的|当然|可以|没问题|以下是|以上是|已按|已经|我已|我已经|"
    r"主要改动|改动说明|说明|注[:：]|希望|如果还需要|如需|需要的话|"
    r"总结|变更摘要|修改说明|Here's|Here is|Sure|I've|I have"
    r")",
    re.I,
)

_REFINE_SYSTEM = (
    "你是专业竖屏漫剧编剧。按用户修改要求改写剧本 Markdown。\n"
    "硬性规则：\n"
    "1. 只输出完整剧本 Markdown 正文，从标题行（# …）或分镜（## 分镜 / ### Shot）开始；\n"
    "2. 禁止任何开场白、解释、改动说明、总结、希望语、列表点评；\n"
    "3. 禁止用 ``` 代码围栏包裹；\n"
    "4. 保留原有结构字段：标题、时长/钩子/悬念、### Shot N (…s)、画面/字幕/旁白/角色；\n"
    "5. 用户修改要求只影响剧情与文案，不要把要求本身写进剧本。"
)


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


def strip_script_code_fence(text: str) -> str:
    """Remove a single outer ``` / ```markdown fence if present."""
    raw = str(text or "").strip()
    if not raw.startswith("```"):
        return raw
    lines = raw.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


def scrub_script_markdown(text: str) -> str:
    """Keep only the compact episode script; drop LLM preamble/postamble."""
    raw = strip_script_code_fence(text)
    if not raw:
        return ""

    lines = raw.replace("\r\n", "\n").split("\n")
    start = 0
    for i, line in enumerate(lines):
        if _SCRIPT_START_RE.match(line.strip()):
            start = i
            break

    body = lines[start:]
    # Drop leading commentary still before the first real script line
    while body and not _SCRIPT_START_RE.match(body[0].strip()) and not body[0].strip().startswith("#"):
        # If nothing looks like a script heading, keep original body from first non-empty
        break

    end = len(body)
    for i in range(len(body)):
        s = body[i].strip()
        if not s:
            # Look ahead: blank then prose → cut here if we already have shots
            j = i + 1
            while j < len(body) and not body[j].strip():
                j += 1
            if j >= len(body):
                end = i
                break
            nxt = body[j].strip()
            if (
                _TRAILING_PROSE_RE.match(nxt)
                and not _SCRIPT_LINE_RE.match(nxt)
                and not _SCRIPT_START_RE.match(nxt)
            ):
                # Only cut if we've already seen at least one Shot heading
                prior = "\n".join(body[:i])
                if re.search(r"^###\s*Shot\b", prior, re.M | re.I) or re.search(
                    r"^#\s+", prior, re.M
                ):
                    end = i
                    break
            continue
        if i > 0 and _TRAILING_PROSE_RE.match(s) and not _SCRIPT_LINE_RE.match(s):
            prior = "\n".join(body[:i])
            if re.search(r"^###\s*Shot\b", prior, re.M | re.I):
                end = i
                break

    cleaned = "\n".join(body[:end]).strip()
    # Prefer parse→rebuild when shots exist, so residual mid-doc chatter is gone
    try:
        from tools.drama_video import parse_episode_markdown

        parsed = parse_episode_markdown(cleaned)
        shots = parsed.get("shots") or []
        if shots:
            return format_episode_markdown(parsed)
    except Exception:
        pass
    return cleaned


def format_episode_markdown(parsed: dict[str, Any]) -> str:
    """Rebuild compact script markdown from parse_episode_markdown output."""
    title = str(parsed.get("title") or "").strip() or "标题"
    meta = parsed.get("meta") if isinstance(parsed.get("meta"), dict) else {}
    shots = parsed.get("shots") if isinstance(parsed.get("shots"), list) else []

    lines: list[str] = [f"# {title}"]
    for key in ("时长", "钩子", "悬念"):
        val = str(meta.get(key) or "").strip()
        if val:
            lines.append(f"- {key}: {val}")
    lines.append("")
    lines.append("## 分镜")
    for shot in shots:
        if not isinstance(shot, dict):
            continue
        try:
            n = int(shot.get("n") or 0)
        except (TypeError, ValueError):
            continue
        if n <= 0:
            continue
        timing = str(shot.get("timing") or "").strip()
        head = f"### Shot {n}" + (f" ({timing})" if timing else "")
        lines.append(head)
        for key in ("画面", "字幕", "旁白", "角色"):
            val = str(shot.get(key) or "").strip()
            if val:
                lines.append(f"- {key}: {val}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _refine_instruction(user_instruction: str) -> str:
    want = str(user_instruction or "").strip() or "精修改写，保留原意并提升剧本表达。"
    return f"{_REFINE_SYSTEM}\n\n用户修改要求：{want}"


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
    raw = await llm_client.refine(
        draft,
        instruction=_refine_instruction(instruction),
        model=cfg["refine_model"] or cfg["model"] or None,
        provider=cfg["provider"],
        alternative_providers=cfg["alternatives"],
    )
    cleaned = scrub_script_markdown(raw)
    return cleaned or scrub_script_markdown(draft) or str(draft or "").strip()


def draft_text_sync(slug: str, prompt: str, *, system: str = "你是专业漫剧编剧，输出简体中文。") -> str:
    return asyncio.run(draft_text(slug, prompt, system=system))


def refine_text_sync(slug: str, draft: str, *, instruction: str = "精修改写，保留原意并提升剧本表达。") -> str:
    return asyncio.run(refine_text(slug, draft, instruction=instruction))
