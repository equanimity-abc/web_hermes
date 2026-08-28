"""Project character cards (D4). Looks go into scene prompts; voices bind TTS.

Does not touch agent/loop.py. Workbench REST and tiktok_drama call this.
"""

from __future__ import annotations

import json
import re
import zlib
from pathlib import Path
from typing import Any

from tools.workspace import resolve_safe

_ID_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,31}$")
_SPEAKER = re.compile(r"^[\s【\[]*([^:：\]】\s]{1,16})\s*[]】]?\s*[:：]")
_SPLIT = re.compile(r"[,，、/|]+")

VOICES = (
    ("zh-CN-YunxiNeural", "云希 · 男"),
    ("zh-CN-YunyangNeural", "云扬 · 男旁白"),
    ("zh-CN-YunjianNeural", "云健 · 男"),
    ("zh-CN-YunxiaNeural", "云夏 · 男少年"),
    ("zh-CN-XiaoxiaoNeural", "晓晓 · 女"),
    ("zh-CN-XiaoyiNeural", "晓伊 · 女"),
    ("zh-CN-XiaohanNeural", "晓涵 · 女"),
    ("zh-CN-XiaozhenNeural", "晓甄 · 女"),
)
VOICE_IDS = tuple(v[0] for v in VOICES)
DEFAULT_VOICE = "zh-CN-YunxiNeural"
VALID_CATEGORIES = frozenset({"character", "prop", "scene"})
CHAR_CANDIDATE_MAX = 4
REF_SIZE_OPTIONS = (640, 1024, 1980)
DEFAULT_REF_SIZE = 1024
REF_IMAGE_OPTIONS: tuple[dict[str, str], ...] = (
    {"provider": "kling-image", "model": "kling/kling-v3-omni-image-generation", "label": "可灵 · Kling V3 Omni"},
    {"provider": "wanx", "model": "qwen-image-plus", "label": "百炼 · Qwen-Image-Plus"},
)


def normalize_ref_image_route(raw_provider: Any, raw_model: Any) -> tuple[str, str]:
    """Normalize per-asset ref image provider/model to a known option."""
    from tools.drama_styles import default_character_ref_image_route

    default = default_character_ref_image_route()
    provider = str(raw_provider or default.get("provider") or "kling-image").strip().lower()
    model = str(raw_model or default.get("model") or "kling/kling-v3-omni-image-generation").strip()
    for opt in REF_IMAGE_OPTIONS:
        if provider == opt["provider"] and model == opt["model"]:
            return provider, model
    for opt in REF_IMAGE_OPTIONS:
        if provider == opt["provider"]:
            return opt["provider"], opt["model"]
    return str(default.get("provider") or "kling-image"), str(
        default.get("model") or "kling/kling-v3-omni-image-generation"
    )


def character_ref_shot(char: dict[str, Any]) -> dict[str, Any]:
    provider, model = normalize_ref_image_route(char.get("ref_image_provider"), char.get("ref_image_model"))
    return {
        "kind": "character_ref",
        "ref_image_provider": provider,
        "ref_image_model": model,
    }


def normalize_ref_size(raw: Any) -> int:
    try:
        n = int(raw or DEFAULT_REF_SIZE)
    except (TypeError, ValueError):
        n = DEFAULT_REF_SIZE
    return n if n in REF_SIZE_OPTIONS else DEFAULT_REF_SIZE


def ref_canvas_size(char: dict[str, Any]) -> tuple[int, int]:
    """角色三视图：整图为 S×S 正方形；物品/场景为 9:16。"""
    s = normalize_ref_size(char.get("ref_size"))
    if normalize_category(char.get("category")) == "character":
        return s, s
    return s, int(round(s * 16 / 9))


class CharacterError(ValueError):
    pass


def characters_rel(slug: str) -> str:
    return f"dramas/{slug}/characters.json"


