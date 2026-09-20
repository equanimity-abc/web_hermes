"""ArcFace face detection / embedding + character ref validation.

Extracted from ``drama_qc`` after identity verification was removed. These
helpers remain in use by lip sync (``drama_lip``) and the character workflow.
"""

from __future__ import annotations

import math
import threading
from pathlib import Path
from typing import Any


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
_arcface_lock = threading.RLock()
# 竖屏漫剧常用 1080×1920 / 1600×2848；det=640 易漏检二次元小脸。
_ARCFACE_DET_SIZE = (960, 960)
_ARCFACE_DET_SIZE_FALLBACK = (1280, 1280)
_ARCFACE_DET_SIZE_LARGE = (1600, 1600)
_ARCFACE_DET_THRESH_DEFAULT = 0.5
_ARCFACE_DET_THRESH_RELAXED = (0.35, 0.25)
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
            _arcface_app.prepare(ctx_id=-1, det_size=_ARCFACE_DET_SIZE)
        return _arcface_app
def _arcface_faces(path: Path) -> tuple[list[dict[str, Any]], str]:
    """检测图中全部人脸：[{emb, bbox, area}]。

    InsightFace 期望 BGR；0 脸时降 det_thresh、升 det_size，必要时轻量放大再检
    （二次元/侧脸/小脸常见漏检，不换模型、不改图语义）。
    """
    try:
        import insightface.app  # type: ignore  # noqa: F401
    except ImportError:
        return [], "no_insightface"
    try:
        from PIL import Image
        import numpy as np

        rgb = np.asarray(Image.open(path).convert("RGB"))
        img = np.ascontiguousarray(rgb[:, :, ::-1])  # BGR
        h, w = int(img.shape[0]), int(img.shape[1])

        def _collect(raw_faces: Any) -> list[dict[str, Any]]:
            out: list[dict[str, Any]] = []
            for face in raw_faces or []:
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
                        "img_w": w,
                        "img_h": h,
                    }
                )
            return out

        def _scale_boxes(rows: list[dict[str, Any]], sx: float, sy: float) -> list[dict[str, Any]]:
            scaled: list[dict[str, Any]] = []
            for row in rows:
                box = list(row.get("bbox") or [])
                if len(box) != 4:
                    continue
                nb = [box[0] / sx, box[1] / sy, box[2] / sx, box[3] / sy]
                area = max(0.0, (nb[2] - nb[0]) * (nb[3] - nb[1]))
                scaled.append(
                    {
                        **row,
                        "bbox": nb,
                        "area": area,
                        "img_w": w,
                        "img_h": h,
                    }
                )
            return scaled

        # get + 偶发升档 prepare 需串行，避免并行镜互相改 det_size
        with _arcface_lock:
            app = _arcface_singleton()
            if app is None:
                return [], "no_insightface"
            rows = _collect(app.get(img))
            if not rows:
                attempts: list[tuple[tuple[int, int], float]] = [
                    (_ARCFACE_DET_SIZE_FALLBACK, _ARCFACE_DET_THRESH_DEFAULT),
                    (_ARCFACE_DET_SIZE_FALLBACK, _ARCFACE_DET_THRESH_RELAXED[0]),
                    (_ARCFACE_DET_SIZE_LARGE, _ARCFACE_DET_THRESH_RELAXED[0]),
                    (_ARCFACE_DET_SIZE_LARGE, _ARCFACE_DET_THRESH_RELAXED[1]),
                ]
                for size, thresh in attempts:
                    try:
                        app.prepare(ctx_id=-1, det_size=size, det_thresh=thresh)
                    except TypeError:
                        app.prepare(ctx_id=-1, det_size=size)
                    rows = _collect(app.get(img))
                    if rows:
                        break
                if not rows and max(h, w) < 1600:
                    # 小图二次元：放大后再检，bbox 映射回原图
                    scale = 1600.0 / float(max(h, w))
                    nh, nw = max(1, int(round(h * scale))), max(1, int(round(w * scale)))
                    try:
                        from PIL import Image as _PILImage

                        big_rgb = np.asarray(
                            _PILImage.fromarray(rgb).resize((nw, nh), _PILImage.Resampling.BICUBIC)
                        )
                    except Exception:
                        big_rgb = np.asarray(
                            Image.fromarray(rgb).resize((nw, nh), Image.BICUBIC)
                        )
                    big = np.ascontiguousarray(big_rgb[:, :, ::-1])
                    try:
                        app.prepare(
                            ctx_id=-1,
                            det_size=_ARCFACE_DET_SIZE_FALLBACK,
                            det_thresh=_ARCFACE_DET_THRESH_RELAXED[1],
                        )
                    except TypeError:
                        app.prepare(ctx_id=-1, det_size=_ARCFACE_DET_SIZE_FALLBACK)
                    rows = _scale_boxes(_collect(app.get(big)), scale, scale)
                if not rows:
                    # 二次元正脸特写常见：脸贴边/大眼平涂。加边距再以更低阈值检一次。
                    try:
                        pad = max(32, int(round(0.12 * max(h, w))))
                        canvas = np.full((h + 2 * pad, w + 2 * pad, 3), 245, dtype=rgb.dtype)
                        canvas[pad : pad + h, pad : pad + w] = rgb
                        padded = np.ascontiguousarray(canvas[:, :, ::-1])
                        try:
                            app.prepare(
                                ctx_id=-1,
                                det_size=_ARCFACE_DET_SIZE_LARGE,
                                det_thresh=0.15,
                            )
                        except TypeError:
                            app.prepare(ctx_id=-1, det_size=_ARCFACE_DET_SIZE_LARGE)
                        padded_rows = _collect(app.get(padded))
                        if padded_rows:
                            rows = []
                            for row in padded_rows:
                                box = list(row.get("bbox") or [])
                                if len(box) != 4:
                                    continue
                                nb = [box[0] - pad, box[1] - pad, box[2] - pad, box[3] - pad]
                                area = max(0.0, (nb[2] - nb[0]) * (nb[3] - nb[1]))
                                rows.append({**row, "bbox": nb, "area": area, "img_w": w, "img_h": h})
                    except Exception:
                        pass
                try:
                    app.prepare(
                        ctx_id=-1,
                        det_size=_ARCFACE_DET_SIZE,
                        det_thresh=_ARCFACE_DET_THRESH_DEFAULT,
                    )
                except TypeError:
                    app.prepare(ctx_id=-1, det_size=_ARCFACE_DET_SIZE)
        if not rows:
            return [], "no_face"
        return rows, "arcface"
    except Exception:
        return [], "arcface_error"
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

    返回字段含诊断信息：``path`` / ``size_bytes`` / ``width`` / ``height`` /
    ``face_count`` / ``method`` / ``reason`` / ``hint``。
    """
    meta: dict[str, Any] = {
        "path": str(ref_path) if ref_path is not None else "",
        "size_bytes": 0,
        "width": 0,
        "height": 0,
        "face_count": 0,
    }
    if ref_path is None or not ref_path.is_file() or ref_path.stat().st_size < 32:
        return {
            "ok": False,
            "reason": "missing_ref",
            "retryable": False,
            "method": "",
            "hint": "定妆图文件缺失或过小",
            **meta,
        }
    try:
        meta["size_bytes"] = int(ref_path.stat().st_size)
        meta["path"] = str(ref_path)
        from PIL import Image

        with Image.open(ref_path) as im:
            meta["width"], meta["height"] = int(im.size[0]), int(im.size[1])
    except Exception:
        pass
    if not _arcface_ready():
        return {
            "ok": False,
            "reason": "no_insightface",
            "retryable": False,
            "method": "",
            "hint": (
                f"InsightFace/ArcFace 未就绪（buffalo_l 未安装或未缓存）；"
                f"文件={ref_path.name} {meta['width']}x{meta['height']} {meta['size_bytes']}B"
            ),
            **meta,
        }
    faces, method = _arcface_faces(ref_path)
    meta["face_count"] = len(faces)
    if not faces:
        return {
            "ok": False,
            "reason": method or "no_face",
            "retryable": method in ("no_face", "no_embedding"),
            "method": method or "",
            "hint": (
                f"InsightFace 在定妆图上检出 0 张脸（method={method or 'no_face'}；"
                f"文件={ref_path.name}；尺寸={meta['width']}x{meta['height']}；"
                f"大小={meta['size_bytes']}B）。"
                f"检测器 buffalo_l 偏真人照片，二次元/平涂特写常见漏检，不代表肉眼无脸。"
            ),
            **meta,
        }
    emb = faces[0].get("emb")
    if emb is None:
        return {
            "ok": False,
            "reason": "no_embedding",
            "retryable": True,
            "method": method or "no_embedding",
            "hint": (
                f"InsightFace 检出 {len(faces)} 张脸但无法提取嵌入（文件={ref_path.name}；"
                f"尺寸={meta['width']}x{meta['height']}）"
            ),
            **meta,
        }
    return {
        "ok": True,
        "reason": "",
        "retryable": True,
        "method": method,
        "dims": len(emb),
        "hint": "",
        **meta,
    }
def format_ref_check_line(label: str, check: dict[str, Any], *, rel: str = "") -> str:
    """One-line diagnostic for logs / Fail Loud messages."""
    name = rel or str(check.get("path") or "").replace("\\", "/").rsplit("/", 1)[-1]
    ok = "通过" if check.get("ok") else "失败"
    return (
        f"{label}[{ok}] file={name} reason={check.get('reason') or '-'} "
        f"method={check.get('method') or '-'} faces={check.get('face_count', 0)} "
        f"size={check.get('width', 0)}x{check.get('height', 0)} "
        f"bytes={check.get('size_bytes', 0)}"
    )


def validate_character_cast_ready(slug: str, char: dict[str, Any]) -> dict[str, Any]:
    """有全身定妆文件即放行（身份/检脸硬校验已拆除）。"""
    from tools.drama_characters import ref_face_rel, ref_rel
    from tools.workspace import resolve_safe

    cid = str(char.get("id") or "").strip()
    name = str(char.get("name") or cid)
    body_rel = str(char.get("ref") or ref_rel(slug, cid)).replace("\\", "/")
    face_rel = str(char.get("face_ref") or ref_face_rel(slug, cid)).replace("\\", "/")
    body_path = face_path = None
    try:
        body_path = resolve_safe(body_rel) if body_rel else None
    except ValueError:
        body_path = None
    try:
        face_path = resolve_safe(face_rel) if face_rel else None
    except ValueError:
        face_path = None
    body_exists = bool(body_path is not None and body_path.is_file() and body_path.stat().st_size >= 32)
    if body_exists:
        return {
            "ok": True,
            "anchor": "body",
            "reason": "qc_disabled",
            "hint": "校验已关闭，有全身定妆即放行",
            "character_id": cid,
            "character_name": name,
        }
    return {
        "ok": False,
        "anchor": "body",
        "reason": "no_body_ref",
        "hint": f"角色「{name}」缺少全身定妆图",
        "character_id": cid,
        "character_name": name,
    }


