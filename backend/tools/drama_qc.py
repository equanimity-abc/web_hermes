"""QC scripts (Q4 identity, Q7 episode gate).

Identity / lip / flicker are per-shot. Loudness is episode-level and only
remixes mix — never per-shot clips. Missing deps or files → status=skipped
(never counted as pass). `n/a` checks are not required and do not block.
"""

from __future__ import annotations

import math
import os
import re
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path
from typing import Any

from tools.drama_characters import (
    find_character,
    load_characters,
    ref_exists,
    ref_rel,
    resolve_shot_characters,
)
from tools.drama_models import infer_kind, infer_speaker, load_models
from tools.drama_shots import load_doc, ordered_shots_from_doc
from tools.workspace import resolve_safe

DEFAULT_IDENTITY_MIN = 0.75
DEFAULT_SSIM_MIN = 0.85
DEFAULT_LUFS_TARGET = -14.0
DEFAULT_LUFS_MIN = -16.0
DEFAULT_LUFS_MAX = -12.0
DEFAULT_TRUE_PEAK = -1.0
DEFAULT_LSE_C_MIN = 0.15
DEFAULT_LSE_D_MAX = 0.9
HINT_FAIL = "低于 0.75，请重抽首帧（不重配音）"
HINT_SKIPPED = "脚本未能出分，不得记为通过"
LUFS_I_RE = re.compile(r"I:\s*(-?[\d.]+)\s*LUFS", re.I)
LUFS_PEAK_RE = re.compile(r"(?:True peak|Peak):\s*(-?[\d.]+)\s*dBTP", re.I)
FLICKER_FRAMES = 8


def fail_hint(threshold: float) -> str:
    return f"低于 {threshold:g}，请重抽首帧（不重配音）"


def _qc_float(raw: Any, default: float) -> float:
    try:
        return float(raw if raw is not None else default)
    except (TypeError, ValueError):
        return default


def qc_thresholds(slug: str, models: dict[str, Any] | None = None) -> dict[str, float]:
    models = models or load_models(slug)
    qc = models.get("qc") if isinstance(models.get("qc"), dict) else {}
    return {
        "identity_min": max(0.0, min(1.0, _qc_float(qc.get("identity_min"), DEFAULT_IDENTITY_MIN))),
        "ssim_min": max(0.0, min(1.0, _qc_float(qc.get("ssim_min"), DEFAULT_SSIM_MIN))),
        "lufs_target": _qc_float(qc.get("lufs_target"), DEFAULT_LUFS_TARGET),
        "lufs_min": _qc_float(qc.get("lufs_min"), DEFAULT_LUFS_MIN),
        "lufs_max": _qc_float(qc.get("lufs_max"), DEFAULT_LUFS_MAX),
        "true_peak_dbtp": _qc_float(qc.get("true_peak_dbtp"), DEFAULT_TRUE_PEAK),
        "lse_c_min": _qc_float(qc.get("lse_c_min"), DEFAULT_LSE_C_MIN),
        "lse_d_max": _qc_float(qc.get("lse_d_max"), DEFAULT_LSE_D_MAX),
    }


def identity_threshold(slug: str, models: dict[str, Any] | None = None) -> float:
    return qc_thresholds(slug, models)["identity_min"]


def qc_passed(result: dict[str, Any] | None) -> bool:
    """skipped / missing / n/a is never a pass."""
    if not isinstance(result, dict):
        return False
    if str(result.get("status") or "") != "ok":
        return False
    return bool(result.get("pass"))


def check_allows_pass(result: dict[str, Any] | None) -> bool:
    """Required checks must be ok+pass. n/a is ignored. skipped never allows pass."""
    if not isinstance(result, dict):
        return False
    status = str(result.get("status") or "")
    if status == "n/a" or result.get("required") is False:
        return True
    return qc_passed(result)


def _cosine(a: list[float], b: list[float]) -> float:
    n = min(len(a), len(b))
    if n < 8:
        return 0.0
    xs = a[:n]
    ys = b[:n]
    dot = sum(x * y for x, y in zip(xs, ys))
    na = math.sqrt(sum(x * x for x in xs))
    nb = math.sqrt(sum(y * y for y in ys))
    if na < 1e-9 or nb < 1e-9:
        return 0.0
    return max(-1.0, min(1.0, dot / (na * nb)))


def _hist_embedding(path: Path) -> list[float] | None:
    try:
        from PIL import Image
    except ImportError:
        return None
    try:
        img = Image.open(path).convert("RGB")
        img = img.resize((32, 32))
        pixels = list(img.getdata())
    except OSError:
        return None
    bins = [0.0] * 64
    for r, g, b in pixels:
        key = (r // 64) * 16 + (g // 64) * 4 + (b // 64)
        bins[key] += 1.0
    total = sum(bins) or 1.0
    return [v / total for v in bins]


_arcface_app: Any = None
_arcface_lock = threading.Lock()


def _arcface_ready() -> bool:
    """True only when the buffalo_l pack is already downloaded + extracted.

    insightface's ``FaceAnalysis(...)`` triggers a blocking download when the model
    is missing, which can hang the request path for minutes. Pre-check the cache so
    a missing model degrades gracefully instead of freezing generation.
    """
    try:
        root = Path.home() / ".insightface" / "models" / "buffalo_l"
        return (
            root.is_dir()
            and (root / "det_10g.onnx").is_file()
            and (root / "w600k_r50.onnx").is_file()
        )
    except Exception:
        return False


def _arcface_singleton() -> Any:
    """Lazy singleton so consecutive shots don't rebuild the model (P1-8).

    Returns None (never hangs) when the model pack is not yet cached — callers
    already treat a missing model as a graceful degradation, not a blocker.
    """
    global _arcface_app
    if _arcface_app is not None:
        return _arcface_app
    with _arcface_lock:
        if _arcface_app is None:
            if not _arcface_ready():
                return None
            from insightface.app import FaceAnalysis  # type: ignore

            _arcface_app = FaceAnalysis(name="buffalo_l", providers=["CPUExecutionProvider"])
            _arcface_app.prepare(ctx_id=-1, det_size=(640, 640))
        return _arcface_app


def _arcface_faces(path: Path) -> tuple[list[dict[str, Any]], str]:
    """检测图中全部人脸：[{emb, bbox, area}]。"""
    try:
        import insightface.app  # type: ignore  # noqa: F401
    except ImportError:
        return [], "no_insightface"
    try:
        app = _arcface_singleton()
        from PIL import Image
        import numpy as np

        if app is None:
            return [], "no_insightface"
        img = np.array(Image.open(path).convert("RGB"))
        h, w = img.shape[:2]
        faces = app.get(img)
        if not faces:
            return [], "no_face"
        out: list[dict[str, Any]] = []
        for face in faces:
            emb = getattr(face, "normed_embedding", None)
            if emb is None:
                emb = getattr(face, "embedding", None)
            bbox = getattr(face, "bbox", None)
            if emb is None or bbox is None:
                continue
            try:
                box = [float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])]
                area = max(0.0, (box[2] - box[0]) * (box[3] - box[1]))
            except Exception:
                continue
            out.append(
                {
                    "emb": [float(x) for x in list(emb)],
                    "bbox": box,
                    "area": area,
                    "img_w": int(w),
                    "img_h": int(h),
                }
            )
        if not out:
            return [], "no_embedding"
        return out, "arcface"
    except Exception:
        return [], "arcface_error"


