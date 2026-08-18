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


class CharacterError(ValueError):
    pass


def characters_rel(slug: str) -> str:
    return f"dramas/{slug}/characters.json"


def ref_rel(slug: str, cid: str) -> str:
    return f"dramas/{slug}/characters/{cid}.png"


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


def normalize_character(slug: str, raw: dict[str, Any]) -> dict[str, Any]:
    cid = parse_character_id(str(raw.get("id") or ""))
    name = str(raw.get("name") or cid).strip() or cid
    voice = str(raw.get("voice") or DEFAULT_VOICE).strip() or DEFAULT_VOICE
    if voice not in VOICE_IDS:
        voice = DEFAULT_VOICE
    ref = str(raw.get("ref") or ref_rel(slug, cid)).replace("\\", "/")
    return {
        "id": cid,
        "name": name,
        "aliases": _as_str_list(raw.get("aliases")),
        "look": str(raw.get("look") or "").strip(),
        "colors": str(raw.get("colors") or "").strip(),
        "catchphrase": str(raw.get("catchphrase") or "").strip(),
        "voice": voice,
        "ref": ref,
        "ref_locked": bool(raw.get("ref_locked")),
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
    cid = parse_character_id(str(patch.get("id") or suggest_character_id(str(patch.get("name") or ""))))
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
    _write_ref_png(data, dest)
    rec["ref"] = rel
    save_characters(slug, [rec if c.get("id") == cid else c for c in cards])
    return rec


def _write_ref_png(data: bytes, dest: Path) -> None:
    try:
        from io import BytesIO

        from PIL import Image

        img = Image.open(BytesIO(data)).convert("RGB")
        img.thumbnail((1024, 1024))
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
    tokens = normalize_roles(shot.get("角色"))
    if not tokens:
        tokens = infer_roles_from_dialogue(str(shot.get("对白") or ""), characters)
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for token in tokens:
        hit = match_character_token(token, characters) or find_character(characters, token)
        if not hit or hit["id"] in seen:
            continue
        seen.add(hit["id"])
        out.append(hit)
    return out


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
        look = str(char.get("look") or "").strip() or "consistent original character design"
        colors = palette_phrase(slug, char) if slug else str(char.get("colors") or "")
        bit = f"{name}: {look}"
        if colors:
            bit += f", color palette {colors}"
        if char.get("ref_locked") and look:
            bit += ", locked character reference sheet, same face and costume every shot"
        parts.append(bit)
    if not parts:
        return "consistent original characters, same faces and costumes across consecutive shots"
    return "same characters every shot, " + "; ".join(parts)


def character_seed(slug: str, characters: list[dict[str, Any]], shot_n: int) -> int:
    ids = ",".join(str(c.get("id") or "") for c in characters) or "none"
    looks = "|".join(str(c.get("look") or "") for c in characters)
    base = zlib.crc32(f"{slug}:{ids}:{looks}".encode()) & 0x7FFFFFFF
    return (base + int(shot_n or 1) * 17) & 0x7FFFFFFF