def ref_rel(slug: str, cid: str) -> str:
    return f"dramas/{slug}/characters/{cid}.png"


def candidate_ref_rel(slug: str, cid: str, cand_id: str) -> str:
    return f"dramas/{slug}/characters/{cid}/candidates/{cand_id}.png"


def parse_character_id(raw: str) -> str:
    cid = str(raw or "").strip()
    if not _ID_RE.match(cid):
        raise CharacterError("角色 id 须为 1–32 位字母数字、下划线或短横线，且以字母或数字开头")
    return cid


def suggest_character_id(name: str) -> str:
    ascii_id = re.sub(r"[^a-zA-Z0-9]+", "-", str(name or "").strip()).strip("-").lower()
    if ascii_id and _ID_RE.match(ascii_id):
        return ascii_id[:32]
    digest = format(zlib.crc32(str(name or "c").encode()) & 0xFFFFFFFF, "x")
    return f"c{digest}"[:32]


def normalize_roles(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, (list, tuple)):
        parts = [str(x).strip() for x in raw]
    else:
        parts = [p.strip() for p in _SPLIT.split(str(raw))]
    out: list[str] = []
    for part in parts:
        if part and part not in out:
            out.append(part)
    return out


def roles_key(raw: Any) -> str:
    return ",".join(normalize_roles(raw))


def _as_str_list(value: Any) -> list[str]:
    return normalize_roles(value)


def normalize_category(raw: Any) -> str:
    cat = str(raw or "character").strip().lower()
    return cat if cat in VALID_CATEGORIES else "character"


def character_ref_negative_prompt() -> str:
    return (
        "网格线，黑色边框，分割线，九宫格，分格，表格线，参考线，身高尺，刻度尺，"
        "标尺，数字，编号，设定表，模型板，三视图，多视角，并排，分栏，侧面，背面，"
        "横线，竖线，character sheet，model sheet，turnaround，grid，border，ruler，"
        "measurement，multiple views，side view，back view"
    )


def build_asset_ref_prompt(char: dict[str, Any]) -> str:
    """角色定妆：单张正面全身立绘；物品/场景仍走各自设定图 prompt。"""
    look = str(char.get("look") or "").strip() or "原创设计"
    colors = str(char.get("colors") or "").strip()
    category = normalize_category(char.get("category"))
    no_text = "禁止任何文字、姓名、标签、编号、水印、界面元素"
    if category == "prop":
        bits = [
            "竖屏9:16物品设定图",
            f"外形：{look}",
            f"配色：{colors}" if colors else "",
            "纯白满幅背景占满画面，无黑边白边留白",
            "产品展示风格，高清细节",
            no_text,
        ]
        return "，".join(b for b in bits if b)
    if category == "scene":
        bits = [
            "竖屏9:16场景概念图",
            f"场景：{look}",
            f"色调：{colors}" if colors else "",
            "电影感光影，无人物",
            "满幅构图，无黑边白边留白",
            no_text,
        ]
        return "，".join(b for b in bits if b)
    bits = [
        "一张正方形插画，画面中只有一个动漫角色，仅一个姿势，禁止多个视角",
        "正面全身站立，居中构图，人物占画面主体",
        f"三视图：{look}",
        "均匀浅色纯色背景，无分栏、无多格、无线条、无网格",
        "完整上色插画，高质量二次元立绘",
        no_text,
    ]
    return "，".join(b for b in bits if b)


def _prune_char_candidates(rows: list[dict[str, Any]], chosen: str = "") -> list[dict[str, Any]]:
    keep = list(rows[:CHAR_CANDIDATE_MAX])
    if chosen and not any(str(c.get("id") or "") == chosen for c in keep):
        hit = next((c for c in rows if str(c.get("id") or "") == chosen), None)
        if hit:
            keep = ([hit] + [c for c in keep if str(c.get("id") or "") != chosen])[:CHAR_CANDIDATE_MAX]
    return keep