def match_faces_to_refs(
    ref_items: list[dict[str, Any]],
    scene_faces: list[dict[str, Any]],
    *,
    match_floor: float = 0.35,
) -> list[dict[str, Any]]:
    """贪心一对一匹配：ref_items=[{character_id, character_name, emb, ...}]。

    返回每条：character_id, cosine, face_index, bbox, matched。
    """
    unused = set(range(len(scene_faces)))
    # 所有边按相似度降序
    edges: list[tuple[float, int, int]] = []
    for ri, ref in enumerate(ref_items):
        remb = ref.get("emb")
        if not remb:
            continue
        for fi in unused:
            cos = _cosine(list(remb), list(scene_faces[fi]["emb"]))
            edges.append((cos, ri, fi))
    edges.sort(key=lambda e: e[0], reverse=True)
    assigned_ref: set[int] = set()
    assigned_face: set[int] = set()
    picked: dict[int, tuple[float, int]] = {}
    for cos, ri, fi in edges:
        if cos < match_floor:
            break
        if ri in assigned_ref or fi in assigned_face:
            continue
        assigned_ref.add(ri)
        assigned_face.add(fi)
        picked[ri] = (cos, fi)

    results: list[dict[str, Any]] = []
    for ri, ref in enumerate(ref_items):
        row = {
            "character_id": ref.get("character_id") or "",
            "character_name": ref.get("character_name") or "",
            "role": ref.get("role") or "support",
            "matched": False,
            "cosine": None,
            "face_index": None,
            "bbox": None,
            "face_ratio": None,
            "in_slot": None,
        }
        if ri in picked:
            cos, fi = picked[ri]
            face = scene_faces[fi]
            img_w = float(face.get("img_w") or 1)
            img_h = float(face.get("img_h") or 1)
            area = float(face.get("area") or 0)
            row.update(
                {
                    "matched": True,
                    "cosine": round(float(cos), 4),
                    "face_index": fi,
                    "bbox": face.get("bbox"),
                    "face_ratio": round(area / max(img_w * img_h, 1.0), 4),
                }
            )
        results.append(row)
    return results


def _arcface_embedding(
    path: Path,
    *,
    match_to: list[float] | None = None,
) -> tuple[list[float] | None, str]:
    """取图中 ArcFace 嵌入。

    - ``match_to`` 有值：在多人脸中选与之余弦最高的一张（双人镜避免拿错脸）。
    - 否则：取检测框面积最大的脸（比 ``faces[0]`` 顺序更稳）。
    """
    faces, method = _arcface_faces(path)
    if not faces:
        return None, method
    if match_to is not None:
        best = max(faces, key=lambda f: _cosine(match_to, f["emb"]))
        return list(best["emb"]), "arcface"
    best = max(faces, key=lambda f: float(f.get("area") or 0))
    return list(best["emb"]), "arcface"


def validate_character_ref(ref_path: Path | None) -> dict[str, Any]:
    """锁定定妆前的身份就绪校验（纯函数、不改任何状态）。

    用来在「生成定妆 → 锁定」之间把关：刚生成的定妆必须有可检测的人脸 + 可计算的
    ArcFace 嵌入，才允许锁定；否则锁定的定妆在后续抽检时会命中 ``no_face`` /
    ``no_embedding``，而且此时已无法回改（定妆一旦锁定即不可变）。

    区分两类完全不同的失败：
      - 可重试：图本身没人脸/嵌入不出来（no_face / no_embedding）→ 换种子重生成。
      - 不可重试：依赖缺失（no_insightface / arcface_error）→ 快速失败，重生成无用。
    """
    if ref_path is None or not ref_path.is_file() or ref_path.stat().st_size < 32:
        return {
            "ok": False,
            "reason": "missing_ref",
            "retryable": False,
            "method": "",
            "hint": "定妆图文件缺失或过小，需重新生成",
        }
    if not _arcface_ready():
        return {
            "ok": False,
            "reason": "no_insightface",
            "retryable": False,
            "method": "",
            "hint": "身份模型 ArcFace 未就绪（insightface 未安装或 buffalo_l 未缓存）",
        }
    emb, method = _arcface_embedding(ref_path)
    if emb is None:
        retryable = method in ("no_face", "no_embedding")
        return {
            "ok": False,
            "reason": method or "arcface_error",
            "retryable": retryable,
            "method": method or "",
            "hint": (
                "定妆图未检测到可用人脸，需重新生成"
                if retryable
                else "身份嵌入依赖缺失或调用失败，专业档不得记为通过"
            ),
        }
    return {
        "ok": True,
        "reason": "",
        "retryable": True,
        "method": method,
        "dims": len(emb),
        "hint": "",
    }


def score_pair(
    left: Path,
    right: Path,
    *,
    left_emb: list[float] | None = None,
) -> dict[str, Any]:
    if left_emb is None and (not left.is_file() or left.stat().st_size < 32):
        return {"status": "skipped", "reason": "missing_left", "method": "", "cosine": None}
    if not right.is_file() or right.stat().st_size < 32:
        return {"status": "skipped", "reason": "missing_right", "method": "", "cosine": None}

    if left_emb is not None:
        vec_a, method = [float(x) for x in left_emb], "arcface"
    else:
        vec_a, method = _arcface_embedding(left)
    # 右图（本镜画面）按左图定妆嵌入选脸，避免双人镜拿错成配角。
    vec_b, method_b = (
        _arcface_embedding(right, match_to=vec_a) if vec_a is not None else (None, method)
    )

    if vec_a is not None and vec_b is not None and method_b == "arcface":
        cosine = round(_cosine(vec_a, vec_b), 4)
        return {"status": "ok", "reason": "", "method": "arcface", "cosine": cosine}

    # ArcFace 真不可用 → 直方图仅作诊断，专业档不得过关。
    # 模型可用但某一侧没脸/调用失败 → 保留真实 reason，绝不能冒充「ArcFace 不可用」。
    arcface_unavailable = (not _arcface_ready()) or method == "no_insightface" or method_b == "no_insightface"
    if not arcface_unavailable:
        fail_reason = method_b if vec_a is not None else method
        fail_side = "right" if vec_a is not None else "left"
        return {
            "status": "skipped",
            "reason": fail_reason or "no_score",
            "method": fail_reason or "",
            "cosine": None,
            "side": fail_side,
            "hint": (
                "本镜画面未检测到可用人脸"
                if fail_side == "right" and fail_reason == "no_face"
                else "定妆参考图未检测到可用人脸"
                if fail_side == "left" and fail_reason == "no_face"
                else "身份嵌入未能出分"
            ),
        }

    # P1-7: histogram cosine is a meaningless numeric proxy — never counts as pass.
    hist_a = _hist_embedding(left)
    hist_b = _hist_embedding(right)
    if hist_a is None or hist_b is None:
        return {"status": "skipped", "reason": "no_embedder", "method": "skipped", "cosine": None}
    cosine = round(_cosine(hist_a, hist_b), 4)
    return {
        "status": "degraded",
        "reason": "proxy_identity",
        "method": "proxy",
        "cosine": cosine,
        "hint": "缺 ArcFace，直方图余弦不可判定身份（不得记为通过）",
    }


