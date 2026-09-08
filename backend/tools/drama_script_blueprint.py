"""Step-1 script blueprint: rich structured bible + episode script prompts & materialize."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from tools.workspace import resolve_safe

_ASSET_FIELD_RE = re.compile(r"^-\s*\*{0,2}([^\*{：:]+)(?:\*{0,2})\s*[:：]\s*(.*)$")

_META_KEYS = ("时长", "钩子", "悬念", "配乐")
_CAST_FIELDS = ("外形", "性格", "音色倾向", "口头禅", "别名")
_LOC_FIELDS = ("描述", "光影色调", "标志物")
_PROP_FIELDS = ("描述", "材质外形", "剧情作用")

_SECTION_ALIASES = {
    "角色设定": "cast",
    "角色表": "cast",
    "人物设定": "cast",
    "场景设定": "locations",
    "地点设定": "locations",
    "场景表": "locations",
    "道具设定": "props",
    "道具表": "props",
    "物品设定": "props",
}


def bible_outline_paths(slug: str) -> tuple[Path, Path]:
    root = resolve_safe(f"dramas/{slug}")
    return root / "bible.md", root / "outline.md"


def load_bible_outline(slug: str) -> tuple[str, str]:
    bible_p, outline_p = bible_outline_paths(slug)
    bible = bible_p.read_text(encoding="utf-8") if bible_p.is_file() else ""
    outline = outline_p.read_text(encoding="utf-8") if outline_p.is_file() else ""
    return bible.strip(), outline.strip()


def ensure_bible_and_outline(
    slug: str,
    premise: str,
    *,
    title: str = "",
    series: dict[str, Any] | None = None,
) -> dict[str, str]:
    """Create bible+outline once if missing; enrich template includes scenes/props/BGM."""
    bible, outline = load_bible_outline(slug)
    if bible and outline:
        return {"bible": bible, "outline": outline}

    from tools.drama_common import load_project
    from tools.drama_produce import generate_bible_and_outline

    project = load_project(slug)
    ep_title = str(title or project.get("title") or "").strip() or "未命名漫剧"
    return generate_bible_and_outline(
        slug,
        premise,
        ep_title,
        series=series,
    )


def truncate_context(text: str, *, limit: int = 3500) -> str:
    raw = str(text or "").strip()
    if len(raw) <= limit:
        return raw
    return raw[: limit - 20].rstrip() + "\n…（已截断）"


def build_episode_script_system(
    *,
    title_line: str,
    ep_sec: int,
    shot_lo: int,
    shot_hi: int,
    series_rule: str,
) -> str:
    """Hard markdown template for rich, continuity-first episode scripts."""
    return (
        "你是专业竖屏漫剧编剧与视觉统筹。只输出【一支】完整短片剧本 Markdown，"
        "不要输出任何多余说明，禁止写多集。\n\n"
        "目标：先建立完整连贯的结构化设定，再写可拍分镜；"
        "后续定妆、场景底板、道具、配音、成片配乐都必须能直接引用这些字段，"
        "因此名称与细节必须前后一致、可拍摄、可配音。\n\n"
        f"{title_line}\n"
        f"- 时长: {ep_sec}s\n"
        "- 钩子: 前3秒抓住观众的一句话\n"
        "- 悬念: 结尾反转或未解悬念\n"
        "- 配乐: 情绪/风格/乐器/节奏起伏（成片 BGM 依据，勿写具体版权曲名）\n\n"
        "## 角色设定\n"
        "### 角色名\n"
        "- 外形: 年龄感、五官、发型发色、服饰、配色、标志性细节（可画定妆）\n"
        "- 性格: 2–4 词或短句\n"
        "- 音色倾向: 如女声温柔 / 男声低沉（供配音选型）\n"
        "- 口头禅: 可选\n\n"
        "## 场景设定\n"
        "### 场景名（稳定地名，跨镜复用同一写法）\n"
        "- 描述: 空间结构、材质、陈设、时代气质\n"
        "- 光影色调: 主光方向、冷暖、氛围\n"
        "- 标志物: 1–3 个固定视觉锚点\n\n"
        "## 道具设定\n"
        "### 道具名\n"
        "- 描述: 外形与材质\n"
        "- 材质外形: 可画细节\n"
        "- 剧情作用: 与冲突/身份的关系\n\n"
        "## 分镜\n"
        f"### Shot 1 (0-3s)\n"
        "- 画面: 景别+构图+人物动作+环境细节+镜头运动感（禁止写切黑/转场指令）\n"
        "- 地点: 必须引用「场景设定」中的稳定场景名\n"
        "- 道具: 本镜关键道具（顿号分隔；名称引用「道具设定」，可空）\n"
        "- 字幕: 角色台词；格式「角色名：台词」；口语化、可配音；无对白可空\n"
        "- 旁白: 画外说明（左上竖排）；可空，勿与字幕重复堆砌\n"
        "- 角色: 出场角色（顿号分隔；名称必须与「角色设定」一致）\n\n"
        "### Shot 2 (3-6s)\n"
        "……\n\n"
        f"硬性要求：{series_rule}"
        f"整集总时长必须约 {ep_sec} 秒（允许 ±5 秒）；"
        f"镜头数 {shot_lo}–{shot_hi} 个；"
        "时间轴必须从 0s 连续排到目标时长；"
        "角色/场景/道具名称全局统一，禁止同人异名；"
        "每镜必填地点；关键道具写入道具字段；"
        "台词与旁白服务情绪与信息推进，画面描述必须具体可拍；"
        "配乐描述要能指导成片选曲情绪，不要空泛形容词堆砌。"
    )


def build_episode_user_prompt(
    premise: str,
    *,
    user_series: str,
    bible: str = "",
    outline: str = "",
) -> str:
    parts = [f"系列故事梗概：{premise}", user_series]
    if bible:
        parts.append("人设/场景/道具圣经（必须遵守姓名与外形设定）：\n" + truncate_context(bible))
    if outline:
        parts.append("故事大纲（按本集节拍展开，勿越界写其它集正文）：\n" + truncate_context(outline))
    parts.append(
        "请先写齐角色设定、场景设定、道具设定与配乐，再写分镜；"
        "分镜中的角色/地点/道具必须与设定块同名。"
    )
    return "\n\n".join(parts)


def parse_asset_sections(text: str) -> dict[str, list[dict[str, str]]]:
    """Extract ## 角色设定 / 场景设定 / 道具设定 blocks from episode markdown."""
    out: dict[str, list[dict[str, str]]] = {"cast": [], "locations": [], "props": []}
    lines = str(text or "").replace("\r\n", "\n").split("\n")
    section: str | None = None
    current: dict[str, str] | None = None
    bucket: list[dict[str, str]] | None = None

    def flush() -> None:
        nonlocal current, bucket
        if current and bucket is not None and str(current.get("name") or "").strip():
            bucket.append(current)
        current = None

    for raw in lines:
        line = raw.rstrip()
        h2 = line.startswith("## ") and not line.startswith("### ")
        if h2:
            flush()
            title = line[3:].strip()
            if title.startswith("分镜"):
                section = None
                bucket = None
                continue
            key = _SECTION_ALIASES.get(title)
            section = key
            bucket = out[key] if key else None
            continue
        if section is None or bucket is None:
            continue
        if line.startswith("### "):
            flush()
            current = {"name": line[4:].strip()}
            continue
        if current is None:
            continue
        m = _ASSET_FIELD_RE.match(line)
        if m:
            key = m.group(1).strip()
            val = m.group(2).strip()
            if key and val:
                current[key] = val
    flush()
    return out