def normalize_char_candidates(
    slug: str,
    cid: str,
    raw: Any,
    chosen: str = "",
) -> list[dict[str, Any]]:
    rows = raw if isinstance(raw, list) else []
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in rows:
        if not isinstance(item, dict):
            continue
        cand_id = str(item.get("id") or "").strip()
        if not cand_id or cand_id in seen:
            continue
        seen.add(cand_id)
        rel = str(item.get("path") or candidate_ref_rel(slug, cid, cand_id)).replace("\\", "/")
        out.append(
            {
                "id": cand_id,
                "path": rel,
                "source": str(item.get("source") or "ai"),
            }
        )
    return _prune_char_candidates(out, str(chosen or ""))


def next_char_candidate_ids(char: dict[str, Any], count: int = 1) -> list[str]:
    used = {str(c.get("id") or "") for c in (char.get("candidates") or [])}
    out: list[str] = []
    i = 1
    while len(out) < max(0, int(count)):
        cid = f"c{i}"
        i += 1
        if cid not in used:
            out.append(cid)
    return out


def normalize_character(slug: str, raw: dict[str, Any]) -> dict[str, Any]:
    cid = parse_character_id(str(raw.get("id") or ""))
    name = str(raw.get("name") or cid).strip() or cid
    voice = str(raw.get("voice") or DEFAULT_VOICE).strip() or DEFAULT_VOICE
    if voice not in VOICE_IDS:
        voice = DEFAULT_VOICE
    ref = str(raw.get("ref") or ref_rel(slug, cid)).replace("\\", "/")
    chosen_ref = str(raw.get("chosen_ref") or "").strip()
    candidates = normalize_char_candidates(slug, cid, raw.get("candidates"), chosen_ref)
    ref_image_provider, ref_image_model = normalize_ref_image_route(
        raw.get("ref_image_provider"), raw.get("ref_image_model")
    )
    return {
        "id": cid,
        "name": name,
        "category": normalize_category(raw.get("category")),
        "aliases": _as_str_list(raw.get("aliases")),
        "look": str(raw.get("look") or "").strip(),
        "colors": str(raw.get("colors") or "").strip(),
        "ref_size": normalize_ref_size(raw.get("ref_size")),
        "ref_image_provider": ref_image_provider,
        "ref_image_model": ref_image_model,
        "catchphrase": str(raw.get("catchphrase") or "").strip(),
        "voice": voice,
        "ref": ref,
        "ref_locked": bool(raw.get("ref_locked")),
        "chosen_ref": chosen_ref,
        "candidates": candidates,
    }


def load_characters(slug: str) -> list[dict[str, Any]]:
    rel = characters_rel(slug)
    path = resolve_safe(rel)
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    rows = data.get("characters") if isinstance(data, dict) else data
    if not isinstance(rows, list):
        return []
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in rows:
        if not isinstance(raw, dict):
            continue
        try:
            rec = normalize_character(slug, raw)
        except CharacterError:
            continue
        if rec["id"] in seen:
            continue
        seen.add(rec["id"])
        out.append(rec)
    return out


def save_characters(slug: str, characters: list[dict[str, Any]]) -> str:
    rel = characters_rel(slug)
    path = resolve_safe(rel)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "characters": [normalize_character(slug, c) for c in characters],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return rel


def find_character(characters: list[dict[str, Any]], cid: str) -> dict[str, Any] | None:
    cid = str(cid or "").strip()
    for rec in characters:
        if rec.get("id") == cid:
            return rec
    return None