def _subject_character(slug: str, shot: dict[str, Any]) -> dict[str, Any] | None:
    from tools.drama_spatial import identity_subject_character

    return identity_subject_character(slug, shot)


def locked_ref_path(slug: str, shot: dict[str, Any]) -> Path | None:
    char = _subject_character(slug, shot)
    if not char or not char.get("ref_locked") or not ref_exists(slug, char):
        return None
    rel = str(char.get("ref") or ref_rel(slug, str(char.get("id") or "")))
    try:
        path = resolve_safe(rel)
    except ValueError:
        return None
    return path if path.is_file() else None


def _char_ref_path(slug: str, char: dict[str, Any]) -> str | None:
    if not char or not char.get("ref_locked") or not ref_exists(slug, char):
        return None
    rel = str(char.get("ref") or ref_rel(slug, str(char.get("id") or ""))).replace("\\", "/")
    try:
        path = resolve_safe(rel)
    except ValueError:
        return None
    return rel if path.is_file() else None


def locked_refs_for_shot(slug: str, shot: dict[str, Any]) -> list[str]:
    """本镜锁定定妆路径，供出图 ``image`` 参考。

    顺序：身份主体（说话人/主角色）永远在前作为图1，再跟同镜其它可锁脸角色。
    Seedream 多图融合时图1权重最高；若把配角放图1，主体脸会被冲淡，身份 QC 易挂。
    """
    from tools.drama_characters import character_requires_face_identity

    cards = load_characters(slug)
    cast = resolve_shot_characters(shot, cards)
    subject = _subject_character(slug, shot)
    ordered: list[dict[str, Any]] = []
    if subject and character_requires_face_identity(subject):
        ordered.append(subject)
    for char in cast:
        if not character_requires_face_identity(char):
            continue
        cid = str(char.get("id") or "")
        if any(str(x.get("id") or "") == cid for x in ordered):
            continue
        ordered.append(char)

    refs: list[str] = []
    for char in ordered:
        path = _char_ref_path(slug, char)
        if path and path not in refs:
            refs.append(path)
    return refs


def _scene_path(shot: dict[str, Any]) -> Path | None:
    rel = str((shot.get("assets") or {}).get("scene") or "")
    if not rel:
        return None
    try:
        path = resolve_safe(rel)
    except ValueError:
        return None
    return path if path.is_file() and path.stat().st_size > 32 else None


def _same_character(a: dict[str, Any], b: dict[str, Any], slug: str) -> bool:
    ca = _subject_character(slug, a)
    cb = _subject_character(slug, b)
    if ca and cb:
        return str(ca.get("id") or "") == str(cb.get("id") or "")
    return infer_speaker(a) != "" and infer_speaker(a) == infer_speaker(b)


def previous_same_character(slug: str, episode: int, shot: dict[str, Any]) -> dict[str, Any] | None:
    doc = load_doc(slug, episode)
    if not doc:
        return None
    ordered = ordered_shots_from_doc(doc)
    current_n = int(shot.get("n") or 0)
    prev: dict[str, Any] | None = None
    for item in ordered:
        n = int(item.get("n") or 0)
        if n == current_n:
            return prev if prev and _same_character(item, prev, slug) else None
        prev = item
    return None


def _mark_fail_layers(shot: dict[str, Any], layers: tuple[str, ...]) -> list[str]:
    if "shot" in (shot.get("locked") or []):
        return []
    locked = set(shot.get("locked") or [])
    dirty = list(shot.get("dirty") or [])
    added: list[str] = []
    for layer in layers:
        if layer in locked or layer in dirty:
            continue
        dirty.append(layer)
        added.append(layer)
    shot["dirty"] = dirty
    if added:
        shot["status"] = "dirty"
    return added


def _mark_identity_fail(shot: dict[str, Any], threshold: float) -> list[str]:
    shot["identity_hint"] = fail_hint(threshold)
    return _mark_fail_layers(shot, ("scene", "motion", "clip"))


