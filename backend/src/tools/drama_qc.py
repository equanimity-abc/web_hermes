"""Seedream 出图参考打包（Ark）。

身份 / 口型 / 闪烁 / 响度 QC 已删除：质量由人在工作台把关，produce/export 不再做任何检查门闸。
"""

from __future__ import annotations

from typing import Any

from tools.drama_characters import load_characters, ref_exists, resolve_shot_characters
from tools.workspace import resolve_safe


def _char_ref_path(slug: str, char: dict[str, Any]) -> str | None:
    from tools.drama_characters import anchor_ref_rel

    if not char or not char.get("ref_locked") or not ref_exists(slug, char):
        return None
    rel = anchor_ref_rel(slug, char)
    if not rel:
        return None
    try:
        path = resolve_safe(rel)
    except ValueError:
        return None
    return rel if path.is_file() else None


def locked_face_refs_for_shot(slug: str, shot: dict[str, Any]) -> list[str]:
    """本镜出图用的角色参考路径（Ark：大头照→全身照；身份主体优先）。"""
    from tools.drama_characters import (
        character_ark_pair_refs,
        character_requires_face,
        ref_exists,
    )

    cards = load_characters(slug)
    cast = resolve_shot_characters(shot, cards)
    from tools.drama_spatial import subject_character

    subject = subject_character(slug, shot)
    ordered: list[dict[str, Any]] = []
    if subject and character_requires_face(subject):
        ordered.append(subject)
    for char in cast:
        if not character_requires_face(char):
            continue
        cid = str(char.get("id") or "")
        if any(str(x.get("id") or "") == cid for x in ordered):
            continue
        ordered.append(char)

    refs: list[str] = []
    for char in ordered:
        if not char.get("ref_locked") or not ref_exists(slug, char):
            if not ref_exists(slug, char):
                continue
        for rel in character_ark_pair_refs(slug, char):
            if rel not in refs:
                refs.append(rel)
    return refs


def locked_env_refs_for_shot(slug: str, shot: dict[str, Any]) -> list[str]:
    """本镜环境参考：地点主底板（优先）+ 至多 1 个主道具设定图。"""
    from tools.drama_characters import (
        environment_ref_rel,
        find_character,
        load_characters,
        normalize_category,
        ref_exists,
    )

    cards = load_characters(slug)
    refs: list[str] = []
    loc_id = str(shot.get("location_id") or "").strip()
    if loc_id:
        loc = find_character(cards, loc_id)
        if loc and normalize_category(loc.get("category")) == "scene":
            rel = environment_ref_rel(slug, loc)
            if rel:
                try:
                    if resolve_safe(rel).is_file() and rel not in refs:
                        refs.append(rel)
                except ValueError:
                    pass
    prop_ids = shot.get("prop_ids") if isinstance(shot.get("prop_ids"), list) else []
    for pid in prop_ids[:2]:
        cid = str(pid or "").strip()
        if not cid:
            continue
        prop = find_character(cards, cid)
        if not prop or normalize_category(prop.get("category")) != "prop":
            continue
        if not (prop.get("ref_locked") and ref_exists(slug, prop)):
            if not ref_exists(slug, prop):
                continue
        rel = str(prop.get("ref") or "").replace("\\", "/")
        if not rel:
            continue
        try:
            if resolve_safe(rel).is_file() and rel not in refs:
                refs.append(rel)
                break
        except ValueError:
            continue
    return refs


def compose_shot_image_refs(slug: str, shot: dict[str, Any], *, max_refs: int = 4) -> list[str]:
    """Seedream 参考打包（Ark：大头照优先于全身，再环境）。"""
    from tools.drama_models import infer_kind, infer_size

    limit = max(1, min(int(max_refs or 4), 4))
    env = locked_env_refs_for_shot(slug, shot)
    faces = locked_face_refs_for_shot(slug, shot)[:2]
    kind = infer_kind(shot)
    size = infer_size(shot)
    face_first = kind in ("dialogue", "reaction", "cu", "ms", "hook", "action") or size in (
        "CU",
        "MCU",
        "ECU",
        "MS",
        "近景",
        "特写",
        "中景",
    )
    primary = faces if face_first else env
    secondary = env if face_first else faces
    out: list[str] = []
    for rel in primary:
        if len(out) >= limit:
            break
        if rel not in out:
            out.append(rel)
    for rel in secondary:
        if len(out) >= limit:
            break
        if rel not in out:
            out.append(rel)
    if len(out) < limit:
        for rel in env:
            if len(out) >= limit:
                break
            if rel not in out:
                out.append(rel)
    return out
