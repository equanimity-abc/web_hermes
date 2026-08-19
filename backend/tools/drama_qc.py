"""Identity QC (Q4): locked character ref vs shot face.

Tries InsightFace ArcFace when installed; otherwise a local embedding cosine
so consecutive same-character shots can still produce a score. Missing files
or no comparable pair → status=skipped (never counted as pass).
Failing scores dirty scene/motion only — voice is not rebuilt.
"""

from __future__ import annotations

import math
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

DEFAULT_IDENTITY_MIN = 0.65
HINT_FAIL = "低于 0.65，请重抽首帧（不重配音）"


def fail_hint(threshold: float) -> str:
    return f"低于 {threshold:g}，请重抽首帧（不重配音）"


def identity_threshold(slug: str, models: dict[str, Any] | None = None) -> float:
    models = models or load_models(slug)
    try:
        return max(0.0, min(1.0, float((models.get("qc") or {}).get("identity_min") or DEFAULT_IDENTITY_MIN)))
    except (TypeError, ValueError):
        return DEFAULT_IDENTITY_MIN


def qc_passed(result: dict[str, Any] | None) -> bool:
    """skipped / missing is never a pass."""
    if not isinstance(result, dict):
        return False
    if str(result.get("status") or "") != "ok":
        return False
    return bool(result.get("pass"))


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


def _arcface_embedding(path: Path) -> tuple[list[float] | None, str]:
    try:
        from insightface.app import FaceAnalysis  # type: ignore
    except ImportError:
        return None, "no_insightface"
    try:
        app = FaceAnalysis(name="buffalo_l", providers=["CPUExecutionProvider"])
        app.prepare(ctx_id=-1, det_size=(640, 640))
        from PIL import Image
        import numpy as np

        img = np.array(Image.open(path).convert("RGB"))
        faces = app.get(img)
        if not faces:
            return None, "no_face"
        emb = getattr(faces[0], "normed_embedding", None) or getattr(faces[0], "embedding", None)
        if emb is None:
            return None, "no_embedding"
        return [float(x) for x in list(emb)], "arcface"
    except Exception:
        return None, "arcface_error"


def score_pair(left: Path, right: Path) -> dict[str, Any]:
    if not left.is_file() or left.stat().st_size < 32:
        return {"status": "skipped", "reason": "missing_left", "method": "", "cosine": None}
    if not right.is_file() or right.stat().st_size < 32:
        return {"status": "skipped", "reason": "missing_right", "method": "", "cosine": None}
    vec_a, method = _arcface_embedding(left)
    vec_b, method_b = _arcface_embedding(right) if vec_a is not None else (None, method)
    if vec_a is None or vec_b is None or method_b != "arcface":
        vec_a = _hist_embedding(left)
        vec_b = _hist_embedding(right)
        method = "proxy"
        if vec_a is None or vec_b is None:
            return {"status": "skipped", "reason": "no_embedder", "method": "skipped", "cosine": None}
    cosine = round(_cosine(vec_a, vec_b), 4)
    return {"status": "ok", "reason": "", "method": method, "cosine": cosine}


def _subject_character(slug: str, shot: dict[str, Any]) -> dict[str, Any] | None:
    cards = load_characters(slug)
    speaker = infer_speaker(shot)
    if speaker:
        hit = find_character(cards, speaker)
        if hit:
            return hit
    cast = resolve_shot_characters(shot, cards)
    return cast[0] if cast else None


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


def _mark_identity_fail(shot: dict[str, Any], threshold: float) -> list[str]:
    shot["identity_hint"] = fail_hint(threshold)
    if "shot" in (shot.get("locked") or []):
        return []
    locked = set(shot.get("locked") or [])
    dirty = list(shot.get("dirty") or [])
    added: list[str] = []
    for layer in ("scene", "motion", "clip"):
        if layer in locked or layer in dirty:
            continue
        dirty.append(layer)
        added.append(layer)
    shot["dirty"] = dirty
    if added:
        shot["status"] = "dirty"
    return added


def qc_shot_identity(
    slug: str,
    episode: int,
    shot: dict[str, Any],
    *,
    apply: bool = True,
) -> dict[str, Any]:
    threshold = identity_threshold(slug)
    scene = _scene_path(shot)
    ref = locked_ref_path(slug, shot)
    prev = previous_same_character(slug, episode, shot)
    prev_scene = _scene_path(prev) if prev else None
    char = _subject_character(slug, shot)
    checks: list[dict[str, Any]] = []
    if ref is not None and scene is not None:
        pair = score_pair(ref, scene)
        pair["kind"] = "ref"
        pair["label"] = "锁参考图 vs 本镜画面"
        checks.append(pair)
    if prev is not None and prev_scene is not None and scene is not None:
        pair = score_pair(prev_scene, scene)
        pair["kind"] = "consecutive"
        pair["label"] = f"Shot {prev.get('n')} vs Shot {shot.get('n')} 同角色"
        pair["prev_shot"] = int(prev.get("n") or 0)
        checks.append(pair)

    if not checks:
        result = {
            "status": "skipped",
            "pass": False,
            "reason": "no_locked_ref" if scene and not ref else "no_scene",
            "method": "",
            "cosine": None,
            "threshold": threshold,
            "hint": "需要锁定角色参考图和本镜画面才能抽检身份",
            "character_id": (char or {}).get("id") or infer_speaker(shot),
            "checks": [],
            "kind": infer_kind(shot),
        }
        if apply:
            shot["identity_hint"] = str(result.get("hint") or "")
        shot["identity"] = result
        return result

    ok_checks = [c for c in checks if c.get("status") == "ok" and c.get("cosine") is not None]
    if not ok_checks:
        result = {
            "status": "skipped",
            "pass": False,
            "reason": (checks[0].get("reason") if checks else "no_score"),
            "method": checks[0].get("method") if checks else "",
            "cosine": None,
            "threshold": threshold,
            "hint": "身份脚本未能出分（缺依赖或无人脸），不得记为通过",
            "character_id": (char or {}).get("id") or infer_speaker(shot),
            "checks": checks,
            "kind": infer_kind(shot),
        }
        if apply:
            shot["identity_hint"] = str(result.get("hint") or "")
        shot["identity"] = result
        return result

    # Ref check is authoritative when present; consecutive is always recorded.
    ref_check = next((c for c in ok_checks if c.get("kind") == "ref"), None)
    primary = ref_check or ok_checks[0]
    cosine = float(primary["cosine"])
    passed = cosine >= threshold
    result = {
        "status": "ok",
        "pass": passed,
        "reason": "" if passed else "below_threshold",
        "method": primary.get("method") or "proxy",
        "cosine": cosine,
        "threshold": threshold,
        "hint": "" if passed else fail_hint(threshold),
        "character_id": (char or {}).get("id") or infer_speaker(shot),
        "checks": checks,
        "kind": infer_kind(shot),
        "dirtied": [],
    }
    if apply and not passed:
        result["dirtied"] = _mark_identity_fail(shot, threshold)
        result["hint"] = shot.get("identity_hint") or fail_hint(threshold)
    elif apply:
        shot["identity_hint"] = ""
    shot["identity"] = result
    return result


def public_identity(shot: dict[str, Any]) -> dict[str, Any] | None:
    raw = shot.get("identity")
    if isinstance(raw, dict) and raw:
        return raw
    return None
