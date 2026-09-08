"""Location / prop binding for shot environment consistency (P0+).

Structured script fields ``地点`` / ``道具`` plus heuristic extraction from ``画面``.
Assets reuse ``characters.json`` with ``category`` in {scene, prop}.
"""

from __future__ import annotations

import re
from typing import Any

from tools.drama_characters import (
    load_characters,
    match_character_token,
    normalize_category,
    normalize_roles,
    upsert_character,
)

# Common place suffixes in vertical-drama Chinese copy.
_PLACE_SUFFIX = (
    "宫",
    "殿",
    "殿前",
    "殿外",
    "殿内",
    "前殿",
    "后殿",
    "月宫",
    "广寒宫",
    "街",
    "巷",
    "道",
    "路",
    "桥",
    "房",
    "屋",
    "室",
    "厅",
    "堂",
    "院",
    "园",
    "楼",
    "塔",
    "庙",
    "观",
    "寺",
    "山",
    "洞",
    "湖",
    "海",
    "河",
    "岸",
    "林",
    "城",
    "府",
    "门",
    "门口",
    "台阶",
    "走廊",
    "天台",
    "阳台",
    "卧室",
    "书房",
    "厨房",
    "咖啡厅",
    "办公室",
    "教室",
    "地铁",
    "车站",
)

_PROP_MARKERS = (
    "不死药",
    "仙药",
    "佩剑",
    "长剑",
    "短剑",
    "宝剑",
    "药瓶",
    "玉佩",
    "玉兔",  # careful - might be character; filtered by cast
    "信封",
    "信件",
    "手机",
    "钥匙",
    "戒指",
    "项链",
    "手链",
    "镯",
    "灯笼",
    "烛台",
    "酒壶",
    "酒杯",
    "碗",
    "粥",
    "伞",
    "扇子",
    "面具",
    "照片",
    "画像",
    "卷轴",
    "书信",
    "匕首",
    "弓",
    "箭",
)

_LOC_AFTER_PREP_RE = re.compile(
    r"(?:在|于|位于|站在|立于|坐在|跪在|停在|回到|走进|跑进|冲进|来到|抵达|路过)"
    r"(?P<loc>[\u4e00-\u9fff]{1,12}"
    r"(?:前殿|后殿|正殿|广寒宫|月宫|天宫|龙宫|仙宫|"
    r"宫|殿|街|巷|道|路|桥|房|屋|室|厅|堂|院|园|楼|塔|庙|观|寺|山|洞|湖|海|河|岸|林|城|府|"
    r"门口|台阶|走廊|天台|阳台|卧室|书房|厨房|咖啡厅|办公室|教室|地铁|车站))"
)

_LOC_NAMED_RE = re.compile(
    r"(?P<loc>"
    r"[\u4e00-\u9fff]{0,6}(?:广寒宫前殿|广寒宫|月宫|天宫|龙宫|仙宫|前殿|后殿|正殿)"
    r"(?:前|外|内|边|旁)?"
    r"|"
    r"[\u4e00-\u9fff]{2,8}(?:前殿|后殿|正殿|宫|殿)(?:前|外|内|边|旁)?"
    r")"
)

_LOC_CLEAN_RE = re.compile(r"^(?:的|了|着|把|被)+|(?:的|了|着)+$")
_LOC_LEADING_ACTOR_RE = re.compile(
    r"^[\u4e00-\u9fff]{1,6}(?:站在|立于|坐在|跪在|停在|走进|跑进|冲进|来到|抵达)"
)


def normalize_location_name(raw: Any) -> str:
    text = str(raw or "").strip()
    if not text:
        return ""
    text = re.split(r"[，,、/;；|/]", text, maxsplit=1)[0].strip()
    text = _LOC_LEADING_ACTOR_RE.sub("", text).strip()
    text = _LOC_CLEAN_RE.sub("", text).strip()
    text = re.sub(r"^(?:在|于|位于)\s*", "", text).strip()
    if len(text) > 24:
        text = text[:24]
    return text


def normalize_prop_names(raw: Any) -> list[str]:
    names = normalize_roles(raw)
    out: list[str] = []
    for name in names:
        cleaned = str(name or "").strip()
        if not cleaned:
            continue
        if len(cleaned) > 24:
            cleaned = cleaned[:24]
        if cleaned not in out:
            out.append(cleaned)
    return out


def extract_location_from_scene(scene: str) -> str:
    """Heuristic: pull a stable place name from 画面 prose."""
    text = str(scene or "").strip()
    if not text:
        return ""
    m_tag = re.search(r"(?:地点|场景|场所)\s*[:：]\s*([^\s，,。；;]{2,16})", text)
    if m_tag:
        return normalize_location_name(m_tag.group(1))

    for rx in (_LOC_AFTER_PREP_RE, _LOC_NAMED_RE):
        m = rx.search(text)
        if not m:
            continue
        cand = normalize_location_name(m.group("loc") or "")
        # 「广寒宫前殿台阶」→ 收束到建筑本体，避免每镜台阶后缀拆卡
        cand = re.sub(r"(?:台阶|门口|走廊|边上|旁侧)$", "", cand).strip()
        if len(cand) < 2:
            continue
        if any(cand.endswith(suf) or suf in cand for suf in _PLACE_SUFFIX):
            return cand
        if len(cand) >= 3:
            return cand
    return ""