def format_asset_sections(parsed: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    cast = parsed.get("cast") if isinstance(parsed.get("cast"), list) else []
    locations = parsed.get("locations") if isinstance(parsed.get("locations"), list) else []
    props = parsed.get("props") if isinstance(parsed.get("props"), list) else []

    if cast:
        lines.append("## 角色设定")
        for rec in cast:
            if not isinstance(rec, dict):
                continue
            name = str(rec.get("name") or "").strip()
            if not name:
                continue
            lines.append(f"### {name}")
            for key in _CAST_FIELDS:
                val = str(rec.get(key) or "").strip()
                if val:
                    lines.append(f"- {key}: {val}")
            lines.append("")
    if locations:
        lines.append("## 场景设定")
        for rec in locations:
            if not isinstance(rec, dict):
                continue
            name = str(rec.get("name") or "").strip()
            if not name:
                continue
            lines.append(f"### {name}")
            for key in _LOC_FIELDS:
                val = str(rec.get(key) or "").strip()
                if val:
                    lines.append(f"- {key}: {val}")
            lines.append("")
    if props:
        lines.append("## 道具设定")
        for rec in props:
            if not isinstance(rec, dict):
                continue
            name = str(rec.get("name") or "").strip()
            if not name:
                continue
            lines.append(f"### {name}")
            for key in _PROP_FIELDS:
                val = str(rec.get(key) or "").strip()
                if val:
                    lines.append(f"- {key}: {val}")
            lines.append("")
    return lines


def materialize_script_assets(slug: str, episode: int, parsed: dict[str, Any]) -> dict[str, Any]:
    """Upsert cast/scene/prop cards from structured script + bind shot ids; store BGM intent."""
    from tools.drama_audio import load_mix, save_mix
    from tools.drama_characters import (
        load_characters,
        match_character_token,
        pick_default_voice,
        upsert_character,
        voice_hint_to_gender,
    )
    from tools.drama_environment import ensure_locations_and_props_from_shots
    from tools.drama_produce import ensure_characters_from_shots
    from tools.drama_shots import load_doc, save_doc

    created = {"characters": [], "scenes": [], "props": []}
    cards = load_characters(slug)

    for rec in parsed.get("cast") or []:
        if not isinstance(rec, dict):
            continue
        name = str(rec.get("name") or "").strip()
        if not name:
            continue
        look_parts = [
            str(rec.get("外形") or "").strip(),
            (f"性格：{str(rec.get('性格')).strip()}" if str(rec.get("性格") or "").strip() else ""),
            (f"口头禅：{str(rec.get('口头禅')).strip()}" if str(rec.get("口头禅") or "").strip() else ""),
        ]
        look = "；".join(p for p in look_parts if p) or f"{name}，竖屏漫剧角色，五官清晰可辨"
        aliases = [
            a.strip()
            for a in str(rec.get("别名") or "").replace("，", "、").split("、")
            if a.strip()
        ]
        hint_gender = voice_hint_to_gender(str(rec.get("音色倾向") or ""))
        payload: dict[str, Any] = {
            "name": name,
            "look": look,
            "category": "character",
            "catchphrase": str(rec.get("口头禅") or "").strip(),
            "aliases": aliases,
        }
        if hint_gender:
            payload["gender"] = hint_gender
        existing = match_character_token(
            name, [c for c in cards if str(c.get("category") or "character") == "character"]
        )
        if existing and existing.get("ref_locked"):
            # Keep locked looks; only fill empty look / voice / gender.
            patch: dict[str, Any] = {"id": existing["id"]}
            if not str(existing.get("look") or "").strip():
                patch["look"] = look
            if hint_gender and not str(existing.get("gender") or "").strip():
                patch["gender"] = hint_gender
            if hint_gender and not str(existing.get("voice") or "").strip():
                patch["voice"] = pick_default_voice(slug, hint_gender, cards)
            if len(patch) == 1:
                continue
            payload = patch
        elif existing:
            payload["id"] = existing["id"]
            if str(existing.get("look") or "").strip() and len(str(existing.get("look") or "")) > len(look):
                payload.pop("look", None)
            if hint_gender and not str(existing.get("voice") or "").strip():
                payload["voice"] = pick_default_voice(slug, hint_gender, cards)
            elif not hint_gender and not str(existing.get("voice") or "").strip():
                pass
        else:
            if hint_gender:
                payload["voice"] = pick_default_voice(slug, hint_gender, cards)
        card = upsert_character(slug, payload)
        cards = load_characters(slug)
        created["characters"].append(str(card.get("id") or name))

    for rec in parsed.get("locations") or []:
        if not isinstance(rec, dict):
            continue
        name = str(rec.get("name") or "").strip()
        if not name:
            continue
        look = "；".join(
            p
            for p in (
                str(rec.get("描述") or "").strip(),
                (f"光影：{str(rec.get('光影色调')).strip()}" if str(rec.get("光影色调") or "").strip() else ""),
                (f"标志物：{str(rec.get('标志物')).strip()}" if str(rec.get("标志物") or "").strip() else ""),
            )
            if p
        ) or f"{name}，稳定可复用场景底板"
        existing = match_character_token(name, [c for c in cards if str(c.get("category") or "") == "scene"])
        payload = {"name": name, "look": look, "category": "scene"}
        if existing:
            if existing.get("ref_locked"):
                continue
            payload["id"] = existing["id"]
        card = upsert_character(slug, payload)
        cards = load_characters(slug)
        created["scenes"].append(str(card.get("id") or name))

    for rec in parsed.get("props") or []:
        if not isinstance(rec, dict):
            continue
        name = str(rec.get("name") or "").strip()
        if not name:
            continue
        look = "；".join(
            p
            for p in (
                str(rec.get("描述") or "").strip(),
                str(rec.get("材质外形") or "").strip(),
                (f"剧情：{str(rec.get('剧情作用')).strip()}" if str(rec.get("剧情作用") or "").strip() else ""),
            )
            if p
        ) or f"{name}，可识别关键道具"
        existing = match_character_token(name, [c for c in cards if str(c.get("category") or "") == "prop"])
        payload = {"name": name, "look": look, "category": "prop"}
        if existing:
            if existing.get("ref_locked"):
                continue
            payload["id"] = existing["id"]
        card = upsert_character(slug, payload)
        cards = load_characters(slug)
        created["props"].append(str(card.get("id") or name))

    doc = load_doc(slug, episode)
    if doc:
        ensure_characters_from_shots(slug, doc)
        ensure_locations_and_props_from_shots(slug, doc)
        doc = load_doc(slug, episode) or doc
        meta = dict(doc.get("meta") or {}) if isinstance(doc.get("meta"), dict) else {}
        bgm = str((parsed.get("meta") or {}).get("配乐") or meta.get("配乐") or "").strip()
        if bgm:
            meta["配乐"] = bgm
            doc["meta"] = meta
            save_doc(doc)
            mix = load_mix(slug, episode)
            mix["bgm_intent"] = bgm
            save_mix(slug, episode, mix)

    created["character_cards"] = len(load_characters(slug))
    return created
