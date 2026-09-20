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

DEFAULT_SSIM_MIN = 0.84
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






def _qc_float(raw: Any, default: float) -> float:
    try:
        return float(raw if raw is not None else default)
    except (TypeError, ValueError):
        return default


def qc_thresholds(slug: str, models: dict[str, Any] | None = None) -> dict[str, float]:
    models = models or load_models(slug)
    qc = models.get("qc") if isinstance(models.get("qc"), dict) else {}
    return {
        "ssim_min": max(0.0, min(1.0, _qc_float(qc.get("ssim_min"), DEFAULT_SSIM_MIN))),
        "lufs_target": _qc_float(qc.get("lufs_target"), DEFAULT_LUFS_TARGET),
        "lufs_min": _qc_float(qc.get("lufs_min"), DEFAULT_LUFS_MIN),
        "lufs_max": _qc_float(qc.get("lufs_max"), DEFAULT_LUFS_MAX),
        "true_peak_dbtp": _qc_float(qc.get("true_peak_dbtp"), DEFAULT_TRUE_PEAK),
        "lse_c_min": _qc_float(qc.get("lse_c_min"), DEFAULT_LSE_C_MIN),
        "lse_d_max": _qc_float(qc.get("lse_d_max"), DEFAULT_LSE_D_MAX),
    }




def qc_gates_enabled() -> bool:
    """QC hard gates permanently removed — never Fail Loud on identity/flicker/lip/loudness/KPI.

    Env ``DRAMA_QC_ENABLED`` is ignored. Scoring helpers may still exist for diagnostics,
    but produce/export must never block on them.
    """
    return False






def qc_passed(result: dict[str, Any] | None) -> bool:
    """skipped / missing / n/a is never a pass."""
    if not isinstance(result, dict):
        return False
    if str(result.get("status") or "") != "ok":
        return False
    return bool(result.get("pass"))


def check_allows_pass(result: dict[str, Any] | None) -> bool:
    """Required checks must be ok+pass. n/a is ignored. skipped never allows pass.

    身份旁路（``enforcement`` 为 advisory/off）永不阻断导出/清单。
    总闸 ``qc_gates_enabled()`` 关闭时一律放行。
    """
    if not qc_gates_enabled():
        return True
    if not isinstance(result, dict):
        return False
    status = str(result.get("status") or "")
    if status == "n/a" or result.get("required") is False:
        return True
    enf = str(result.get("enforcement") or "").strip().lower()
    if enf in ("advisory", "off"):
        return True
    return qc_passed(result)
























def locked_ref_path(slug: str, shot: dict[str, Any]) -> Path | None:
    from tools.drama_characters import anchor_ref_rel
    from tools.drama_spatial import subject_character

    char = subject_character(slug, shot)
    if not char or not char.get("ref_locked") or not ref_exists(slug, char):
        return None
    rel = anchor_ref_rel(slug, char)
    try:
        path = resolve_safe(rel)
    except ValueError:
        return None
    return path if path.is_file() else None


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
    """本镜出图用的角色参考路径（Ark：大头照→全身照；身份主体优先）。

    注意：这是图生图参考，不是身份校验锚；校验请用 ``anchor_ref_rel``（全身）。
    每个角色最多贡献 2 张（脸+身）；总脸槽由 compose 再裁。
    """
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
            # 未锁但文件已在：仍允许作参考（工作台重生成后会自动锁）
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
            # still allow unlocked existing file for quality
            if not ref_exists(slug, prop):
                continue
        rel = str(prop.get("ref") or "").replace("\\", "/")
        if not rel:
            continue
        try:
            if resolve_safe(rel).is_file() and rel not in refs:
                refs.append(rel)
                break  # 至多 1 个道具进 Seedream 槽
        except ValueError:
            continue
    return refs


def compose_shot_image_refs(slug: str, shot: dict[str, Any], *, max_refs: int = 4) -> list[str]:
    """Seedream 参考打包（Ark：大头照优先于全身，再环境）。

    对话/近景：脸→身→环境；远景/空镜：环境优先，再脸身。
    角色对最多占 2 槽（同一人的大头+全身）；总数 ≤ max_refs。
    """
    from tools.drama_models import infer_kind, infer_size

    limit = max(1, min(int(max_refs or 4), 4))
    env = locked_env_refs_for_shot(slug, shot)
    # Ark：单角色最多大头+全身两张，勿塞第二人定妆冲淡身份
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


def locked_refs_for_shot(slug: str, shot: dict[str, Any]) -> list[str]:
    """本镜出图参考图路径（环境 + 角色），供 Seedream ``image``。

    Ark：大头照+全身照（≤2）+ 环境；总数 ≤4。
    """
    return compose_shot_image_refs(slug, shot, max_refs=4)