def qc_shot_identity(
    slug: str,
    episode: int,
    shot: dict[str, Any],
    *,
    apply: bool = True,
) -> dict[str, Any]:
    threshold = identity_threshold(slug)
    scene = _scene_path(shot)
    prev = previous_same_character(slug, episode, shot)
    prev_scene = _scene_path(prev) if prev else None
    char = _subject_character(slug, shot)
    char_name = str((char or {}).get("name") or "").strip() or str(infer_speaker(shot) or "").strip()
    kind = infer_kind(shot)
    from tools.drama_characters import character_requires_face_identity, load_characters, resolve_shot_characters
    from tools.drama_spatial import MATCH_FLOOR, face_center_in_slot, slot_for_character

    if char is not None and not character_requires_face_identity(char):
        result = {
            "status": "n/a",
            "pass": False,
            "required": False,
            "reason": "silhouette",
            "method": "",
            "cosine": None,
            "threshold": threshold,
            "hint": "本镜主体为剪影/影子角色，不抽检人脸身份",
            "character_id": (char or {}).get("id") or "",
            "character_name": char_name,
            "checks": [],
            "matches": [],
            "kind": kind,
        }
        if apply:
            shot["identity_hint"] = ""
        shot["identity"] = result
        return result

    if char is None and not infer_speaker(shot) and kind in ("establishing", "crowd", "title", "insert"):
        result = {
            "status": "n/a",
            "pass": False,
            "required": False,
            "reason": "no_character",
            "method": "",
            "cosine": None,
            "threshold": threshold,
            "hint": "本镜无角色，不抽检身份",
            "character_id": "",
            "character_name": char_name,
            "checks": [],
            "matches": [],
            "kind": kind,
        }
        if apply:
            shot["identity_hint"] = ""
        shot["identity"] = result
        return result

    if scene is None:
        result = {
            "status": "skipped",
            "pass": False,
            "required": True,
            "reason": "no_scene",
            "method": "",
            "cosine": None,
            "threshold": threshold,
            "hint": "本镜缺少画面，无法抽检身份",
            "character_id": (char or {}).get("id") or infer_speaker(shot),
            "character_name": char_name,
            "checks": [],
            "matches": [],
            "kind": kind,
        }
        if apply:
            shot["identity_hint"] = str(result.get("hint") or "")
        shot["identity"] = result
        return result

    # 组装本镜需验角色：spatial_plan.slots 优先，否则 subject + 可锁脸 cast
    cards = load_characters(slug)
    cast = resolve_shot_characters(shot, cards)
    plan = shot.get("spatial_plan") if isinstance(shot.get("spatial_plan"), dict) else {}
    slots = list((plan or {}).get("slots") or [])
    identity_chars: list[dict[str, Any]] = []
    if slots:
        by_id = {str(c.get("id") or ""): c for c in cast}
        for slot in slots:
            cid = str(slot.get("character_id") or "")
            c = by_id.get(cid)
            if c is None:
                c = next((x for x in cards if str(x.get("id") or "") == cid), None)
            if c and character_requires_face_identity(c) and _char_ref_path(slug, c):
                identity_chars.append({**c, "_slot_role": slot.get("role") or "support"})
    if not identity_chars and char and _char_ref_path(slug, char):
        identity_chars.append({**char, "_slot_role": "identity"})
    for c in cast:
        if not character_requires_face_identity(c):
            continue
        if not _char_ref_path(slug, c):
            continue
        cid = str(c.get("id") or "")
        if any(str(x.get("id") or "") == cid for x in identity_chars):
            continue
        # 未入 plan 的可锁脸角色：出席则验（support）
        identity_chars.append({**c, "_slot_role": "support"})

    if not identity_chars:
        result = {
            "status": "skipped",
            "pass": False,
            "required": True,
            "reason": "no_locked_ref",
            "method": "",
            "cosine": None,
            "threshold": threshold,
            "hint": "需要锁定角色参考图和本镜画面才能抽检身份",
            "character_id": (char or {}).get("id") or infer_speaker(shot),
            "character_name": char_name,
            "checks": [],
            "matches": [],
            "kind": kind,
        }
        if apply:
            shot["identity_hint"] = str(result.get("hint") or "")
        shot["identity"] = result
        return result

    # 取定妆嵌入
    ref_items: list[dict[str, Any]] = []
    for c in identity_chars:
        cid = str(c.get("id") or "")
        path = _char_ref_path(slug, c)
        if not path:
            continue
        try:
            from tools.drama_series import load_character_embedding, save_character_embedding

            emb = load_character_embedding(slug, cid)
            if emb is None:
                emb, emb_method = _arcface_embedding(resolve_safe(path))
                if emb is not None:
                    save_character_embedding(
                        slug,
                        cid,
                        emb,
                        method=emb_method,
                        ref_rel=str(c.get("ref") or ref_rel(slug, cid)),
                    )
        except Exception:
            emb, _ = _arcface_embedding(resolve_safe(path))
        if emb is None:
            continue
        ref_items.append(
            {
                "character_id": cid,
                "character_name": str(c.get("name") or cid),
                "role": c.get("_slot_role") or "support",
                "emb": emb,
                "ref": path,
            }
        )

    scene_faces, face_method = _arcface_faces(scene)
    checks: list[dict[str, Any]] = []
    matches: list[dict[str, Any]] = []

    if not ref_items:
        result = {
            "status": "skipped",
            "pass": False,
            "required": True,
            "reason": "no_embedding",
            "method": face_method,
            "cosine": None,
            "threshold": threshold,
            "hint": "定妆参考图未能提取人脸嵌入",
            "character_id": (char or {}).get("id") or "",
            "character_name": char_name,
            "checks": [],
            "matches": [],
            "kind": kind,
        }
        if apply:
            shot["identity_hint"] = str(result.get("hint") or "")
        shot["identity"] = result
        return result

    if not scene_faces:
        result = {
            "status": "skipped",
            "pass": False,
            "required": True,
            "reason": face_method or "no_face",
            "method": face_method,
            "cosine": None,
            "threshold": threshold,
            "hint": "本镜画面未检测到可用人脸，无法做身份比对（可重抽画面）",
            "character_id": (char or {}).get("id") or "",
            "character_name": char_name,
            "checks": [],
            "matches": [],
            "kind": kind,
        }
        if apply:
            shot["identity_hint"] = str(result.get("hint") or "")
            _mark_identity_fail(shot, threshold)
        shot["identity"] = result
        return result

    matches = match_faces_to_refs(ref_items, scene_faces, match_floor=MATCH_FLOOR)
    # 槽位对齐
    for row in matches:
        if not row.get("matched") or not row.get("bbox"):
            continue
        slot = slot_for_character(plan, str(row.get("character_id") or ""))
        if not slot:
            row["in_slot"] = None
            continue
        face = next((f for i, f in enumerate(scene_faces) if i == row.get("face_index")), None)
        if not face:
            row["in_slot"] = None
            continue
        row["in_slot"] = face_center_in_slot(
            list(row["bbox"]),
            slot,
            img_w=int(face.get("img_w") or 1),
            img_h=int(face.get("img_h") or 1),
        )
        min_ratio = float(slot.get("min_face_ratio") or 0)
        row["min_face_ratio"] = min_ratio
        row["face_ratio_ok"] = float(row.get("face_ratio") or 0) >= min_ratio if min_ratio > 0 else True

    subject_id = str((char or {}).get("id") or (plan or {}).get("identity_subject_id") or "")
    subject_row = next((m for m in matches if m.get("character_id") == subject_id), None)
    if subject_row is None and matches:
        subject_row = next((m for m in matches if m.get("role") == "identity"), matches[0])

    for row in matches:
        status = "ok" if row.get("matched") and row.get("cosine") is not None else "skipped"
        reason = ""
        if not row.get("matched"):
            reason = "unmatched_face"
        checks.append(
            {
                "status": status,
                "reason": reason,
                "method": "arcface" if status == "ok" else face_method,
                "cosine": row.get("cosine"),
                "kind": "ref",
                "label": f"{row.get('character_name') or row.get('character_id')} 定妆 vs 画面",
                "character_id": row.get("character_id"),
                "character_name": row.get("character_name"),
                "role": row.get("role"),
                "in_slot": row.get("in_slot"),
                "face_ratio": row.get("face_ratio"),
            }
        )

    if prev is not None and prev_scene is not None and subject_row and subject_row.get("matched"):
        # 邻镜同角色：用主体匹配脸 vs 上一镜最大相似
        pair = score_pair(prev_scene, scene, left_emb=None)
        # 用主体定妆对上一镜选脸更稳
        subj_ref = next((r for r in ref_items if r.get("character_id") == subject_row.get("character_id")), None)
        if subj_ref and subj_ref.get("emb"):
            pair = score_pair(prev_scene, scene, left_emb=list(subj_ref["emb"]))
        pair["kind"] = "consecutive"
        pair["label"] = f"Shot {prev.get('n')} vs Shot {shot.get('n')} 同角色"
        pair["prev_shot"] = int(prev.get("n") or 0)
        checks.append(pair)

    # 硬闸：identity/subject 必须匹配且过阈值；support 若匹配到也要过阈值
    failures: list[str] = []
    primary_cosine = None
    for row in matches:
        role = str(row.get("role") or "support")
        is_subject = str(row.get("character_id") or "") == subject_id or role == "identity"
        name = str(row.get("character_name") or row.get("character_id") or "?")
        if is_subject:
            if not row.get("matched"):
                failures.append(f"{name}: 未匹配到人脸")
                continue
            cos = float(row.get("cosine") or 0)
            primary_cosine = cos if primary_cosine is None else primary_cosine
            if subject_id and str(row.get("character_id") or "") == subject_id:
                primary_cosine = cos
            if cos < threshold:
                failures.append(f"{name}: cosine={cos}<{threshold}")
            if row.get("face_ratio_ok") is False:
                failures.append(f"{name}: 脸面积不足")
        else:
            if row.get("matched"):
                cos = float(row.get("cosine") or 0)
                if cos < threshold:
                    failures.append(f"{name}: cosine={cos}<{threshold}")

    passed = not failures
    if primary_cosine is None and subject_row and subject_row.get("cosine") is not None:
        primary_cosine = float(subject_row["cosine"])

    if not passed:
        reason = "unmatched_face" if any("未匹配" in f for f in failures) else "below_threshold"
        hint = "；".join(failures) if failures else fail_hint(threshold)
    else:
        reason = ""
        hint = ""

    result = {
        "status": "ok" if (subject_row and subject_row.get("matched")) or passed else "skipped",
        "pass": passed,
        "required": True,
        "reason": reason if not passed else "",
        "method": "arcface",
        "cosine": round(float(primary_cosine), 4) if primary_cosine is not None else None,
        "threshold": threshold,
        "hint": hint if not passed else "",
        "character_id": (char or {}).get("id") or subject_id,
        "character_name": char_name,
        "checks": checks,
        "matches": matches,
        "kind": kind,
        "dirtied": [],
        "failures": failures,
    }
    # 主体完全没匹配时 status 用 skipped 更贴切
    if subject_row is not None and not subject_row.get("matched"):
        result["status"] = "skipped"
        result["reason"] = result["reason"] or "unmatched_face"
    elif subject_row is not None and subject_row.get("matched"):
        result["status"] = "ok"

    if apply and not passed:
        result["dirtied"] = _mark_identity_fail(shot, threshold)
        shot["identity_hint"] = hint or fail_hint(threshold)
        result["hint"] = shot.get("identity_hint") or hint
    elif apply:
        shot["identity_hint"] = ""
    shot["identity"] = result
    return result