def extract_props_from_scene(scene: str, *, exclude: set[str] | None = None) -> list[str]:
    """Heuristic: known prop tokens appearing in 画面 (excluding cast names)."""
    text = str(scene or "").strip()
    if not text:
        return []
    blocked = {str(x).strip() for x in (exclude or set()) if str(x).strip()}
    m_tag = re.search(r"(?:道具|物品)\s*[:：]\s*([^\n。；;]+)", text)
    found: list[str] = []
    if m_tag:
        for name in normalize_prop_names(m_tag.group(1)):
            if name not in blocked and name not in found:
                found.append(name)
    for marker in _PROP_MARKERS:
        if marker in text and marker not in blocked and marker not in found:
            found.append(marker)
    return found[:6]


def match_asset_token(
    token: str,
    characters: list[dict[str, Any]],
    *,
    category: str,
) -> dict[str, Any] | None:
    """Match by name/alias among cards of a given category."""
    want = normalize_category(category)
    pool = [c for c in characters if normalize_category(c.get("category")) == want]
    return match_character_token(token, pool)


def _default_look(name: str, category: str) -> str:
    if category == "prop":
        return f"{name}，竖屏漫剧关键道具，外形特征清晰可辨，材质与年代感符合剧情，高质量设定图"
    return (
        f"{name}，竖屏漫剧固定场景，建筑轮廓与标志物清晰，主光方向与地面材质稳定，"
        "电影感环境概念图，无人物"
    )


def ensure_locations_and_props_from_shots(slug: str, doc: dict[str, Any]) -> dict[str, Any]:
    """Create scene/prop cards from shot fields (and 画面 heuristics); bind ids onto shots.

    Mutates ``doc['shots']`` in place. Returns summary counts.
    """
    cards = load_characters(slug)
    created_locations: list[str] = []
    created_props: list[str] = []
    bound = 0

    for shot in doc.get("shots") or []:
        if not isinstance(shot, dict):
            continue
        cast_names = set(normalize_roles(shot.get("角色")))
        loc = normalize_location_name(shot.get("地点"))
        if not loc:
            loc = extract_location_from_scene(str(shot.get("画面") or ""))
        props = normalize_prop_names(shot.get("道具"))
        if not props:
            props = extract_props_from_scene(str(shot.get("画面") or ""), exclude=cast_names)

        location_id = ""
        if loc:
            hit = match_asset_token(loc, cards, category="scene")
            if hit is None:
                rec = upsert_character(
                    slug,
                    {
                        "name": loc,
                        "category": "scene",
                        "look": _default_look(loc, "scene"),
                        "colors": "主色:#C8D0D8, 点缀:#6B7C8A",
                        "aliases": [loc],
                    },
                )
                cards.append(rec)
                created_locations.append(str(rec.get("id") or loc))
                hit = rec
            else:
                # Merge alias if new wording
                aliases = list(hit.get("aliases") or [])
                if loc not in aliases and loc != str(hit.get("name") or ""):
                    aliases.append(loc)
                    hit = upsert_character(slug, {**hit, "aliases": aliases})
                    cards = [hit if c.get("id") == hit.get("id") else c for c in cards]
            location_id = str(hit.get("id") or "")
            shot["地点"] = str(hit.get("name") or loc)
            shot["location_id"] = location_id
            bound += 1
        else:
            shot["地点"] = str(shot.get("地点") or "")
            shot["location_id"] = str(shot.get("location_id") or "")

        prop_ids: list[str] = []
        prop_names: list[str] = []
        for prop_name in props:
            if prop_name in cast_names:
                continue
            hit = match_asset_token(prop_name, cards, category="prop")
            if hit is None:
                # Avoid colliding with an existing character of the same name
                char_hit = match_character_token(
                    prop_name,
                    [c for c in cards if normalize_category(c.get("category")) == "character"],
                )
                if char_hit is not None:
                    continue
                rec = upsert_character(
                    slug,
                    {
                        "name": prop_name,
                        "category": "prop",
                        "look": _default_look(prop_name, "prop"),
                        "colors": "主色:#D4C4A8, 点缀:#8B6914",
                        "aliases": [prop_name],
                    },
                )
                cards.append(rec)
                created_props.append(str(rec.get("id") or prop_name))
                hit = rec
            cid = str(hit.get("id") or "")
            if cid and cid not in prop_ids:
                prop_ids.append(cid)
                prop_names.append(str(hit.get("name") or prop_name))
        shot["道具"] = prop_names
        shot["prop_ids"] = prop_ids
        if prop_ids:
            bound += 1

    return {
        "locations_created": created_locations,
        "props_created": created_props,
        "shots_bound": bound,
    }


def location_prompt_clause(location: dict[str, Any] | None) -> str:
    """Text anchor for scene prompts (used from P2; safe no-op helper in P0)."""
    if not location:
        return ""
    name = str(location.get("name") or location.get("id") or "").strip()
    look = str(location.get("look") or "").strip()
    anchor = str(location.get("anchor_prompt") or "").strip()
    colors = str(location.get("colors") or "").strip()
    bits = [f"地点「{name}」" if name else "固定地点"]
    if look:
        bits.append(look)
    if colors:
        bits.append(colors)
    if anchor:
        bits.append(anchor)
    bits.append("保持同一建筑轮廓、主光方向与地面材质，禁止换成无关背景")
    return "，".join(bits)


def prop_prompt_clause(props: list[dict[str, Any]] | None) -> str:
    cards = [p for p in (props or []) if isinstance(p, dict)]
    if not cards:
        return ""
    parts: list[str] = []
    for prop in cards[:4]:
        name = str(prop.get("name") or prop.get("id") or "").strip()
        look = str(prop.get("look") or "").strip()
        if not name:
            continue
        chunk = f"道具「{name}」"
        if look:
            chunk += f"：{look}"
        parts.append(chunk)
    if not parts:
        return ""
    return "可见道具须与设定一致：" + "；".join(parts)