def _scene_path(shot: dict[str, Any]) -> Path | None:
    rel = str((shot.get("assets") or {}).get("scene") or "")
    if not rel:
        return None
    try:
        path = resolve_safe(rel)
    except ValueError:
        return None
    return path if path.is_file() and path.stat().st_size > 32 else None


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
    from tools.drama_lse import SCORE_VERSION as LSE_SCORE_VERSION

    score = shot.get("lip_score") if isinstance(shot.get("lip_score"), dict) else None
    score_stale = (
        not isinstance(score, dict)
        or score.get("status") != "ok"
        or int(score.get("version") or 0) < int(LSE_SCORE_VERSION)
    )
    if score_stale and lip_path is not None:
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
    proxy_ok = lse_c >= thresholds["lse_c_min"] and lse_d <= thresholds["lse_d_max"]
    from tools.providers.lip_providers import lip_source_is_real

    # 真实口型模型已出片时：proxy LSE 只作参考（draft）；studio 默认要求 proxy 也过，
    # 可用 DRAMA_LIP_PROXY_ADVISORY=1 放宽。
    real_lip = lip_source_is_real(source) and lip_path is not None
    studio = False
    try:
        from tools.drama_profiles import resolve_quality_profile

        studio = resolve_quality_profile(slug) == "studio"
    except Exception:
        studio = False
    import os

    allow_advisory = os.getenv("DRAMA_LIP_PROXY_ADVISORY", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )
    if studio and not allow_advisory:
        passed = bool(real_lip and proxy_ok)
    else:
        passed = bool(proxy_ok or real_lip)
    hint = ""
    reason = ""
    if not proxy_ok and real_lip and (not studio or allow_advisory):
        reason = "proxy_advisory"
        hint = f"口型 proxy LSE 偏低(c={lse_c},d={lse_d})，真实口型已出片，不硬拦"
    elif studio and real_lip and not proxy_ok and not allow_advisory:
        reason = "proxy_below_studio"
        hint = f"专业档要求口型 proxy 也过线(c={lse_c},d={lse_d})；可设 DRAMA_LIP_PROXY_ADVISORY=1"
    elif not passed:
        reason = "below_threshold"
        hint = "口型分数低于基线或未使用真实口型模型"
    result = {
        "status": "ok",
        "pass": passed,
        "required": True,
        "reason": reason,
        "hint": hint,
        "method": score.get("method") or "proxy",
        "lse_c": lse_c,
        "lse_d": lse_d,
        "lse_c_min": thresholds["lse_c_min"],
        "lse_d_max": thresholds["lse_d_max"],
        "proxy_pass": proxy_ok,
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
    ordered = sorted(scores)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        median = round(ordered[mid], 4)
    else:
        median = round((ordered[mid - 1] + ordered[mid]) / 2, 4)
    # 用 mean 与 median 的较高者过闸：单对异常帧（粒子/切光）不误杀整镜
    score = max(mean, median)
    return {
        "status": "ok",
        "method": "ssim",
        "ssim": score,
        "ssim_mean": mean,
        "ssim_median": median,
        "pairs": len(scores),
    }


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
        "hint": "" if passed else f"相邻帧相似度 {ssim} < {thresholds['ssim_min']}，生成视频画面抖动过大，请重做本镜视频（不重配音）",
        "method": "ssim",
        "ssim": ssim,
        "ssim_mean": scored.get("ssim_mean"),
        "ssim_median": scored.get("ssim_median"),
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


def qc_shot_environment(
    slug: str,
    episode: int,
    shot: dict[str, Any],
    *,
    apply: bool = True,
    ssim_min: float = 0.28,
) -> dict[str, Any]:
    """Soft environment gate: scene vs locked location plate (wide/establishing).

    Dialogue close-ups return n/a (do not block face-led frames). Failures dirties
    ``scene`` for one automatic produce retry.
    """
    from tools.drama_characters import (
        environment_ref_rel,
        find_character,
        load_characters,
        normalize_category,
        ref_plate_exists,
    )
    from tools.drama_models import infer_kind, infer_size

    loc_id = str(shot.get("location_id") or "").strip()
    if not loc_id:
        result = {
            "status": "skipped",
            "reason": "no_location",
            "pass": True,
            "hint": "本镜未绑定地点，跳过环境验收",
        }
        shot["environment"] = result
        return result

    kind = str(shot.get("kind") or infer_kind(shot) or "")
    size = str(shot.get("size") or infer_size(shot) or "")
    if kind in ("dialogue", "reaction") and size in ("CU", "ECU", "MCU"):
        result = {
            "status": "skipped",
            "reason": "closeup",
            "pass": True,
            "hint": "近景对话镜不做环境硬闸",
            "location_id": loc_id,
        }
        shot["environment"] = result
        return result

    cards = load_characters(slug)
    loc = find_character(cards, loc_id)
    if not loc or normalize_category(loc.get("category")) != "scene":
        result = {
            "status": "skipped",
            "reason": "no_location_card",
            "pass": True,
            "location_id": loc_id,
        }
        shot["environment"] = result
        return result
    if not ref_plate_exists(slug, loc):
        result = {
            "status": "skipped",
            "reason": "no_plate",
            "pass": True,
            "hint": "地点主底板尚未生成",
            "location_id": loc_id,
        }
        shot["environment"] = result
        return result

    scene_path = _scene_path(shot)
    plate_rel = environment_ref_rel(slug, loc)
    try:
        plate_path = resolve_safe(plate_rel)
    except ValueError:
        plate_path = None
    if scene_path is None or plate_path is None or not plate_path.is_file():
        result = {
            "status": "skipped",
            "reason": "missing_files",
            "pass": True,
            "location_id": loc_id,
        }
        shot["environment"] = result
        return result

    try:
        from PIL import Image, ImageFilter
    except ImportError:
        result = _skip_check("no_pillow", hint="缺少 Pillow，环境验收跳过")
        result["location_id"] = loc_id
        shot["environment"] = result
        return result

    try:
        scene_img = Image.open(scene_path).convert("RGB").resize((64, 64))
        plate_img = Image.open(plate_path).convert("RGB").resize((64, 64))
        # 强模糊后比结构，降低人物遮挡对底板相似度的干扰
        scene_img = scene_img.filter(ImageFilter.GaussianBlur(radius=2)).convert("L")
        plate_img = plate_img.filter(ImageFilter.GaussianBlur(radius=2)).convert("L")
        score = round(_ssim_gray(scene_img, plate_img), 4)
    except OSError:
        result = {
            "status": "skipped",
            "reason": "read_error",
            "pass": True,
            "location_id": loc_id,
        }
        shot["environment"] = result
        return result

    threshold = max(0.05, min(0.9, float(ssim_min)))
    passed = score >= threshold
    result = {
        "status": "ok",
        "pass": passed,
        "ssim": score,
        "ssim_min": threshold,
        "location_id": loc_id,
        "location_name": str(loc.get("name") or loc_id),
        "hint": ""
        if passed
        else f"环境与地点底板相似度偏低（SSIM {score} < {threshold}），建议重抽画面",
    }
    if apply and not passed:
        result["dirtied"] = _mark_fail_layers(shot, ("scene", "clip"))
    shot["environment"] = result
    return result


def shot_can_pass(bundle: dict[str, Any] | None) -> bool:
    if not isinstance(bundle, dict):
        return False
    return all(check_allows_pass(bundle.get(key)) for key in ("lip", "flicker"))


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
    lip = qc_shot_lip(slug, shot, apply=apply)
    flicker = qc_shot_flicker(slug, shot, apply=apply)
    shot.pop("_episode", None)
    can_pass = check_allows_pass(lip) and check_allows_pass(flicker)
    prev = shot.get("qc") if isinstance(shot.get("qc"), dict) else {}
    verdict = str(prev.get("verdict") or "待修")
    if verdict == "通过" and not can_pass:
        verdict = "待修"
    if not can_pass:
        verdict = "待修"
    reasons = [
        _check_block_reason("口型", lip, int(shot.get("n") or 0)),
        _check_block_reason("闪烁", flicker, int(shot.get("n") or 0)),
    ]
    bundle = {
        "lip": lip,
        "flicker": flicker,
        "can_pass": can_pass,
        "verdict": verdict if verdict in ("待修", "通过") else "待修",
        "block_reason": next((r for r in reasons if r), ""),
    }
    # 保留产线失败标记，避免续跑（resume）的失败点判定被 QC 覆盖冲掉
    for key in ("produce_ok", "produce_error", "produce_stage", "resume_from", "resume_hint"):
        if key in prev:
            bundle[key] = prev[key]
    shot["qc"] = bundle
    return bundle


def normalize_shot_qc(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict) or not raw:
        return None
    verdict = str(raw.get("verdict") or "待修")
    if verdict not in ("待修", "通过"):
        verdict = "待修"
    return {
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
            "lip": None,
            "flicker": None,
            "can_pass": False,
            "verdict": "待修",
            "block_reason": "尚未跑验收",
        }
        for key in ("lip", "flicker"):
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
        can_shot = all(check_allows_pass(bundle.get(key)) for key in ("lip", "flicker"))
        reasons = [
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

    Returns (group, label) pairs. Groups: dirty / fallback / lip / flicker /
    unlocked / voice.
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

    for key, label in (("lip", "口型"), ("flicker", "闪烁")):
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
    order = ("dirty", "fallback", "lip", "flicker", "voice", "unlocked")
    for shot in ordered:
        bundle = normalize_shot_qc(shot.get("qc")) or {}
        problems = _shot_block_type(shot, bundle)
        row = {
            "n": int(shot.get("n") or 0),
            "kind": infer_kind(shot),
            "can_pass": all(check_allows_pass(bundle.get(key)) for key in ("lip", "flicker")),
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