def public_identity(shot: dict[str, Any]) -> dict[str, Any] | None:
    raw = shot.get("identity")
    if isinstance(raw, dict) and raw:
        return raw
    return None


def _ffmpeg_bin() -> str:
    return os.getenv("FFMPEG_BIN", "ffmpeg")


def _asset_file(shot: dict[str, Any], layer: str) -> Path | None:
    rel = str((shot.get("assets") or {}).get(layer) or "")
    if not rel:
        return None
    try:
        path = resolve_safe(rel)
    except ValueError:
        return None
    return path if path.is_file() and path.stat().st_size > 32 else None


def _na_check(reason: str, hint: str = "", **extra: Any) -> dict[str, Any]:
    return {
        "status": "n/a",
        "pass": False,
        "required": False,
        "reason": reason,
        "hint": hint,
        "dirtied": [],
        **extra,
    }


def _skip_check(reason: str, hint: str = HINT_SKIPPED, **extra: Any) -> dict[str, Any]:
    return {
        "status": "skipped",
        "pass": False,
        "required": True,
        "reason": reason,
        "hint": hint,
        "dirtied": [],
        **extra,
    }


def qc_shot_lip(slug: str, shot: dict[str, Any], *, apply: bool = True) -> dict[str, Any]:
    from tools.drama_lip import lip_eligible, lip_rel
    from tools.drama_lse import score_lip

    n = int(shot.get("n") or 0)
    episode = int(shot.get("_episode") or 0)
    gate = lip_eligible(shot)
    if not gate["ok"]:
        result = _na_check(gate.get("reason") or "not_eligible", hint=str(gate.get("reason") or "本镜不开口型"))
        shot["qc_lip"] = result
        return result
    thresholds = qc_thresholds(slug)
    lip_path = _asset_file(shot, "lip")
    if lip_path is None and episode and n:
        try:
            cand = resolve_safe(lip_rel(slug, episode, n))
            if cand.is_file() and cand.stat().st_size > 32:
                lip_path = cand
        except ValueError:
            lip_path = None
    source = str(shot.get("lip_source") or "")
    if source == "fallback":
        result = {
            "status": "ok",
            "pass": False,
            "required": True,
            "reason": "fallback",
            "hint": "口型回退闭口静图，不得记为通过",
            "method": "proxy",
            "lse_c": None,
            "lse_d": None,
            "dirtied": [],
        }
        if apply:
            result["dirtied"] = _mark_fail_layers(shot, ("lip", "clip"))
        shot["qc_lip"] = result
        return result
    score = shot.get("lip_score") if isinstance(shot.get("lip_score"), dict) else None
    if (not score or score.get("status") != "ok") and lip_path is not None:
        voice = _asset_file(shot, "voice")
        score = score_lip(lip_path, voice)
        if apply:
            shot["lip_score"] = score
    if not isinstance(score, dict) or score.get("status") != "ok":
        result = _skip_check(
            (score or {}).get("reason") if isinstance(score, dict) else "no_lip_score",
            hint="口型脚本未能出分，不得记为通过",
            method=(score or {}).get("method") if isinstance(score, dict) else "",
            lse_c=None,
            lse_d=None,
        )
        shot["qc_lip"] = result
        return result
    lse_c = float(score.get("lse_c") or 0)
    lse_d = float(score.get("lse_d") or 0)
    passed = lse_c >= thresholds["lse_c_min"] and lse_d <= thresholds["lse_d_max"]
    result = {
        "status": "ok",
        "pass": passed,
        "required": True,
        "reason": "" if passed else "below_threshold",
        "hint": "" if passed else "口型分数低于 mock 基线",
        "method": score.get("method") or "proxy",
        "lse_c": lse_c,
        "lse_d": lse_d,
        "lse_c_min": thresholds["lse_c_min"],
        "lse_d_max": thresholds["lse_d_max"],
        "dirtied": [],
    }
    if apply and not passed:
        result["dirtied"] = _mark_fail_layers(shot, ("lip", "clip"))
    shot["qc_lip"] = result
    return result