def upsert_character(slug: str, patch: dict[str, Any]) -> dict[str, Any]:
    name = str(patch.get("name") or "").strip()
    raw_id = str(patch.get("id") or "").strip()
    if raw_id and _ID_RE.match(raw_id):
        cid = parse_character_id(raw_id)
    else:
        # Tolerate non-ASCII / empty ids (e.g. an LLM passing a Chinese name as id).
        # Fall back to a deterministic ascii id derived from the name.
        cid = suggest_character_id(name or raw_id or "c")
    cards = load_characters(slug)
    existing = find_character(cards, cid) or {"id": cid}
    merged = {**existing, **{k: v for k, v in patch.items() if v is not None}}
    merged["id"] = cid
    rec = normalize_character(slug, merged)
    next_cards = [rec if c.get("id") == cid else c for c in cards]
    if not find_character(next_cards, cid):
        next_cards.append(rec)
    save_characters(slug, next_cards)
    return rec


def delete_character(slug: str, cid: str) -> None:
    cid = parse_character_id(cid)
    cards = load_characters(slug)
    rec = find_character(cards, cid)
    if rec is None:
        raise CharacterError(f"找不到角色：{cid}")
    if rec.get("ref_locked"):
        raise CharacterError("参考图已锁定，先解锁再删除角色")
    save_characters(slug, [c for c in cards if c.get("id") != cid])


def set_ref_locked(slug: str, cid: str, locked: bool) -> dict[str, Any]:
    rec = find_character(load_characters(slug), parse_character_id(cid))
    if rec is None:
        raise CharacterError(f"找不到角色：{cid}")
    rec["ref_locked"] = bool(locked)
    return upsert_character(slug, rec)


def ref_exists(slug: str, char: dict[str, Any]) -> bool:
    rel = str(char.get("ref") or ref_rel(slug, str(char.get("id") or "")))
    try:
        path = resolve_safe(rel)
    except ValueError:
        return False
    return path.is_file() and path.stat().st_size > 0


def save_character_ref(slug: str, cid: str, data: bytes) -> dict[str, Any]:
    cid = parse_character_id(cid)
    cards = load_characters(slug)
    rec = find_character(cards, cid)
    if rec is None:
        raise CharacterError(f"找不到角色：{cid}，请先保存角色卡")
    if rec.get("ref_locked") and ref_exists(slug, rec):
        raise CharacterError("参考图已锁定，解锁后才能替换")
    if not data:
        raise CharacterError("参考图不能为空")
    rel = ref_rel(slug, cid)
    dest = resolve_safe(rel)
    dest.parent.mkdir(parents=True, exist_ok=True)
    _write_ref_png(data, dest, char=rec)
    rec["ref"] = rel
    save_characters(slug, [rec if c.get("id") == cid else c for c in cards])
    return rec


def _write_ref_png(data: bytes, dest: Path, *, char: dict[str, Any] | None = None) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if char and normalize_category(char.get("category")) == "character":
        dest.write_bytes(data)
        if dest.stat().st_size < 32:
            raise CharacterError("无法读取参考图")
        return
    try:
        from io import BytesIO

        from PIL import Image

        from tools.drama_video import ZOOM_H, ZOOM_W, _prepare_frame

        img = Image.open(BytesIO(data)).convert("RGB")
        img = _prepare_frame(img, ZOOM_W, ZOOM_H)
        img.save(dest, "PNG")
    except Exception:
        dest.write_bytes(data)
        if dest.stat().st_size < 32:
            raise CharacterError("无法读取参考图") from None


def _names_of(char: dict[str, Any]) -> list[str]:
    names = [str(char.get("id") or ""), str(char.get("name") or "")]
    names.extend(_as_str_list(char.get("aliases")))
    return [n for n in names if n]


def match_character_token(token: str, characters: list[dict[str, Any]]) -> dict[str, Any] | None:
    needle = str(token or "").strip()
    if not needle:
        return None
    for char in characters:
        for name in _names_of(char):
            if needle == name:
                return char
    for char in characters:
        for name in _names_of(char):
            if needle in name or name in needle:
                return char
    return None


def resolve_role_ids(raw: Any, characters: list[dict[str, Any]]) -> list[str]:
    ids: list[str] = []
    for token in normalize_roles(raw):
        hit = match_character_token(token, characters)
        cid = str((hit or {}).get("id") or token)
        if cid not in ids:
            ids.append(cid)
    return ids


