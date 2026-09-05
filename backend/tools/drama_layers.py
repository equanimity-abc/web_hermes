"""分层生成：场景底板 + 逐角色定妆层 + 按 spatial_plan 槽位融合。"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from tools.drama_characters import (
    character_requires_face_identity,
    load_characters,
)
from tools.drama_spatial import build_spatial_plan
from tools.workspace import resolve_safe

log = logging.getLogger("drama.layers")


def layer_rel(slug: str, episode: int, shot_n: int, kind: str, cid: str = "") -> str:
    stem = f"shot{int(shot_n):02d}"
    if kind == "plate":
        return f"dramas/{slug}/videos/ep{int(episode):02d}/{stem}_plate.png"
    safe = "".join(ch for ch in str(cid) if ch.isalnum() or ch in "-_")[:24] or "x"
    return f"dramas/{slug}/videos/ep{int(episode):02d}/{stem}_layer_{safe}.png"


def _bbox_pixels(bbox_norm: list[float], width: int, height: int) -> tuple[int, int, int, int]:
    x0, y0, x1, y1 = [float(v) for v in bbox_norm]
    x0 = max(0.0, min(1.0, x0))
    y0 = max(0.0, min(1.0, y0))
    x1 = max(0.0, min(1.0, x1))
    y1 = max(0.0, min(1.0, y1))
    if x1 <= x0:
        x1 = min(1.0, x0 + 0.3)
    if y1 <= y0:
        y1 = min(1.0, y0 + 0.4)
    return (
        int(x0 * width),
        int(y0 * height),
        max(1, int((x1 - x0) * width)),
        max(1, int((y1 - y0) * height)),
    )


def _soft_ellipse_mask(w: int, h: int):
    from PIL import Image, ImageDraw, ImageFilter

    mask = Image.new("L", (w, h), 0)
    draw = ImageDraw.Draw(mask)
    inset = max(2, min(w, h) // 20)
    draw.ellipse((inset, inset, w - inset - 1, h - inset - 1), fill=255)
    return mask.filter(ImageFilter.GaussianBlur(radius=max(4, min(w, h) // 25)))


def _paste_layer_into_slot(canvas, layer_rgb, bbox_norm: list[float]) -> None:
    from PIL import Image

    cw, ch = canvas.size
    x, y, bw, bh = _bbox_pixels(bbox_norm, cw, ch)
    from tools.drama_video import _fit_cover

    fitted = _fit_cover(layer_rgb.convert("RGB"), bw, bh)
    rgba = fitted.convert("RGBA")
    mask = _soft_ellipse_mask(bw, bh)
    rgba.putalpha(mask)
    canvas.paste(rgba, (x, y), rgba)


def _occlusion_ordered_slots(plan: dict[str, Any]) -> list[dict[str, Any]]:
    slots = list(plan.get("slots") or [])
    if not slots:
        return []
    front_ids = {str(o.get("front") or "") for o in (plan.get("occlusion") or [])}
    # 先贴背层，再贴前景
    back = [s for s in slots if str(s.get("character_id") or "") not in front_ids]
    front = [s for s in slots if str(s.get("character_id") or "") in front_ids]
    if not front and not back:
        # 无 occlusion：support 先，identity 后
        back = [s for s in slots if s.get("role") != "identity"]
        front = [s for s in slots if s.get("role") == "identity"]
        if not front:
            front = slots[-1:]
            back = slots[:-1]
    return back + front


def _char_by_id(cards: list[dict[str, Any]], cid: str) -> dict[str, Any] | None:
    return next((c for c in cards if str(c.get("id") or "") == cid), None)


def generate_layered_scene(
    slug: str,
    episode: int,
    shot: dict[str, Any],
    dest: Path,
    *,
    title: str = "",
    seed: int = 0,
) -> dict[str, Any]:
    """生成分层场景并融合到 dest。成功返回 assets 信息，失败返回 {ok: False}。"""
    from tools.drama_characters import character_anchor_prompt, ref_exists
    from tools.drama_qc import _char_ref_path
    from tools.drama_video import (
        ZOOM_H,
        ZOOM_W,
        _generate_scene_image,
        _prepare_frame,
        _scene_text_for_prompt,
    )
    from PIL import Image

    plan = shot.get("spatial_plan") if isinstance(shot.get("spatial_plan"), dict) else None
    if not plan or not plan.get("slots"):
        plan = build_spatial_plan(slug, shot)
    slots = list(plan.get("slots") or [])
    if len(slots) < 1:
        return {"ok": False, "reason": "no_slots"}

    cards = load_characters(slug)
    # 只要有可锁脸槽位就分层
    usable: list[tuple[dict[str, Any], dict[str, Any], str]] = []
    for slot in slots:
        cid = str(slot.get("character_id") or "")
        char = _char_by_id(cards, cid)
        if not char or not character_requires_face_identity(char):
            continue
        ref = _char_ref_path(slug, char)
        if not ref or not ref_exists(slug, char):
            continue
        usable.append((slot, char, ref))
    if not usable:
        return {"ok": False, "reason": "no_locked_refs"}

    n = int(shot.get("n") or 0)
    plate_rel = layer_rel(slug, episode, n, "plate")
    plate_path = resolve_safe(plate_rel)
    plate_path.parent.mkdir(parents=True, exist_ok=True)

    scene_txt = _scene_text_for_prompt(shot.get("画面") or "")
    plate_prompt = (
        f"竖屏9:16场景底板，{title or '短剧'}，{scene_txt}，"
        "空镜或极弱化人物剪影，突出环境与光影，不要清晰可辨的人脸，"
        "现代都市条漫插画，戏剧性轮廓光，无文字无字幕无水印"
    )
    ok_plate = bool(
        _generate_scene_image(
            plate_prompt,
            plate_path,
            seed=(seed + 17) & 0x7FFFFFFF,
            slug=slug,
            shot={**shot, "kind": "establishing"},
            refs=(),
            width=ZOOM_W,
            height=ZOOM_H,
        )
    )
    if not ok_plate or not plate_path.is_file():
        return {"ok": False, "reason": "plate_failed"}

    canvas = Image.open(plate_path).convert("RGBA")
    canvas = _prepare_frame(canvas.convert("RGB"), ZOOM_W, ZOOM_H).convert("RGBA")

    layer_assets: dict[str, str] = {"plate": plate_rel}
    ordered_slots = _occlusion_ordered_slots(plan)
    # 保持 usable 顺序跟 occlusion 一致
    by_cid = {str(s.get("character_id") or ""): (s, c, r) for s, c, r in usable}
    ordered_usable = []
    for slot in ordered_slots:
        cid = str(slot.get("character_id") or "")
        if cid in by_cid:
            ordered_usable.append(by_cid[cid])
    for item in usable:
        if item not in ordered_usable:
            ordered_usable.append(item)

    for i, (slot, char, ref) in enumerate(ordered_usable):
        cid = str(char.get("id") or "")
        name = str(char.get("name") or cid)
        anchor = str(slot.get("anchor") or "center_front")
        ap = character_anchor_prompt(char)
        layer_rel_path = layer_rel(slug, episode, n, "character", cid)
        layer_path = resolve_safe(layer_rel_path)
        layer_prompt = (
            f"竖屏9:16单人角色层，{name}，{ap}，"
            f"角色位于{anchor}，半身或全身清晰可见，五官清楚，"
            "简洁浅色或虚化背景便于抠图合成，同一张脸同一套服装，"
            "条漫插画，无文字无字幕无水印，画面中只有这一个角色"
        )
        ok_layer = bool(
            _generate_scene_image(
                layer_prompt,
                layer_path,
                seed=(seed + 1009 * (i + 1)) & 0x7FFFFFFF,
                slug=slug,
                shot=shot,
                refs=(ref,),
                width=ZOOM_W,
                height=ZOOM_H,
            )
        )
        if not ok_layer or not layer_path.is_file():
            log.warning("layered character gen failed cid=%s", cid)
            return {"ok": False, "reason": f"layer_failed:{cid}", "layer_assets": layer_assets}
        layer_img = Image.open(layer_path).convert("RGB")
        layer_img = _prepare_frame(layer_img, ZOOM_W, ZOOM_H)
        _paste_layer_into_slot(canvas, layer_img, list(slot.get("bbox_norm") or [0.2, 0.15, 0.8, 0.8]))
        layer_assets[f"layer_{cid}"] = layer_rel_path

    dest.parent.mkdir(parents=True, exist_ok=True)
    out = canvas.convert("RGB")
    # 统一到出图像素（候选墙可能用 ZOOM，scene 最终仍会被 apply）
    out = _prepare_frame(out, ZOOM_W, ZOOM_H)
    out.save(dest, "PNG")
    assets = shot.setdefault("assets", {})
    assets["plate"] = plate_rel
    for k, v in layer_assets.items():
        if k.startswith("layer_"):
            assets[k] = v
    shot["scene_source"] = "layered"
    shot["layer_assets"] = layer_assets
    return {"ok": True, "layer_assets": layer_assets, "path": str(dest)}


def _failing_character_ids(identity: dict[str, Any]) -> list[str]:
    ids: list[str] = []
    subject = str(identity.get("character_id") or "")
    threshold = float(identity.get("threshold") or 0.75)
    for row in identity.get("matches") or []:
        cid = str(row.get("character_id") or "")
        if not cid:
            continue
        role = str(row.get("role") or "support")
        is_subject = cid == subject or role == "identity"
        cos = row.get("cosine")
        bad = (not row.get("matched")) or (cos is not None and float(cos) < threshold)
        if is_subject and bad:
            ids.append(cid)
        elif (not is_subject) and row.get("matched") and bad:
            ids.append(cid)
    return list(dict.fromkeys(ids))


def regenerate_failing_layers(
    slug: str,
    episode: int,
    shot: dict[str, Any],
    identity: dict[str, Any],
    dest: Path,
    *,
    title: str = "",
    seed: int = 0,
) -> dict[str, Any]:
    """仅重生成身份失败的角色层并重新融合；无分层资产时返回 ok=False。"""
    from tools.drama_characters import character_anchor_prompt, ref_exists
    from tools.drama_qc import _char_ref_path
    from tools.drama_video import ZOOM_H, ZOOM_W, _generate_scene_image, _prepare_frame
    from PIL import Image

    layer_assets = dict(shot.get("layer_assets") or {})
    plate_rel = str(layer_assets.get("plate") or (shot.get("assets") or {}).get("plate") or "")
    if not plate_rel:
        return {"ok": False, "reason": "no_plate"}
    try:
        plate_path = resolve_safe(plate_rel)
    except ValueError:
        return {"ok": False, "reason": "bad_plate"}
    if not plate_path.is_file():
        return {"ok": False, "reason": "missing_plate"}

    plan = shot.get("spatial_plan") if isinstance(shot.get("spatial_plan"), dict) else {}
    if not plan:
        plan = build_spatial_plan(slug, shot)
    fail_ids = set(_failing_character_ids(identity))
    if not fail_ids:
        sid = str((plan or {}).get("identity_subject_id") or identity.get("character_id") or "")
        if sid:
            fail_ids.add(sid)
    if not fail_ids:
        return {"ok": False, "reason": "no_failing_ids"}

    cards = load_characters(slug)
    n = int(shot.get("n") or 0)
    for i, cid in enumerate(sorted(fail_ids)):
        slot = next((s for s in (plan.get("slots") or []) if str(s.get("character_id") or "") == cid), None)
        char = _char_by_id(cards, cid)
        if not slot or not char:
            continue
        ref = _char_ref_path(slug, char)
        if not ref or not ref_exists(slug, char):
            continue
        name = str(char.get("name") or cid)
        anchor = str(slot.get("anchor") or "center_front")
        ap = character_anchor_prompt(char)
        layer_rel_path = layer_rel(slug, episode, n, "character", cid)
        layer_path = resolve_safe(layer_rel_path)
        layer_prompt = (
            f"竖屏9:16单人角色层，{name}，{ap}，"
            f"角色位于{anchor}，半身特写五官清晰，"
            "简洁浅色背景，同一张脸同一套服装，条漫插画，无文字无水印，只有这一个角色"
        )
        ok_layer = bool(
            _generate_scene_image(
                layer_prompt,
                layer_path,
                seed=(seed + 5003 * (i + 1)) & 0x7FFFFFFF,
                slug=slug,
                shot=shot,
                refs=(ref,),
                width=ZOOM_W,
                height=ZOOM_H,
            )
        )
        if not ok_layer:
            return {"ok": False, "reason": f"layer_retry_failed:{cid}"}
        layer_assets[f"layer_{cid}"] = layer_rel_path

    canvas = _prepare_frame(Image.open(plate_path).convert("RGB"), ZOOM_W, ZOOM_H).convert("RGBA")
    for slot in _occlusion_ordered_slots(plan):
        cid = str(slot.get("character_id") or "")
        rel = str(layer_assets.get(f"layer_{cid}") or "")
        if not rel:
            continue
        try:
            path = resolve_safe(rel)
        except ValueError:
            continue
        if not path.is_file():
            continue
        layer_img = _prepare_frame(Image.open(path).convert("RGB"), ZOOM_W, ZOOM_H)
        _paste_layer_into_slot(canvas, layer_img, list(slot.get("bbox_norm") or [0.2, 0.15, 0.8, 0.8]))

    dest.parent.mkdir(parents=True, exist_ok=True)
    _prepare_frame(canvas.convert("RGB"), ZOOM_W, ZOOM_H).save(dest, "PNG")
    shot["layer_assets"] = layer_assets
    shot["scene_source"] = "layered"
    assets = shot.setdefault("assets", {})
    assets["plate"] = plate_rel
    for k, v in layer_assets.items():
        if k.startswith("layer_"):
            assets[k] = v
    return {"ok": True, "layer_assets": layer_assets, "regenerated": sorted(fail_ids)}