def _ssim_gray(left: Any, right: Any) -> float:
    if left.size != right.size:
        right = right.resize(left.size)
    w, h = left.size
    n = w * h
    if n < 16:
        return 0.0
    xs = list(left.getdata())
    ys = list(right.getdata())
    mx = sum(xs) / n
    my = sum(ys) / n
    vx = sum((x - mx) ** 2 for x in xs) / n
    vy = sum((y - my) ** 2 for y in ys) / n
    cxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / n
    c1 = (0.01 * 255) ** 2
    c2 = (0.03 * 255) ** 2
    den = (mx * mx + my * my + c1) * (vx + vy + c2)
    if den <= 1e-12:
        return 0.0
    return max(0.0, min(1.0, ((2 * mx * my + c1) * (2 * cxy + c2)) / den))


def score_ssim_paths(paths: list[Path]) -> dict[str, Any]:
    try:
        from PIL import Image
    except ImportError:
        return _skip_check("no_pillow", hint="缺少 Pillow，闪烁脚本未能出分，不得记为通过")
    frames = []
    for path in paths:
        try:
            frames.append(Image.open(path).convert("L").resize((48, 48)))
        except OSError:
            continue
    if len(frames) < 2:
        return _skip_check("too_short", hint="帧数不足，闪烁脚本未能出分，不得记为通过")
    scores = [_ssim_gray(frames[i], frames[i + 1]) for i in range(len(frames) - 1)]
    mean = round(sum(scores) / len(scores), 4)
    return {"status": "ok", "method": "ssim", "ssim": mean, "pairs": len(scores)}


def _extract_gray_frames(video: Path, *, count: int = FLICKER_FRAMES) -> list[Path]:
    ff = _ffmpeg_bin()
    if not shutil.which(ff) or not video.is_file():
        return []
    tmp = Path(tempfile.mkdtemp(prefix="drama-qc-"))
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    try:
        proc = subprocess.run(
            [
                ff,
                "-y",
                "-i",
                str(video),
                "-vf",
                f"fps=6,scale=48:48,format=gray",
                "-frames:v",
                str(max(2, count)),
                str(tmp / "f%03d.png"),
            ],
            capture_output=True,
            timeout=40,
            creationflags=creationflags,
        )
        if proc.returncode != 0:
            shutil.rmtree(tmp, ignore_errors=True)
            return []
        return sorted(p for p in tmp.glob("*.png") if p.is_file())
    except (OSError, subprocess.TimeoutExpired):
        shutil.rmtree(tmp, ignore_errors=True)
        return []


def qc_shot_flicker(slug: str, shot: dict[str, Any], *, apply: bool = True) -> dict[str, Any]:
    thresholds = qc_thresholds(slug)
    video = _asset_file(shot, "motion") or _asset_file(shot, "clip")
    if video is None:
        result = _skip_check("no_video", hint="没有运动/成片，闪烁脚本未能出分，不得记为通过")
        shot["qc_flicker"] = result
        return result
    if not shutil.which(_ffmpeg_bin()):
        result = _skip_check("no_ffmpeg", hint="没有 ffmpeg，闪烁脚本未能出分，不得记为通过")
        shot["qc_flicker"] = result
        return result
    frames = _extract_gray_frames(video)
    parent: Path | None = frames[0].parent if frames else None
    try:
        scored = score_ssim_paths(frames)
    finally:
        if parent is not None:
            shutil.rmtree(parent, ignore_errors=True)
    if scored.get("status") != "ok":
        shot["qc_flicker"] = scored
        return scored
    ssim = float(scored.get("ssim") or 0)
    passed = ssim >= thresholds["ssim_min"]
    result = {
        "status": "ok",
        "pass": passed,
        "required": True,
        "reason": "" if passed else "below_threshold",
        "hint": "" if passed else f"闪烁 SSIM {ssim} < {thresholds['ssim_min']}，请重做运动（不重配音）",
        "method": "ssim",
        "ssim": ssim,
        "ssim_min": thresholds["ssim_min"],
        "pairs": scored.get("pairs") or 0,
        "dirtied": [],
    }
    if apply and not passed:
        result["dirtied"] = _mark_fail_layers(shot, ("motion", "clip"))
    shot["qc_flicker"] = result
    return result


def score_loudness(path: Path, thresholds: dict[str, float]) -> dict[str, Any]:
    ff = _ffmpeg_bin()
    if not shutil.which(ff):
        return _skip_check("no_ffmpeg", hint="没有 ffmpeg，响度脚本未能出分，不得记为通过")
    if not path.is_file() or path.stat().st_size < 200:
        return _skip_check("no_mix", hint="没有成片/混音，响度脚本未能出分，不得记为通过")
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    try:
        proc = subprocess.run(
            [ff, "-hide_banner", "-i", str(path), "-af", "ebur128=peak=true", "-f", "null", "-"],
            capture_output=True,
            text=True,
            timeout=60,
            creationflags=creationflags,
        )
    except (OSError, subprocess.TimeoutExpired):
        return _skip_check("ebur128_error", hint="响度脚本未能出分，不得记为通过")
    text = f"{proc.stderr or ''}\n{proc.stdout or ''}"
    i_hits = LUFS_I_RE.findall(text)
    p_hits = LUFS_PEAK_RE.findall(text)
    if not i_hits:
        return _skip_check("no_lufs", hint="未能解析 LUFS，不得记为通过")
    lufs = round(float(i_hits[-1]), 2)
    peak = round(float(p_hits[-1]), 2) if p_hits else None
    in_range = thresholds["lufs_min"] <= lufs <= thresholds["lufs_max"]
    peak_ok = peak is None or peak < thresholds["true_peak_dbtp"]
    passed = in_range and peak_ok
    hint = ""
    if not passed:
        hint = "响度不达标，只重 mix，不重渲各镜 clip"
    return {
        "status": "ok",
        "pass": passed,
        "required": True,
        "reason": "" if passed else "out_of_range",
        "hint": hint,
        "method": "ebur128",
        "lufs": lufs,
        "true_peak": peak,
        "lufs_min": thresholds["lufs_min"],
        "lufs_max": thresholds["lufs_max"],
        "lufs_target": thresholds["lufs_target"],
        "true_peak_dbtp": thresholds["true_peak_dbtp"],
        "fix": "" if passed else "mix",
        "dirtied": [],
    }