def infer_roles_from_dialogue(dialogue: str, characters: list[dict[str, Any]]) -> list[str]:
    if not characters:
        return []
    ids: list[str] = []
    for line in str(dialogue or "").splitlines():
        m = _SPEAKER.match(line.strip())
        if not m:
            continue
        hit = match_character_token(m.group(1).strip(), characters)
        if hit and hit["id"] not in ids:
            ids.append(hit["id"])
    if ids:
        return ids
    text = str(dialogue or "")
    for char in characters:
        for name in _names_of(char):
            if name and name in text and char["id"] not in ids:
                ids.append(char["id"])
                break
    return ids


def resolve_shot_characters(shot: dict[str, Any], characters: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cast_cards = [c for c in characters if normalize_category(c.get("category")) == "character"]
    tokens = normalize_roles(shot.get("角色"))
    if not tokens:
        tokens = infer_roles_from_dialogue(str(shot.get("对白") or ""), cast_cards)
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for token in tokens:
        hit = match_character_token(token, cast_cards) or find_character(cast_cards, token)
        if not hit or hit["id"] in seen:
            continue
        seen.add(hit["id"])
        out.append(hit)
    return out


def find_char_candidate(char: dict[str, Any], cand_id: str) -> dict[str, Any] | None:
    needle = str(cand_id or "").strip()
    for item in char.get("candidates") or []:
        if str(item.get("id") or "") == needle:
            return item
    return None


def append_char_candidate(slug: str, cid: str, data: bytes, *, source: str = "upload") -> dict[str, Any]:
    cid = parse_character_id(cid)
    cards = load_characters(slug)
    rec = find_character(cards, cid)
    if rec is None:
        raise CharacterError(f"找不到资产：{cid}，请先保存")
    if rec.get("ref_locked") and ref_exists(slug, rec):
        raise CharacterError("参考图已锁定，解锁后才能添加候选")
    if len(rec.get("candidates") or []) >= CHAR_CANDIDATE_MAX:
        raise CharacterError(f"候选图最多 {CHAR_CANDIDATE_MAX} 张，请先删除旧候选")
    cand_ids = next_char_candidate_ids(rec, 1)
    if not cand_ids:
        raise CharacterError("无法分配候选 id")
    cand_id = cand_ids[0]
    rel = candidate_ref_rel(slug, cid, cand_id)
    dest = resolve_safe(rel)
    dest.parent.mkdir(parents=True, exist_ok=True)
    _write_ref_png(data, dest)
    rec["candidates"] = list(rec.get("candidates") or []) + [{"id": cand_id, "path": rel, "source": source}]
    rec["candidates"] = _prune_char_candidates(rec["candidates"], str(rec.get("chosen_ref") or ""))
    if not ref_exists(slug, rec):
        rec["ref"] = rel
        rec["chosen_ref"] = cand_id
    save_characters(slug, [rec if c.get("id") == cid else c for c in cards])
    return rec


def choose_char_candidate(slug: str, cid: str, cand_id: str) -> dict[str, Any]:
    cid = parse_character_id(cid)
    cand_id = str(cand_id or "").strip()
    cards = load_characters(slug)
    rec = find_character(cards, cid)
    if rec is None:
        raise CharacterError(f"找不到资产：{cid}")
    cand = find_char_candidate(rec, cand_id)
    if cand is None:
        raise CharacterError(f"找不到候选：{cand_id}")
    rel = str(cand.get("path") or candidate_ref_rel(slug, cid, cand_id))
    if not resolve_safe(rel).is_file():
        raise CharacterError("候选图文件不存在")
    rec["ref"] = rel
    rec["chosen_ref"] = cand_id
    save_characters(slug, [rec if c.get("id") == cid else c for c in cards])
    return rec


def delete_char_candidate(slug: str, cid: str, cand_id: str) -> dict[str, Any]:
    cid = parse_character_id(cid)
    cand_id = str(cand_id or "").strip()
    cards = load_characters(slug)
    rec = find_character(cards, cid)
    if rec is None:
        raise CharacterError(f"找不到资产：{cid}")
    if rec.get("ref_locked") and str(rec.get("chosen_ref") or "") == cand_id:
        raise CharacterError("当前参考图已锁定，先解锁再删除候选")
    rec["candidates"] = [c for c in (rec.get("candidates") or []) if str(c.get("id") or "") != cand_id]
    if str(rec.get("chosen_ref") or "") == cand_id:
        rec["chosen_ref"] = ""
        remaining = rec.get("candidates") or []
        if remaining:
            last = remaining[-1]
            rec["ref"] = str(last.get("path") or ref_rel(slug, cid))
            rec["chosen_ref"] = str(last.get("id") or "")
        else:
            rec["ref"] = ref_rel(slug, cid)
    save_characters(slug, [rec if c.get("id") == cid else c for c in cards])
    return rec


def primary_voice(characters: list[dict[str, Any]]) -> str:
    for char in characters:
        voice = str(char.get("voice") or "").strip()
        if voice:
            return voice if voice in VOICE_IDS else DEFAULT_VOICE
    return DEFAULT_VOICE


def palette_phrase(slug: str, char: dict[str, Any]) -> str:
    colors = str(char.get("colors") or "").strip()
    if colors:
        return colors
    rel = str(char.get("ref") or "")
    if not rel:
        return ""
    try:
        path = resolve_safe(rel)
    except ValueError:
        return ""
    if not path.is_file():
        return ""
    try:
        from PIL import Image

        img = Image.open(path).convert("RGB").resize((24, 24))
        pixels = list(img.getdata())
        buckets: dict[tuple[int, int, int], int] = {}
        for r, g, b in pixels:
            key = (r // 32 * 32, g // 32 * 32, b // 32 * 32)
            buckets[key] = buckets.get(key, 0) + 1
        top = sorted(buckets, key=lambda k: buckets[k], reverse=True)[:3]
        return ", ".join(f"#{r:02x}{g:02x}{b:02x}" for r, g, b in top)
    except Exception:
        return ""


def character_prompt_clause(characters: list[dict[str, Any]], *, slug: str = "") -> str:
    parts: list[str] = []
    for char in characters:
        name = char.get("name") or char.get("id")
        look = str(char.get("look") or "").strip() or "保持原作角色设计一致"
        colors = palette_phrase(slug, char) if slug else str(char.get("colors") or "")
        bit = f"{name}：{look}"
        if colors:
            bit += f"，配色：{colors}"
        if char.get("ref_locked") and look:
            bit += "，已锁定定妆参考图，每张镜头同一张脸同一套服装"
        parts.append(bit)
    if not parts:
        return "连续镜头中角色面孔与服装保持一致"
    return "每镜同一批角色，" + "；".join(parts)


def character_seed(slug: str, characters: list[dict[str, Any]], shot_n: int) -> int:
    from tools.workspace import resolve_safe

    parts: list[str] = []
    for char in characters:
        cid = str(char.get("id") or "")
        if char.get("ref_locked") and ref_exists(slug, char):
            rel = str(char.get("ref") or ref_rel(slug, cid)).replace("\\", "/")
            try:
                path = resolve_safe(rel)
                parts.append(f"{cid}:{rel}:{path.stat().st_size}:{int(path.stat().st_mtime_ns)}")
            except (ValueError, OSError):
                parts.append(f"{cid}:{rel}")
        else:
            parts.append(f"{cid}:{str(char.get('look') or '')}")
    blob = "|".join(parts) or "none"
    base = zlib.crc32(f"{slug}:{blob}".encode()) & 0x7FFFFFFF
    return (base + int(shot_n or 1) * 17) & 0x7FFFFFFF
