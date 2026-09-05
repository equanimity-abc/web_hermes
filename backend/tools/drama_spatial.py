"""角色–空间预规划：出图前钉死谁在哪、谁必须露脸。"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from tools.drama_characters import (
    character_requires_face_identity,
    load_characters,
    resolve_shot_characters,
)
from tools.drama_models import infer_kind, infer_speaker

# 可识别下限（配对用，不是过闸阈值）
MATCH_FLOOR = 0.35


def _cid(char: dict[str, Any]) -> str:
    return str(char.get("id") or "").strip()


def _cname(char: dict[str, Any]) -> str:
    return str(char.get("name") or char.get("id") or "").strip()


def identity_subject_character(slug: str, shot: dict[str, Any]) -> dict[str, Any] | None:
    """显式 identity_subject > speaker > 首个可锁脸角色。"""
    cards = load_characters(slug)
    cast = resolve_shot_characters(shot, cards)
    override = str(shot.get("identity_subject") or "").strip()
    if override:
        for char in cast:
            if _cid(char) == override or _cname(char) == override:
                if character_requires_face_identity(char):
                    return char
        from tools.drama_characters import find_character, match_character_token

        hit = find_character(cards, override) or match_character_token(override, cards)
        if hit and character_requires_face_identity(hit):
            return hit
    speaker = infer_speaker(shot)
    if speaker:
        from tools.drama_characters import find_character, match_character_token

        hit = find_character(cards, speaker) or match_character_token(speaker, cards)
        if hit and character_requires_face_identity(hit):
            return hit
    for char in cast:
        if character_requires_face_identity(char):
            return char
    return None


def _default_slots(
    cast: list[dict[str, Any]],
    *,
    subject_id: str,
) -> list[dict[str, Any]]:
    face_cast = [c for c in cast if character_requires_face_identity(c)]
    if not face_cast:
        return []
    # 主体置前
    ordered = sorted(face_cast, key=lambda c: (0 if _cid(c) == subject_id else 1, _cname(c)))
    n = len(ordered)
    slots: list[dict[str, Any]] = []
    if n == 1:
        cid = _cid(ordered[0])
        slots.append(
            {
                "character_id": cid,
                "character_name": _cname(ordered[0]),
                "role": "identity" if cid == subject_id else "support",
                "anchor": "center_front",
                "bbox_norm": [0.18, 0.12, 0.82, 0.78],
                "min_face_ratio": 0.08 if cid == subject_id else 0.04,
            }
        )
        return slots
    # 双人及以上：左右分槽；主体在右前（竖屏对白常见）或人数奇偶
    for i, char in enumerate(ordered[:3]):
        cid = _cid(char)
        is_subj = cid == subject_id
        if n == 2:
            # 主体靠前居中偏一侧，配角另一侧
            if is_subj or (not any(_cid(x) == subject_id for x in ordered) and i == 0):
                bbox = [0.28, 0.12, 0.92, 0.80]
                anchor = "right_front"
            else:
                bbox = [0.05, 0.18, 0.48, 0.78]
                anchor = "left_mid"
        else:
            # 三人：左中右
            thirds = [
                ([0.02, 0.18, 0.38, 0.78], "left_mid"),
                ([0.30, 0.12, 0.70, 0.80], "center_front"),
                ([0.60, 0.18, 0.98, 0.78], "right_mid"),
            ]
            bbox, anchor = thirds[min(i, 2)]
            if is_subj:
                bbox, anchor = thirds[1]
        slots.append(
            {
                "character_id": cid,
                "character_name": _cname(char),
                "role": "identity" if is_subj else "support",
                "anchor": anchor,
                "bbox_norm": bbox,
                "min_face_ratio": 0.08 if is_subj else 0.04,
            }
        )
    # 保证主体 role=identity 且只有一个
    for slot in slots:
        if slot["character_id"] == subject_id:
            slot["role"] = "identity"
            slot["min_face_ratio"] = max(float(slot.get("min_face_ratio") or 0), 0.08)
        elif slot.get("role") == "identity":
            slot["role"] = "support"
    return slots


def rewrite_scene_for_plan(scene: str, plan: dict[str, Any]) -> str:
    """文案与空间计划冲突时改写景别，保证主身份可露脸。"""
    text = str(scene or "").strip()
    if not text:
        return text
    slots = list(plan.get("slots") or [])
    if not slots:
        return text
    identity = next((s for s in slots if s.get("role") == "identity"), slots[0])
    name = str(identity.get("character_name") or identity.get("character_id") or "").strip()
    text2 = re.sub(r"竖屏远景", "竖屏中近景", text)
    text2 = re.sub(r"(?<![中近])远景", "中近景", text2)
    if name and name not in text2:
        text2 = f"{text2}，以「{name}」面部为画面主脸"
    elif name:
        # 已有名字但仍是「别人拎着主体」类：强制主脸句
        if re.search(rf"拎着{re.escape(name)}|抱着{re.escape(name)}", text2):
            text2 = f"{text2}，特写「{name}」正面清晰露脸占主要人脸"
    return text2


def build_spatial_plan(slug: str, shot: dict[str, Any]) -> dict[str, Any]:
    """为单镜构建/刷新 spatial_plan，并回写改写后的画面文案。"""
    cards = load_characters(slug)
    cast = resolve_shot_characters(shot, cards)
    kind = infer_kind(shot)
    subject = identity_subject_character(slug, shot)
    subject_id = _cid(subject) if subject else ""
    speaker = infer_speaker(shot)

    if kind in ("establishing", "crowd", "title", "insert") and not subject:
        plan = {
            "version": 1,
            "canvas": "9:16",
            "kind": kind,
            "speaker_id": "",
            "identity_subject_id": "",
            "slots": [],
            "occlusion": [],
            "hash": "",
        }
        plan["hash"] = plan_hash(plan)
        shot["spatial_plan"] = plan
        return plan

    slots = _default_slots(cast, subject_id=subject_id)
    plan = {
        "version": 1,
        "canvas": "9:16",
        "kind": kind,
        "speaker_id": subject_id if speaker else subject_id,
        "identity_subject_id": subject_id,
        "slots": slots,
        "occlusion": [],
        "hash": "",
    }
    if len(slots) >= 2:
        front = next((s["character_id"] for s in slots if s.get("role") == "identity"), slots[0]["character_id"])
        back = next((s["character_id"] for s in slots if s["character_id"] != front), "")
        if front and back:
            plan["occlusion"] = [{"front": front, "back": back}]

    scene = str(shot.get("画面") or "")
    rewritten = rewrite_scene_for_plan(scene, plan)
    if rewritten and rewritten != scene:
        shot["画面"] = rewritten
        plan["scene_rewritten"] = True
    else:
        plan["scene_rewritten"] = False

    plan["hash"] = plan_hash(plan)
    shot["spatial_plan"] = plan
    if subject_id and not str(shot.get("identity_subject") or "").strip():
        shot["identity_subject"] = subject_id
    return plan


def plan_hash(plan: dict[str, Any]) -> str:
    payload = {
        "slots": [
            {
                "character_id": s.get("character_id"),
                "role": s.get("role"),
                "anchor": s.get("anchor"),
                "bbox_norm": s.get("bbox_norm"),
                "min_face_ratio": s.get("min_face_ratio"),
            }
            for s in (plan.get("slots") or [])
        ],
        "identity_subject_id": plan.get("identity_subject_id"),
        "speaker_id": plan.get("speaker_id"),
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def spatial_prompt_clause(plan: dict[str, Any] | None) -> str:
    if not isinstance(plan, dict):
        return ""
    slots = list(plan.get("slots") or [])
    if not slots:
        return ""
    bits: list[str] = []
    for slot in slots:
        name = str(slot.get("character_name") or slot.get("character_id") or "")
        anchor = str(slot.get("anchor") or "")
        role = str(slot.get("role") or "support")
        face = "主脸清晰可见" if role == "identity" else "外形可辨"
        bits.append(f"{name}位于{anchor}（{face}）")
    subj = str(plan.get("identity_subject_id") or "")
    subj_name = next(
        (str(s.get("character_name") or "") for s in slots if s.get("character_id") == subj),
        "",
    )
    head = f"构图预规划：{'；'.join(bits)}"
    if subj_name:
        head += f"。身份锁「{subj_name}」必须占本镜主要人脸"
    return head


def ensure_spatial_plans_doc(slug: str, doc: dict[str, Any]) -> int:
    """为 doc 内所有镜头构建 spatial_plan；返回刷新数量。"""
    n = 0
    for shot in doc.get("shots") or []:
        if not isinstance(shot, dict):
            continue
        build_spatial_plan(slug, shot)
        n += 1
    return n


def slot_for_character(plan: dict[str, Any] | None, character_id: str) -> dict[str, Any] | None:
    cid = str(character_id or "")
    for slot in (plan or {}).get("slots") or []:
        if str(slot.get("character_id") or "") == cid:
            return slot
    return None


def face_center_in_slot(bbox: list[float], slot: dict[str, Any], *, img_w: int, img_h: int) -> bool:
    """脸中心是否落在槽位 bbox_norm 内（放宽 10%）。"""
    if not bbox or img_w <= 0 or img_h <= 0:
        return False
    try:
        cx = (float(bbox[0]) + float(bbox[2])) / 2.0 / float(img_w)
        cy = (float(bbox[1]) + float(bbox[3])) / 2.0 / float(img_h)
        x0, y0, x1, y1 = [float(v) for v in (slot.get("bbox_norm") or [0, 0, 1, 1])]
        pad = 0.10
        return (x0 - pad) <= cx <= (x1 + pad) and (y0 - pad) <= cy <= (y1 + pad)
    except (TypeError, ValueError, IndexError):
        return False