def qc_episode_loudness(slug: str, episode: int, *, apply: bool = True) -> dict[str, Any]:
    from tools.drama_shots import output_rel

    thresholds = qc_thresholds(slug)
    try:
        path = resolve_safe(output_rel(slug, episode))
    except ValueError:
        path = None
    result = score_loudness(path, thresholds) if path else _skip_check("no_mix", hint="没有成片/混音，响度脚本未能出分，不得记为通过")
    result["shot"] = None
    return result


def shot_can_pass(bundle: dict[str, Any] | None) -> bool:
    if not isinstance(bundle, dict):
        return False
    return all(check_allows_pass(bundle.get(key)) for key in ("identity", "lip", "flicker"))


def _check_block_reason(label: str, check: dict[str, Any] | None, shot_n: int | None = None) -> str:
    if check_allows_pass(check):
        return ""
    prefix = f"Shot {shot_n} " if shot_n else ""
    status = str((check or {}).get("status") or "missing")
    if status == "skipped":
        return f"{prefix}{label} skipped，不得记为通过"
    if status == "ok" and not (check or {}).get("pass"):
        return f"{prefix}{label} 未通过"
    return f"{prefix}{label} 未出分，不得记为通过"


def qc_shot_bundle(slug: str, episode: int, shot: dict[str, Any], *, apply: bool = True) -> dict[str, Any]:
    shot["_episode"] = episode
    identity = qc_shot_identity(slug, episode, shot, apply=apply)
    lip = qc_shot_lip(slug, shot, apply=apply)
    flicker = qc_shot_flicker(slug, shot, apply=apply)
    shot.pop("_episode", None)
    can_pass = check_allows_pass(identity) and check_allows_pass(lip) and check_allows_pass(flicker)
    prev = shot.get("qc") if isinstance(shot.get("qc"), dict) else {}
    verdict = str(prev.get("verdict") or "待修")
    if verdict == "通过" and not can_pass:
        verdict = "待修"
    if not can_pass:
        verdict = "待修"
    reasons = [
        _check_block_reason("身份", identity, int(shot.get("n") or 0)),
        _check_block_reason("口型", lip, int(shot.get("n") or 0)),
        _check_block_reason("闪烁", flicker, int(shot.get("n") or 0)),
    ]
    bundle = {
        "identity": identity,
        "lip": lip,
        "flicker": flicker,
        "can_pass": can_pass,
        "verdict": verdict if verdict in ("待修", "通过") else "待修",
        "block_reason": next((r for r in reasons if r), ""),
    }
    shot["qc"] = bundle
    return bundle


def normalize_shot_qc(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict) or not raw:
        return None
    verdict = str(raw.get("verdict") or "待修")
    if verdict not in ("待修", "通过"):
        verdict = "待修"
    return {
        "identity": raw.get("identity") if isinstance(raw.get("identity"), dict) else None,
        "lip": raw.get("lip") if isinstance(raw.get("lip"), dict) else None,
        "flicker": raw.get("flicker") if isinstance(raw.get("flicker"), dict) else None,
        "can_pass": bool(raw.get("can_pass")),
        "verdict": verdict,
        "block_reason": str(raw.get("block_reason") or ""),
    }


def normalize_episode_qc(raw: Any) -> dict[str, Any]:
    data = raw if isinstance(raw, dict) else {}
    verdict = str(data.get("verdict") or "待修")
    if verdict not in ("待修", "通过"):
        verdict = "待修"
    status = str(data.get("status") or "pending")
    if status not in ("pending", "review", "passed"):
        status = "pending"
    return {
        "loudness": data.get("loudness") if isinstance(data.get("loudness"), dict) else None,
        "can_pass": bool(data.get("can_pass")),
        "verdict": verdict,
        "status": status,
        "block_reason": str(data.get("block_reason") or ""),
        "updated_at": str(data.get("updated_at") or ""),
        "passed_at": str(data.get("passed_at") or ""),
        "summary": data.get("summary") if isinstance(data.get("summary"), dict) else {},
    }


def public_episode_qc(doc: dict[str, Any] | None) -> dict[str, Any]:
    from tools.drama_shots import ordered_shots_from_doc

    doc = doc or {}
    qc = normalize_episode_qc(doc.get("qc"))
    shots = []
    skipped = 0
    failed = 0
    passed = 0
    na = 0
    for shot in ordered_shots_from_doc(doc) if doc.get("shots") else []:
        bundle = normalize_shot_qc(shot.get("qc")) or {
            "identity": shot.get("identity") if isinstance(shot.get("identity"), dict) else None,
            "lip": None,
            "flicker": None,
            "can_pass": False,
            "verdict": "待修",
            "block_reason": "尚未跑验收",
        }
        for key in ("identity", "lip", "flicker"):
            check = bundle.get(key)
            status = str((check or {}).get("status") or "")
            if status == "n/a" or (check or {}).get("required") is False:
                na += 1
            elif status == "skipped" or not check:
                skipped += 1
            elif qc_passed(check):
                passed += 1
            else:
                failed += 1
        can_shot = all(check_allows_pass(bundle.get(key)) for key in ("identity", "lip", "flicker"))
        reasons = [
            _check_block_reason("身份", bundle.get("identity"), int(shot.get("n") or 0)),
            _check_block_reason("口型", bundle.get("lip"), int(shot.get("n") or 0)),
            _check_block_reason("闪烁", bundle.get("flicker"), int(shot.get("n") or 0)),
        ]
        bundle["can_pass"] = can_shot
        bundle["block_reason"] = next((r for r in reasons if r), "")
        shots.append(
            {
                "n": int(shot.get("n") or 0),
                "kind": infer_kind(shot),
                **bundle,
            }
        )
    loudness = qc.get("loudness")
    can_pass = bool(shots) and all(s.get("can_pass") for s in shots) and check_allows_pass(loudness)
    reasons = [s.get("block_reason") or "" for s in shots]
    reasons.append(_check_block_reason("响度", loudness))
    block = next((r for r in reasons if r), "" if can_pass else "尚未跑验收")
    if not shots:
        can_pass = False
        block = "没有分镜"
    if loudness and str(loudness.get("status") or "") == "skipped":
        can_pass = False
        block = _check_block_reason("响度", loudness) or block
    verdict = "通过" if qc.get("verdict") == "通过" and can_pass else "待修"
    if not can_pass:
        verdict = "待修"
    return {
        "loudness": loudness,
        "shots": shots,
        "can_pass": can_pass,
        "verdict": verdict,
        "status": "passed" if verdict == "通过" else (qc.get("status") or "pending"),
        "block_reason": block,
        "updated_at": qc.get("updated_at") or "",
        "passed_at": qc.get("passed_at") or "",
        "summary": {
            "passed": passed,
            "failed": failed,
            "skipped": skipped,
            "n/a": na,
            "shots": len(shots),
        },
    }


