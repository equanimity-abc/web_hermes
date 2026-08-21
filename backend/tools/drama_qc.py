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
DEFAULT_SSIM_MIN = 0.85
DEFAULT_LUFS_TARGET = -14.0
DEFAULT_LUFS_MIN = -16.0
DEFAULT_LUFS_MAX = -12.0
DEFAULT_TRUE_PEAK = -1.0
DEFAULT_LSE_C_MIN = 0.0
DEFAULT_LSE_D_MAX = 1.0
HINT_FAIL = "低于 0.65，请重抽首帧（不重配音）"
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


def _char_ref_path(slug: str, char: dict[str, Any]) -> str | None:
    if not char or not char.get("ref_locked") or not ref_exists(slug, char):
        return None
    rel = str(char.get("ref") or ref_rel(slug, str(char.get("id") or "")))
    try:
        path = resolve_safe(rel)
    except ValueError:
        return None
    return str(path) if path.is_file() else None


def locked_refs_for_shot(slug: str, shot: dict[str, Any]) -> list[str]:
    """All locked reference-image paths for characters in this shot (R4 refs)."""
    cards = load_characters(slug)
    cast = resolve_shot_characters(shot, cards)
    refs: list[str] = []
    for char in cast:
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

    kind = infer_kind(shot)
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
            "checks": [],
            "kind": kind,
        }
        if apply:
            shot["identity_hint"] = ""
        shot["identity"] = result
        return result

    if not checks:
        result = {
            "status": "skipped",
            "pass": False,
            "required": True,
            "reason": "no_locked_ref" if scene and not ref else "no_scene",
            "method": "",
            "cosine": None,
            "threshold": threshold,
            "hint": "需要锁定角色参考图和本镜画面才能抽检身份",
            "character_id": (char or {}).get("id") or infer_speaker(shot),
            "checks": [],
            "kind": kind,
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
            "required": True,
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
        "required": True,
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

    need_voice = bool(str(shot.get("对白") or "").strip() or str(shot.get("字幕") or "").strip())
    if need_voice:
        voice = _asset_file(shot, "voice")
        if voice is None:
            out.append(("voice", f"Shot {n} 无声（TTS 未生成/失败）"))

    locked = set(shot.get("locked") or [])
    if infer_kind(shot) == "dialogue" and need_voice and "shot" not in locked and "scene" not in locked:
        out.append(("unlocked", f"Shot {n} 对白镜画面未锁，改剧本可能被覆盖"))

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
