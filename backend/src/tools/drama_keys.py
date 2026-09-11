"""Sparse keyframes for solo action shots (Q6, degraded mock / flow tween).

3–5 poses on `keys[]`. Adjacent keys tween into motion.mp4. Changing a pose
dirties motion/clip only — voice is never rebuilt. Multi-character action is
out of Q6 scope.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tools.drama_characters import load_characters, normalize_roles, resolve_shot_characters
from tools.drama_models import infer_kind, load_models
from tools.drama_shots import shot_stem, work_rel
from tools.workspace import resolve_safe

MIN_KEYS = 3
MAX_KEYS = 5
POSES = ("起手", "蓄力", "击中", "余势", "收势")
DEFAULT_POSES = ("起手", "击中", "收势")


def key_rel(slug: str, episode: int, n: int, kid: str) -> str:
    return f"{work_rel(slug, episode)}/{shot_stem(n)}_{kid}.png"


def key_cand_rel(slug: str, episode: int, n: int, kid: str, cid: str) -> str:
    return f"{work_rel(slug, episode)}/{shot_stem(n)}_{kid}_{cid}.png"


def keys_count(raw: Any) -> int:
    try:
        n = int(raw or MIN_KEYS)
    except (TypeError, ValueError):
        n = MIN_KEYS
    return max(MIN_KEYS, min(n, MAX_KEYS))


def _role_count(shot: dict[str, Any], slug: str = "") -> int:
    n = len(normalize_roles(shot.get("角色")))
    if slug:
        cast = resolve_shot_characters(shot, load_characters(slug))
        n = max(n, len(cast))
    return n


def keys_eligible(shot: dict[str, Any], *, slug: str = "") -> dict[str, Any]:
    kind = infer_kind(shot)
    if kind != "action":
        return {"ok": False, "reason": "仅单人 action 镜可钉稀疏关键帧"}
    if _role_count(shot, slug) > 1:
        return {"ok": False, "reason": "多角色同框动作不在 Q6 验收"}
    if "shot" in (shot.get("locked") or []):
        return {"ok": False, "reason": "整镜已锁定，不能重抽姿态"}
    return {"ok": True, "reason": "", "kind": kind}


def estimate_keys(slug: str, shot: dict[str, Any], *, models: dict[str, Any] | None = None) -> dict[str, Any]:
    models = models or load_models(slug)
    gate = keys_eligible(shot, slug=slug)
    currency = str(models.get("currency") or "CNY")
    n = len([k for k in (shot.get("keys") or []) if isinstance(k, dict)]) or MIN_KEYS
    n = keys_count(n)
    return {
        **gate,
        "count": n,
        "ladder": "L4" if gate["ok"] else "",
        "provider": "mock",
        "cost_per_shot": 0.0,
        "currency": currency,
        "will_run": bool(gate["ok"]),
        "ready": keys_ready(shot),
    }


def _key_file_ok(rel: str) -> bool:
    if not rel:
        return False
    try:
        path = resolve_safe(rel)
    except ValueError:
        return False
    return path.is_file() and path.stat().st_size > 32


def keys_ready(shot: dict[str, Any], *, slug: str | None = None) -> bool:
    if infer_kind(shot) != "action":
        return False
    files = [k for k in (shot.get("keys") or []) if isinstance(k, dict) and _key_file_ok(str(k.get("file") or ""))]
    return len(files) >= MIN_KEYS


def normalize_key(slug: str, episode: int, n: int, raw: dict[str, Any], index: int) -> dict[str, Any]:
    kid = str(raw.get("id") or f"k{index + 1}").strip() or f"k{index + 1}"
    poses = DEFAULT_POSES if index < 3 and len(POSES) >= 3 else POSES
    pose = str(raw.get("pose") or (poses[index] if index < len(poses) else POSES[-1]))
    try:
        t = max(0.0, float(raw.get("t") or 0))
    except (TypeError, ValueError):
        t = 0.0
    cands: list[dict[str, Any]] = []
    for item in raw.get("candidates") or []:
        if not isinstance(item, dict):
            continue
        cid = str(item.get("id") or "").strip()
        if not cid:
            continue
        cands.append(
            {
                "id": cid,
                "path": str(item.get("path") or key_cand_rel(slug, episode, n, kid, cid)),
                "source": str(item.get("source") or "mock"),
            }
        )
    return {
        "id": kid,
        "t": round(t, 3),
        "pose": pose,
        "file": str(raw.get("file") or key_rel(slug, episode, n, kid)).replace("\\", "/"),
        "locked": bool(raw.get("locked")),
        "chosen": str(raw.get("chosen") or ""),
        "candidates": cands,
    }


def normalize_keys(slug: str, episode: int, shot: dict[str, Any]) -> list[dict[str, Any]]:
    n = int(shot.get("n") or 0)
    raw = shot.get("keys") if isinstance(shot.get("keys"), list) else []
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            continue
        rec = normalize_key(slug, episode, n, item, i)
        if rec["id"] in seen:
            continue
        seen.add(rec["id"])
        out.append(rec)
        if len(out) >= MAX_KEYS:
            break
    return out


def find_key(shot: dict[str, Any], kid: str) -> dict[str, Any] | None:
    needle = str(kid or "").strip()
    for item in shot.get("keys") or []:
        if isinstance(item, dict) and str(item.get("id") or "") == needle:
            return item
    return None


def mark_keys_dirty(shot: dict[str, Any]) -> list[str]:
    if "shot" in (shot.get("locked") or []):
        return []
    locked = set(shot.get("locked") or [])
    dirty = list(shot.get("dirty") or [])
    added: list[str] = []
    for layer in ("motion", "clip"):
        if layer in locked or layer in dirty:
            continue
        dirty.append(layer)
        added.append(layer)
    shot["dirty"] = dirty
    if added:
        shot["status"] = "dirty"
    return added


def _pose_list(count: int) -> list[str]:
    count = keys_count(count)
    if count == 3:
        return list(DEFAULT_POSES)
    if count == 4:
        return ["起手", "蓄力", "击中", "收势"]
    return list(POSES[:5])


def seed_keys(slug: str, episode: int, shot: dict[str, Any], count: int = MIN_KEYS) -> list[dict[str, Any]]:
    count = keys_count(count)
    duration = max(0.6, float(shot.get("duration") or 3.0))
    poses = _pose_list(count)
    n = int(shot.get("n") or 0)
    existing = {str(k.get("id") or ""): k for k in (shot.get("keys") or []) if isinstance(k, dict)}
    out: list[dict[str, Any]] = []
    for i, pose in enumerate(poses):
        kid = f"k{i + 1}"
        prev = existing.get(kid) if existing.get(kid, {}).get("locked") else None
        if prev:
            rec = normalize_key(slug, episode, n, prev, i)
        else:
            t = 0.0 if count == 1 else duration * i / (count - 1)
            rec = normalize_key(slug, episode, n, {"id": kid, "pose": pose, "t": t}, i)
        out.append(rec)
    shot["keys"] = out
    return out


def _variant_png(src: Path, dest: Path, *, index: int, seed: int) -> None:
    from PIL import Image, ImageEnhance, ImageOps

    dest.parent.mkdir(parents=True, exist_ok=True)
    img = Image.open(src).convert("RGB")
    w, h = img.size
    dx = ((seed + index * 13) % 17) - 8
    dy = ((seed + index * 29) % 21) - 10
    pad = 24
    canvas = ImageOps.expand(img, border=pad, fill=(18, 18, 24))
    cropped = canvas.crop((pad + dx, pad + dy, pad + dx + w, pad + dy + h)).resize((w, h))
    factor = 0.92 + (index % 5) * 0.04
    cropped = ImageEnhance.Brightness(cropped).enhance(factor)
    cropped = ImageEnhance.Contrast(cropped).enhance(1.05 + index * 0.02)
    cropped.save(dest, "PNG")


def generate_shot_keys(
    slug: str,
    episode: int,
    shot: dict[str, Any],
    *,
    count: int | None = None,
) -> dict[str, Any]:
    gate = keys_eligible(shot, slug=slug)
    if not gate["ok"]:
        raise ValueError(gate["reason"])
    scene_rel = str((shot.get("assets") or {}).get("scene") or "")
    try:
        scene = resolve_safe(scene_rel) if scene_rel else None
    except ValueError:
        scene = None
    if scene is None or not scene.is_file() or scene.stat().st_size < 32:
        raise ValueError("请先锁定/生成画面再钉关键帧")
    n = int(shot.get("n") or 0)
    want = keys_count(count or len(shot.get("keys") or []) or MIN_KEYS)
    keys = seed_keys(slug, episode, shot, want)
    created: list[str] = []
    for i, key in enumerate(keys):
        if key.get("locked") and _key_file_ok(str(key.get("file") or "")):
            continue
        dest = resolve_safe(str(key["file"]))
        cands: list[dict[str, Any]] = []
        for j, cid in enumerate(("a", "b")):
            rel = key_cand_rel(slug, episode, n, str(key["id"]), cid)
            _variant_png(scene, resolve_safe(rel), index=i * 2 + j, seed=n * 17 + i)
            cands.append({"id": cid, "path": rel, "source": "mock"})
        key["candidates"] = cands
        chosen = cands[0]
        _variant_png(scene, dest, index=i, seed=n * 17 + i)
        key["chosen"] = chosen["id"]
        created.append(str(key["id"]))
    mark_keys_dirty(shot)
    return {
        "count": len(keys),
        "created": created,
        "keys": keys,
        "ladder": "L4",
        "voice_rebuilt": False,
        "dirtied": [layer for layer in (shot.get("dirty") or []) if layer in ("motion", "clip")],
    }


def choose_key_pose(shot: dict[str, Any], kid: str, cid: str) -> dict[str, Any]:
    if "shot" in (shot.get("locked") or []):
        raise ValueError("整镜已锁定，不能换姿态")
    key = find_key(shot, kid)
    if key is None:
        raise ValueError(f"找不到关键帧 {kid}")
    if key.get("locked"):
        raise ValueError("该姿态已锁定")
    cand = next((c for c in (key.get("candidates") or []) if str(c.get("id") or "") == str(cid)), None)
    if cand is None:
        raise ValueError(f"找不到姿态候选 {cid}")
    src = resolve_safe(str(cand.get("path") or ""))
    dest = resolve_safe(str(key.get("file") or ""))
    if not src.is_file():
        raise FileNotFoundError(f"候选图不存在：{cand.get('path')}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    import shutil

    shutil.copyfile(src, dest)
    key["chosen"] = str(cand.get("id") or "")
    mark_keys_dirty(shot)
    return key


def upload_key_pose(slug: str, episode: int, shot: dict[str, Any], kid: str, data: bytes) -> dict[str, Any]:
    if "shot" in (shot.get("locked") or []):
        raise ValueError("整镜已锁定，不能换姿态")
    key = find_key(shot, kid)
    if key is None:
        raise ValueError(f"找不到关键帧 {kid}")
    if key.get("locked"):
        raise ValueError("该姿态已锁定")
    if not data:
        raise ValueError("图片不能为空")
    n = int(shot.get("n") or 0)
    cid = f"u{len(key.get('candidates') or []) + 1}"
    rel = key_cand_rel(slug, episode, n, str(key["id"]), cid)
    dest = resolve_safe(rel)
    from io import BytesIO

    from PIL import Image

    dest.parent.mkdir(parents=True, exist_ok=True)
    Image.open(BytesIO(data)).convert("RGB").save(dest, "PNG")
    rec = {"id": cid, "path": rel, "source": "upload"}
    key["candidates"] = list(key.get("candidates") or []) + [rec]
    import shutil

    shutil.copyfile(dest, resolve_safe(str(key["file"])))
    key["chosen"] = cid
    mark_keys_dirty(shot)
    return key


def lock_key_pose(shot: dict[str, Any], kid: str, locked: bool = True) -> dict[str, Any]:
    key = find_key(shot, kid)
    if key is None:
        raise ValueError(f"找不到关键帧 {kid}")
    key["locked"] = bool(locked)
    return key


def key_paths(shot: dict[str, Any]) -> list[Path]:
    out: list[Path] = []
    for item in shot.get("keys") or []:
        if not isinstance(item, dict):
            continue
        rel = str(item.get("file") or "")
        if not _key_file_ok(rel):
            continue
        out.append(resolve_safe(rel))
    return out


def compose_keys_motion(scene: Path, dest: Path, shot: dict[str, Any], seconds: float) -> bool:
    """Tween adjacent key PNGs into motion.mp4 (mock Ken Burns + xfade)."""
    paths = key_paths(shot)
    if len(paths) < MIN_KEYS:
        if scene.is_file():
            paths = [scene] * MIN_KEYS
        else:
            return False
    from tools.drama_i2v import _concat_motion, _kenburns_motion_mp4

    total = max(2.4, float(seconds or 3.0))
    piece = max(1.2, total / len(paths))
    tmps: list[Path] = []
    acc: Path | None = None
    extras: list[Path] = []
    try:
        for i, src in enumerate(paths):
            tmp = dest.with_suffix(f".k{i}.mp4")
            cam = "punch_in" if i % 2 == 0 else "pull_out"
            _kenburns_motion_mp4(src, tmp, {**shot, "camera": shot.get("camera") or cam}, piece)
            tmps.append(tmp)
        acc = tmps[0]
        for i, nxt in enumerate(tmps[1:], start=1):
            out = dest.with_suffix(f".m{i}.mp4")
            extras.append(out)
            if not _concat_motion(acc, nxt, out):
                return False
            acc = out
        dest.parent.mkdir(parents=True, exist_ok=True)
        if acc and acc != dest:
            acc.replace(dest)
        return dest.is_file() and dest.stat().st_size > 500
    except Exception:
        return False
    finally:
        for tmp in (*tmps, *extras):
            if tmp.exists() and tmp != dest:
                try:
                    tmp.unlink()
                except OSError:
                    pass