def run_episode_qc(slug: str, episode: int, doc: dict[str, Any], *, apply: bool = True) -> dict[str, Any]:
    from tools.drama_shots import ordered_shots_from_doc, utc_now

    for shot in ordered_shots_from_doc(doc):
        qc_shot_bundle(slug, episode, shot, apply=apply)
    loudness = qc_episode_loudness(slug, episode, apply=apply)
    prev = normalize_episode_qc(doc.get("qc"))
    report = public_episode_qc({**doc, "qc": {**prev, "loudness": loudness}})
    report["loudness"] = loudness
    report["status"] = "passed" if report["verdict"] == "通过" and report["can_pass"] else "review"
    report["updated_at"] = utc_now()
    if not report["can_pass"]:
        report["verdict"] = "待修"
        report["passed_at"] = ""
        report["status"] = "review"
    doc["qc"] = {
        "loudness": loudness,
        "can_pass": report["can_pass"],
        "verdict": report["verdict"],
        "status": report["status"],
        "block_reason": report["block_reason"],
        "updated_at": report["updated_at"],
        "passed_at": report.get("passed_at") or "",
        "summary": report["summary"],
    }
    return public_episode_qc(doc)


def mark_shot_verdict(shot: dict[str, Any], verdict: str) -> dict[str, Any]:
    bundle = normalize_shot_qc(shot.get("qc"))
    if bundle is None:
        raise ValueError("尚未跑验收")
    if verdict == "通过" and not bundle.get("can_pass"):
        raise ValueError(bundle.get("block_reason") or "脚本未通过，不能点通过")
    bundle["verdict"] = "通过" if verdict == "通过" else "待修"
    shot["qc"] = bundle
    return bundle


def mark_episode_passed(doc: dict[str, Any], *, passed: bool) -> dict[str, Any]:
    from tools.drama_shots import utc_now

    report = public_episode_qc(doc)
    if passed and not report["can_pass"]:
        raise ValueError(report.get("block_reason") or "脚本未通过，不能点通过")
    qc = normalize_episode_qc(doc.get("qc"))
    if passed:
        qc["verdict"] = "通过"
        qc["status"] = "passed"
        qc["passed_at"] = utc_now()
        qc["can_pass"] = True
        qc["block_reason"] = ""
        for shot in doc.get("shots") or []:
            if isinstance(shot, dict) and isinstance(shot.get("qc"), dict):
                shot["qc"]["verdict"] = "通过"
    else:
        qc["verdict"] = "待修"
        qc["status"] = "review"
        qc["passed_at"] = ""
        qc["can_pass"] = report["can_pass"]
        qc["block_reason"] = report.get("block_reason") or ""
    doc["qc"] = qc
    return public_episode_qc(doc)


def _shot_block_type(shot: dict[str, Any], bundle: dict[str, Any]) -> list[tuple[str, str]]:
    """R8: classify shot problems into one-screen checklist groups.

    Returns (group, label) pairs. Groups: dirty / fallback / identity / lip /
    flicker / unlocked / voice.
    """
    n = int(shot.get("n") or 0)
    out: list[tuple[str, str]] = []
    dirty = [str(x) for x in (shot.get("dirty") or [])]
    if dirty:
        out.append(("dirty", f"Shot {n} 脏层：{'/'.join(dirty)}"))

    scene_source = str(shot.get("scene_source") or "")
    if scene_source == "fallback":
        out.append(("fallback", f"Shot {n} 画面降级为静图"))
    if str(shot.get("i2v_source") or "") == "fallback":
        out.append(("fallback", f"Shot {n} 运动降级为静图运镜"))
    if str(shot.get("lip_source") or "") == "fallback":
        out.append(("fallback", f"Shot {n} 口型回退闭口"))

    for key, label in (("identity", "身份"), ("lip", "口型"), ("flicker", "闪烁")):
        check = bundle.get(key)
        status = str((check or {}).get("status") or "")
        if status == "skip" or status == "skipped":
            out.append((key, f"Shot {n} {label} skipped（不得记为通过）"))
        elif status == "ok" and not (check or {}).get("pass"):
            out.append((key, f"Shot {n} {label} 未通过"))

    need_voice = bool(str(shot.get("字幕") or shot.get("对白") or "").strip())
    if need_voice:
        voice = _asset_file(shot, "voice")
        if voice is None:
            out.append(("voice", f"Shot {n} 无声（TTS 未生成/失败）"))

    locked = set(shot.get("locked") or [])
    if infer_kind(shot) == "dialogue" and need_voice and "shot" not in locked and "scene" not in locked:
        out.append(("unlocked", f"Shot {n} 有台词镜画面未锁，改剧本可能被覆盖"))

    return out


def qc_episode_checklist(slug: str, episode: int, doc: dict[str, Any]) -> dict[str, Any]:
    """R8: one-screen 'can this episode pass' checklist with one-click reject."""
    from tools.drama_shots import ordered_shots_from_doc

    doc = doc or {}
    ordered = ordered_shots_from_doc(doc)
    rows: list[dict[str, Any]] = []
    groups: dict[str, list[str]] = {}
    order = ("dirty", "fallback", "identity", "lip", "flicker", "voice", "unlocked")
    for shot in ordered:
        bundle = normalize_shot_qc(shot.get("qc")) or {}
        problems = _shot_block_type(shot, bundle)
        row = {
            "n": int(shot.get("n") or 0),
            "kind": infer_kind(shot),
            "can_pass": all(check_allows_pass(bundle.get(key)) for key in ("identity", "lip", "flicker")),
            "verdict": str(bundle.get("verdict") or "待修"),
            "problems": [label for _, label in problems],
        }
        for group, label in problems:
            groups.setdefault(group, []).append(label)
        rows.append(row)

    summary = {g: len(groups.get(g) or []) for g in order}
    summary["total"] = len(rows)
    can_pass = bool(rows) and all(r["can_pass"] for r in rows)
    loudness = normalize_episode_qc(doc.get("qc")).get("loudness")
    if not check_allows_pass(loudness):
        can_pass = False

    reasons = []
    for g in order:
        for label in groups.get(g) or []:
            reasons.append(label)
    if loudness and not check_allows_pass(loudness):
        reasons.append(str((loudness or {}).get("hint") or "响度未达 -14 LUFS"))

    return {
        "slug": slug,
        "episode": episode,
        "can_pass": can_pass,
        "summary": summary,
        "groups": {g: groups.get(g, []) for g in order},
        "shots": rows,
        "block_reason": next(iter(reasons), "" if can_pass else "尚未跑验收"),
    }
