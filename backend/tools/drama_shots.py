"""Episode shot document — source of truth for D0 assetization.

Markdown scripts remain the authoring format. After parse/render, each
episode has `videos/epNN/shots.json` plus per-shot clip files so a single
shot can be rebuilt without touching the others.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tools.drama_characters import (
    infer_roles_from_dialogue,
    load_characters,
    normalize_roles,
    resolve_role_ids,
    roles_key,
)
from tools.drama_models import apply_shot_class, infer_kind, infer_size, infer_speaker, normalize_kind, normalize_size
from tools.workspace import resolve_safe

DEFAULT_FADE_SEC = 0.32
MIN_PLAY_SEC = 0.25
I2V_MODES = ("off", "auto", "on")


def normalize_i2v_mode(raw: Any) -> str:
    mode = str(raw or "auto").strip().lower()
    return mode if mode in I2V_MODES else "auto"


TRANSITIONS = (
    "auto",
    "cut",
    "fade",
    "fadeblack",
    "fadewhite",
    "wipeleft",
    "wiperight",
    "slideleft",
    "slideright",
    "slideup",
    "slidedown",
    "dissolve",
)

LAYERS = ("scene", "overlay", "voice", "clip")
EXTRA_LAYERS = ("motion", "lip", "mix", "assemble")
RENDER_LAYERS = (*LAYERS, "assemble", "motion", "lip")
LOCK_TOKENS = (*LAYERS, "shot", "kind", "motion", "lip")
CANDIDATE_COUNT = 4
WALL_MAX = 12
LAYER_LABELS = {
    "scene": "画面",
    "overlay": "字幕",
    "voice": "配音",
    "clip": "成片",
    "motion": "运动",
    "lip": "口型",
    "mix": "混音",
    "assemble": "整集拼接",
    "shot": "整镜",
}
_CONTENT_KEYS = ("画面", "对白", "字幕", "角色", "duration", "timing")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_episode_qc(raw: dict[str, Any]) -> dict[str, Any]:
    from tools.drama_qc import normalize_episode_qc

    return normalize_episode_qc(raw.get("qc"))


def _normalize_shot_qc(raw: dict[str, Any]) -> dict[str, Any] | None:
    from tools.drama_qc import normalize_shot_qc

    return normalize_shot_qc(raw.get("qc"))


def _normalize_shot_keys(slug: str, episode: int, raw: dict[str, Any]) -> list[dict[str, Any]]:
    from tools.drama_keys import normalize_keys

    return normalize_keys(slug, episode, raw)


def normalize_shot_timeline(raw: dict[str, Any]) -> dict[str, float | str]:
    trim_in = max(0.0, float(raw.get("trim_in") or 0))
    trim_out = max(0.0, float(raw.get("trim_out") or 0))
    try:
        volume = float(raw.get("volume") if raw.get("volume") is not None else 1.0)
    except (TypeError, ValueError):
        volume = 1.0
    volume = max(0.0, min(volume, 2.0))
    transition = str(raw.get("transition") or "auto").strip() or "auto"
    if transition not in TRANSITIONS:
        transition = "auto"
    return {
        "trim_in": round(trim_in, 3),
        "trim_out": round(trim_out, 3),
        "volume": round(volume, 2),
        "transition": transition,
    }


def _shot_numbers(shots: list[dict[str, Any]]) -> list[int]:
    out: list[int] = []
    for shot in shots:
        try:
            n = int(shot.get("n") or 0)
        except (TypeError, ValueError):
            continue
        if n > 0:
            out.append(n)
    return sorted(set(out))


def normalize_timeline(raw: Any, shots: list[dict[str, Any]]) -> dict[str, Any]:
    nums = _shot_numbers(shots)
    data = raw if isinstance(raw, dict) else {}
    order_raw = data.get("order")
    order: list[int] = []
    seen: set[int] = set()
    if isinstance(order_raw, list):
        for item in order_raw:
            try:
                n = int(item)
            except (TypeError, ValueError):
                continue
            if n in nums and n not in seen:
                order.append(n)
                seen.add(n)
    for n in nums:
        if n not in seen:
            order.append(n)
    try:
        fade = float(data.get("fade_sec") if data.get("fade_sec") is not None else DEFAULT_FADE_SEC)
    except (TypeError, ValueError):
        fade = DEFAULT_FADE_SEC
    fade = max(0.05, min(fade, 1.5))
    return {"order": order, "fade_sec": round(fade, 3)}


def work_rel(slug: str, episode: int) -> str:
    return f"dramas/{slug}/videos/ep{episode:02d}"


def json_rel(slug: str, episode: int) -> str:
    return f"{work_rel(slug, episode)}/shots.json"


def output_rel(slug: str, episode: int) -> str:
    return f"dramas/{slug}/videos/ep{episode:02d}.mp4"


def script_rel(slug: str, episode: int) -> str:
    return f"dramas/{slug}/episodes/ep{episode:02d}.md"


def shot_stem(n: int) -> str:
    return f"shot{int(n):02d}"


def shot_assets(slug: str, episode: int, n: int) -> dict[str, str]:
    base = work_rel(slug, episode)
    stem = shot_stem(n)
    return {
        "scene": f"{base}/{stem}_scene.png",
        "overlay": f"{base}/{stem}_overlay.png",
        "voice": f"{base}/{stem}.mp3",
        "clip": f"{base}/{stem}.mp4",
        "motion": f"{base}/{stem}_motion.mp4",
        "lip": f"{base}/{stem}_lip.mp4",
    }


def candidate_rel(slug: str, episode: int, n: int, cid: str) -> str:
    return f"{work_rel(slug, episode)}/{shot_stem(n)}_cand_{cid}.png"


def normalize_candidates(slug: str, episode: int, n: int, raw: Any) -> list[dict[str, Any]]:
    rows = raw if isinstance(raw, list) else []
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in rows:
        if not isinstance(item, dict):
            continue
        cid = str(item.get("id") or "").strip()
        if not cid or cid in seen:
            continue
        seen.add(cid)
        rel = str(item.get("path") or candidate_rel(slug, episode, n, cid)).replace("\\", "/")
        out.append(
            {
                "id": cid,
                "path": rel,
                "source": str(item.get("source") or "ai"),
                "seed": int(item.get("seed") or 0),
            }
        )
    return out


def find_candidate(shot: dict[str, Any], cid: str) -> dict[str, Any] | None:
    needle = str(cid or "").strip()
    for item in shot.get("candidates") or []:
        if str(item.get("id") or "") == needle:
            return item
    return None


def next_candidate_ids(shot: dict[str, Any], count: int) -> list[str]:
    used = {str(c.get("id") or "") for c in (shot.get("candidates") or [])}
    out: list[str] = []
    i = 1
    while len(out) < max(0, int(count)):
        cid = f"c{i}"
        i += 1
        if cid not in used:
            out.append(cid)
    return out


def prune_candidates(shot: dict[str, Any]) -> None:
    rows = list(shot.get("candidates") or [])
    chosen = str(shot.get("chosen") or "")
    if len(rows) <= WALL_MAX:
        shot["candidates"] = rows
        return
    keep: list[dict[str, Any]] = []
    extras: list[dict[str, Any]] = []
    for item in rows:
        if item.get("id") == chosen or item.get("source") == "upload":
            keep.append(item)
        else:
            extras.append(item)
    need = max(0, WALL_MAX - len(keep))
    shot["candidates"] = keep + extras[-need:]


def load_doc(slug: str, episode: int) -> dict[str, Any] | None:
    rel = json_rel(slug, episode)
    path = resolve_safe(rel)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    return normalize_doc(data, slug, episode)


def save_doc(doc: dict[str, Any]) -> str:
    slug = str(doc.get("slug") or "")
    episode = int(doc.get("episode") or 0)
    if not slug or episode < 1:
        raise ValueError("shots.json 缺少 slug/episode，无法保存")
    doc = normalize_doc(doc, slug, episode)
    rel = json_rel(slug, episode)
    path = resolve_safe(rel)
    path.parent.mkdir(parents=True, exist_ok=True)
    doc["updated_at"] = utc_now()
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return rel


def _as_str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        s = str(item).strip()
        if s and s not in out:
            out.append(s)
    return out


def _asset_exists(rel: str) -> bool:
    try:
        return resolve_safe(rel).is_file() and resolve_safe(rel).stat().st_size > 0
    except ValueError:
        return False


def normalize_shot(slug: str, episode: int, raw: dict[str, Any]) -> dict[str, Any]:
    """Upgrade legacy shot records (pre-D0 flat clip/scene fields) to assets schema."""
    n = int(raw.get("n") or 0)
    defaults = shot_assets(slug, episode, n)
    existing = raw.get("assets") if isinstance(raw.get("assets"), dict) else {}
    assets = {**defaults, **{k: str(v) for k, v in existing.items() if v}}

    # Legacy: top-level "clip": "dramas/.../shot01.mp4"
    legacy_clip = raw.get("clip")
    if isinstance(legacy_clip, str) and legacy_clip.strip() and "/" in legacy_clip:
        assets["clip"] = legacy_clip.strip()

    scene_source = str(raw.get("scene_source") or "")
    legacy_scene = raw.get("scene")
    if legacy_scene in ("ai", "fallback") and not scene_source:
        scene_source = str(legacy_scene)

    need_voice = bool(str(raw.get("对白") or "").strip() or str(raw.get("字幕") or "").strip())
    dirty = _as_str_list(raw.get("dirty"))
    if not dirty and "dirty" not in raw:
        # Fresh legacy docs have no dirty tracking — mark missing layers.
        for layer in LAYERS:
            if layer == "voice" and not need_voice:
                continue
            if not _asset_exists(assets.get(layer) or ""):
                dirty.append(layer)
    locked = _as_str_list(raw.get("locked"))
    status = str(raw.get("status") or "")
    if not status:
        status = "rendered" if _asset_exists(assets.get("clip") or "") and not dirty else (
            "dirty" if dirty else "pending"
        )

    duration = float(raw.get("duration") or 5)
    tl = normalize_shot_timeline(raw)
    shot = {
        "n": n,
        "timing": str(raw.get("timing") or ""),
        "start": float(raw.get("start") or 0),
        "end": float(raw.get("end") or duration),
        "duration": duration,
        "画面": str(raw.get("画面") or ""),
        "对白": str(raw.get("对白") or ""),
        "字幕": str(raw.get("字幕") or ""),
        "角色": normalize_roles(raw.get("角色")),
        "kind": raw.get("kind") or "",
        "size": raw.get("size") or "",
        "speaker": str(raw.get("speaker") or ""),
        "voice": str(raw.get("voice") or ""),
        "camera": str(raw.get("camera") or ""),
        "prompt": str(raw.get("prompt") or ""),
        "trim_in": tl["trim_in"],
        "trim_out": tl["trim_out"],
        "volume": tl["volume"],
        "transition": tl["transition"],
        "i2v": normalize_i2v_mode(raw.get("i2v")),
        "i2v_source": str(raw.get("i2v_source") or ""),
        "i2v_seconds": float(raw.get("i2v_seconds") or 0) or None,
        "i2v_ladder": str(raw.get("i2v_ladder") or ""),
        "i2v_expensive": bool(raw.get("i2v_expensive")),
        "i2v_deferred": bool(raw.get("i2v_deferred")),
        "lip_source": str(raw.get("lip_source") or ""),
        "lip_score": raw.get("lip_score") if isinstance(raw.get("lip_score"), dict) else None,
        "keys": _normalize_shot_keys(slug, episode, raw),
        "identity": raw.get("identity") if isinstance(raw.get("identity"), dict) else None,
        "identity_hint": str(raw.get("identity_hint") or ""),
        "qc": _normalize_shot_qc(raw),
        "locked": locked,
        "dirty": dirty,
        "status": status,
        "scene_source": scene_source,
        "chosen": str(raw.get("chosen") or ""),
        "candidates": normalize_candidates(slug, episode, n, raw.get("candidates")),
        "assets": assets,
    }
    apply_shot_class(shot)
    return shot


def normalize_doc(data: dict[str, Any], slug: str, episode: int) -> dict[str, Any]:
    """Ensure shots.json has D0 fields so PATCH/rerender work on older projects."""
    from tools.drama_director import normalize_coverage

    shots = [normalize_shot(slug, episode, s) for s in (data.get("shots") or []) if isinstance(s, dict)]
    timeline = normalize_timeline(data.get("timeline"), shots)
    return {
        **data,
        "slug": slug,
        "episode": episode,
        "title": data.get("title") or f"第{episode}集",
        "meta": data.get("meta") if isinstance(data.get("meta"), dict) else {},
        "script_path": str(data.get("script_path") or script_rel(slug, episode)),
        "work_dir": str(data.get("work_dir") or work_rel(slug, episode)),
        "output": str(data.get("output") or output_rel(slug, episode)),
        "count": len(shots),
        "shots": shots,
        "timeline": timeline,
        "coverage": normalize_coverage(data.get("coverage")),
        "qc": _normalize_episode_qc(data),
        "style_id": str(data.get("style_id") or ""),
        "updated_at": str(data.get("updated_at") or utc_now()),
    }


def empty_shot(slug: str, episode: int, raw: dict[str, Any]) -> dict[str, Any]:
    n = int(raw.get("n") or 0)
    assets = shot_assets(slug, episode, n)
    duration = float(raw.get("duration") or 5)
    shot = {
        "n": n,
        "timing": str(raw.get("timing") or ""),
        "start": float(raw.get("start") or 0),
        "end": float(raw.get("end") or duration),
        "duration": duration,
        "画面": str(raw.get("画面") or ""),
        "对白": str(raw.get("对白") or ""),
        "字幕": str(raw.get("字幕") or ""),
        "角色": normalize_roles(raw.get("角色")),
        "kind": raw.get("kind") or "",
        "size": raw.get("size") or "",
        "speaker": str(raw.get("speaker") or ""),
        "voice": str(raw.get("voice") or ""),
        "camera": str(raw.get("camera") or ""),
        "prompt": str(raw.get("prompt") or ""),
        "locked": _as_str_list(raw.get("locked")),
        "dirty": list(LAYERS),
        "status": "pending",
        "scene_source": str(raw.get("scene_source") or ""),
        "chosen": str(raw.get("chosen") or ""),
        "candidates": normalize_candidates(slug, episode, n, raw.get("candidates")),
        "trim_in": 0.0,
        "trim_out": 0.0,
        "volume": 1.0,
        "transition": "auto",
        "i2v": "auto",
        "i2v_source": "",
        "assets": assets,
    }
    apply_shot_class(shot)
    return shot


def infer_dirty(old: dict[str, Any], new_content: dict[str, Any]) -> list[str]:
    dirty: list[str] = []

    def changed(key: str) -> bool:
        if key == "duration":
            try:
                return abs(float(old.get(key) or 0) - float(new_content.get(key) or 0)) > 0.05
            except (TypeError, ValueError):
                return True
        return str(old.get(key) or "") != str(new_content.get(key) or "")

    if changed("画面"):
        dirty.extend(["scene", "clip"])
    if changed("对白"):
        dirty.extend(["voice", "overlay", "clip", "lip"])
    if changed("字幕"):
        dirty.extend(["overlay", "clip"])
    if roles_key(old.get("角色")) != roles_key(new_content.get("角色")):
        dirty.extend(["scene", "voice", "clip"])
    if changed("speaker"):
        dirty.extend(["lip", "clip"])
    if changed("timing"):
        dirty.extend(["clip"])
    if str(old.get("camera") or "") != str(new_content.get("camera") or "") and str(
        new_content.get("camera") or ""
    ):
        if str(old.get("camera") or ""):
            dirty.extend(["clip", "motion"])
    if changed("kind") or changed("size"):
        dirty.extend(["clip", "motion", "lip"])
    if changed("voice"):
        dirty.extend(["voice", "clip"])

    locked = set(_as_str_list(old.get("locked"))) | set(_as_str_list(new_content.get("locked")))
    if "shot" in locked:
        return []
    ordered: list[str] = []
    for layer in (*LAYERS, "motion", "lip"):
        if layer in dirty and layer not in locked and layer not in ordered:
            ordered.append(layer)
    return ordered


def parse_layers(raw: Any, *, extra: tuple[str, ...] = ()) -> list[str]:
    allowed = set(LAYERS) | set(EXTRA_LAYERS) | set(extra)
    if raw is None or raw == "":
        return []
    if isinstance(raw, str):
        parts = [p.strip() for p in raw.split(",")]
    elif isinstance(raw, (list, tuple)):
        parts = [str(x).strip() for x in raw]
    else:
        parts = [str(raw).strip()]
    ordered: list[str] = []
    for part in parts:
        if part in allowed and part not in ordered:
            ordered.append(part)
    return ordered


def layers_for_patch(patch: dict[str, Any], locked: Any = None) -> list[str]:
    dirty: list[str] = []
    if "画面" in patch:
        dirty.extend(["scene", "clip"])
    if "对白" in patch:
        dirty.extend(["voice", "overlay", "clip", "lip"])
    if "字幕" in patch:
        dirty.extend(["overlay", "clip"])
    if "角色" in patch:
        dirty.extend(["scene", "voice", "clip"])
    if "speaker" in patch:
        dirty.extend(["lip", "clip"])
    if "timing" in patch or "duration" in patch or "camera" in patch:
        dirty.extend(["clip", "motion"])
    if "kind" in patch or "size" in patch:
        dirty.extend(["clip", "motion", "lip"])
    if "voice" in patch:
        dirty.extend(["voice", "clip"])
    locked_set = set(_as_str_list(locked))
    if "shot" in locked_set:
        return []
    ordered: list[str] = []
    for layer in (*LAYERS, "motion", "lip"):
        if layer in dirty and layer not in locked_set and layer not in ordered:
            ordered.append(layer)
    return ordered


def apply_patch(shot: dict[str, Any], patch: dict[str, Any]) -> list[str]:
    """Apply field edits and return newly dirtied layers (minus locks)."""
    locked = set(_as_str_list(shot.get("locked")))
    patch = dict(patch or {})
    if "shot" in locked:
        return []
    if "scene" in locked:
        patch.pop("画面", None)
    if "overlay" in locked:
        patch.pop("字幕", None)
    if "voice" in locked and "overlay" in locked:
        patch.pop("对白", None)
    if "clip" in locked:
        for key in ("camera", "duration", "timing", "start", "end", "kind", "size"):
            patch.pop(key, None)
    if "kind" in locked:
        patch.pop("kind", None)
        patch.pop("size", None)

    before = {k: shot.get(k) for k in (*_CONTENT_KEYS, "camera", "kind", "size", "speaker", "voice")}
    for key in ("画面", "对白", "字幕", "timing", "camera"):
        if key in patch and patch[key] is not None:
            shot[key] = str(patch[key])
    if "角色" in patch and patch["角色"] is not None:
        shot["角色"] = normalize_roles(patch["角色"])
    if "kind" in patch and patch["kind"] is not None:
        kind = normalize_kind(patch["kind"])
        if not kind:
            raise ValueError(f"未知镜头类型：{patch['kind']}")
        shot["kind"] = kind
        if "size" not in patch:
            shot["size"] = infer_size({**shot, "size": ""})
    if "size" in patch and patch["size"] is not None:
        size = normalize_size(patch["size"])
        if not size:
            raise ValueError(f"未知景别：{patch['size']}")
        shot["size"] = size
    if "speaker" in patch:
        shot["speaker"] = str(patch["speaker"] or "").strip()
    if "角色" in patch:
        roles = list(shot.get("角色") or [])
        if shot.get("speaker") and shot["speaker"] not in roles:
            shot["speaker"] = str(roles[0] if roles else "")
        if not shot.get("speaker"):
            shot["speaker"] = infer_speaker(shot)
    if "duration" in patch and patch["duration"] is not None:
        shot["duration"] = float(patch["duration"])
    if "start" in patch and patch["start"] is not None:
        shot["start"] = float(patch["start"])
    if "end" in patch and patch["end"] is not None:
        shot["end"] = float(patch["end"])
    dirty = infer_dirty({**shot, **before, "locked": shot.get("locked")}, shot)
    if "duration" in patch and patch["duration"] is not None:
        if "clip" not in dirty and "clip" not in locked:
            dirty.append("clip")
    if str(before.get("kind") or "") != str(shot.get("kind") or "") or str(before.get("size") or "") != str(
        shot.get("size") or ""
    ):
        if "clip" not in dirty and "clip" not in locked:
            dirty.append("clip")
        if "motion" not in dirty:
            dirty.append("motion")
        if "lip" not in dirty:
            dirty.append("lip")
    if str(before.get("speaker") or "") != str(shot.get("speaker") or ""):
        if "lip" not in dirty:
            dirty.append("lip")
        if "clip" not in dirty and "clip" not in locked:
            dirty.append("clip")
    if str(before.get("voice") or "") != str(shot.get("voice") or ""):
        if "voice" not in dirty and "voice" not in locked:
            dirty.append("voice")
        if "clip" not in dirty and "clip" not in locked:
            dirty.append("clip")
    dirty = [layer for layer in dirty if layer not in locked]
    merged = _as_str_list(shot.get("dirty"))
    for layer in dirty:
        if layer not in merged and layer not in locked:
            merged.append(layer)
    shot["dirty"] = [layer for layer in merged if layer not in locked]
    shot["status"] = "dirty" if shot["dirty"] else shot.get("status") or "pending"
    return dirty


def set_shot_locks(
    shot: dict[str, Any],
    *,
    locked: Any = None,
    lock: Any = None,
    unlock: Any = None,
) -> list[str]:
    """Replace or incrementally update locked layers. Locked layers drop out of dirty."""
    current = _as_str_list(shot.get("locked"))
    extra = ("shot", "kind")
    if locked is not None:
        current = parse_layers(locked, extra=extra)
    else:
        for layer in parse_layers(lock, extra=extra):
            if layer not in current:
                current.append(layer)
        drop = set(parse_layers(unlock, extra=extra))
        current = [layer for layer in current if layer not in drop]
    shot["locked"] = [layer for layer in LOCK_TOKENS if layer in current]
    if "shot" in shot["locked"]:
        shot["dirty"] = []
        if shot.get("status") == "dirty":
            shot["status"] = "rendered"
        return list(shot["locked"])
    shot["dirty"] = [layer for layer in _as_str_list(shot.get("dirty")) if layer not in shot["locked"]]
    if not shot["dirty"] and shot.get("status") == "dirty":
        shot["status"] = "rendered"
    return list(shot["locked"])


def merge_from_parsed(
    slug: str,
    episode: int,
    parsed: dict[str, Any],
    *,
    title: str = "",
    existing: dict[str, Any] | None = None,
) -> dict[str, Any]:
    old_by_n = {
        int(s.get("n") or 0): s
        for s in (existing or {}).get("shots") or []
        if s.get("n") is not None
    }
    cards = load_characters(slug)
    shots: list[dict[str, Any]] = []
    for raw in parsed.get("shots") or []:
        rec = empty_shot(slug, episode, raw)
        old = old_by_n.get(rec["n"])
        roles = resolve_role_ids(rec.get("角色"), cards)
        if not roles:
            roles = infer_roles_from_dialogue(str(rec.get("对白") or ""), cards)
        if not roles and old:
            roles = normalize_roles(old.get("角色"))
        rec["角色"] = roles
        if old and "shot" in _as_str_list(old.get("locked")):
            frozen = dict(old)
            frozen["locked"] = _as_str_list(old.get("locked"))
            shots.append(normalize_shot(slug, episode, frozen))
            continue
        if old:
            rec["locked"] = _as_str_list(old.get("locked"))
            locked = set(rec["locked"])
            rec["camera"] = str(old.get("camera") or rec["camera"])
            rec["prompt"] = str(old.get("prompt") or "")
            rec["scene_source"] = str(old.get("scene_source") or "")
            rec["assets"] = {**rec["assets"], **(old.get("assets") or {})}
            rec["candidates"] = normalize_candidates(slug, episode, rec["n"], old.get("candidates"))
            rec["chosen"] = str(old.get("chosen") or "")
            for key in ("trim_in", "trim_out", "volume", "transition", "i2v", "i2v_source", "kind", "size", "speaker", "voice"):
                if key in old:
                    rec[key] = old[key]
            if "kind" in locked:
                rec["kind"] = old.get("kind") or rec.get("kind")
                rec["size"] = old.get("size") or rec.get("size")
            apply_shot_class(rec)
            if "scene" in locked:
                rec["画面"] = str(old.get("画面") or rec["画面"])
                rec["prompt"] = str(old.get("prompt") or rec.get("prompt") or "")
                rec["scene_source"] = str(old.get("scene_source") or rec["scene_source"])
            if "overlay" in locked:
                rec["字幕"] = str(old.get("字幕") or rec["字幕"])
            if "voice" in locked and "overlay" in locked:
                rec["对白"] = str(old.get("对白") or rec["对白"])
            if "clip" in locked:
                rec["duration"] = float(old.get("duration") or rec["duration"])
            rec["dirty"] = infer_dirty(old, rec)
            if not rec["dirty"] and _asset_exists(rec["assets"].get("clip") or ""):
                rec["status"] = "rendered"
                rec["dirty"] = []
                rec["duration"] = float(old.get("duration") or rec["duration"])
            else:
                rec["status"] = "dirty" if rec["dirty"] else "pending"
            if not rec["dirty"]:
                # Keep generated duration from last render when content unchanged.
                rec["duration"] = float(old.get("duration") or rec["duration"])
        else:
            rec["dirty"] = list(LAYERS)
            rec["status"] = "pending"
        need_voice = bool(str(rec.get("对白") or "").strip() or str(rec.get("字幕") or "").strip())
        for layer in LAYERS:
            if layer == "voice" and not need_voice:
                continue
            rel = rec["assets"].get(layer)
            if layer not in rec["locked"] and not _asset_exists(rel or ""):
                if layer not in rec["dirty"]:
                    rec["dirty"].append(layer)
                if rec["status"] == "rendered":
                    rec["status"] = "dirty"
        shots.append(rec)

    kept = {int(s["n"]) for s in shots}
    for n, old in sorted(old_by_n.items()):
        if n in kept:
            continue
        if "shot" in _as_str_list(old.get("locked")):
            frozen = dict(old)
            frozen["locked"] = _as_str_list(old.get("locked"))
            shots.append(normalize_shot(slug, episode, frozen))
    shots.sort(key=lambda s: int(s["n"]))
    existing_tl = (existing or {}).get("timeline")
    timeline = normalize_timeline(existing_tl, shots)

    return {
        "slug": slug,
        "episode": episode,
        "title": title or parsed.get("title") or f"第{episode}集",
        "meta": parsed.get("meta") or {},
        "script_path": script_rel(slug, episode),
        "work_dir": work_rel(slug, episode),
        "output": output_rel(slug, episode),
        "count": len(shots),
        "shots": shots,
        "timeline": timeline,
        "updated_at": utc_now(),
    }


def find_shot(doc: dict[str, Any], n: int) -> dict[str, Any] | None:
    for shot in doc.get("shots") or []:
        if int(shot.get("n") or 0) == int(n):
            return shot
    return None


def clip_list(doc: dict[str, Any]) -> list[tuple[Path, float, str]]:
    clips: list[tuple[Path, float, str]] = []
    for shot in ordered_shots_from_doc(doc):
        rel = (shot.get("assets") or {}).get("clip") or ""
        path = resolve_safe(rel)
        if not path.is_file():
            raise FileNotFoundError(f"缺少镜头成片：{rel}")
        tl = normalize_shot_timeline(shot)
        play = max(MIN_PLAY_SEC, float(shot.get("duration") or 5) - tl["trim_in"] - tl["trim_out"])
        clips.append(
            (
                path,
                play,
                str(shot.get("camera") or "punch_in"),
            )
        )
    return clips


def ordered_shots_from_doc(doc: dict[str, Any]) -> list[dict[str, Any]]:
    shots = doc.get("shots") or []
    by_n = {int(s.get("n") or 0): s for s in shots if s.get("n") is not None}
    timeline = normalize_timeline(doc.get("timeline"), shots)
    out: list[dict[str, Any]] = []
    for n in timeline["order"]:
        shot = by_n.get(int(n))
        if shot is not None:
            out.append(shot)
    for n in sorted(by_n):
        if n not in timeline["order"]:
            out.append(by_n[n])
    return out


def public_shot(shot: dict[str, Any]) -> dict[str, Any]:
    tl = normalize_shot_timeline(shot)
    return {
        "n": shot.get("n"),
        "timing": shot.get("timing"),
        "duration": shot.get("duration"),
        "画面": shot.get("画面"),
        "对白": shot.get("对白"),
        "字幕": shot.get("字幕"),
        "角色": normalize_roles(shot.get("角色")),
        "kind": infer_kind(shot),
        "size": infer_size(shot),
        "speaker": infer_speaker(shot),
        "voice": shot.get("voice") or "",
        "camera": shot.get("camera"),
        "trim_in": tl["trim_in"],
        "trim_out": tl["trim_out"],
        "volume": tl["volume"],
        "transition": tl["transition"],
        "i2v": normalize_i2v_mode(shot.get("i2v")),
        "i2v_source": shot.get("i2v_source") or "",
        "lip_source": shot.get("lip_source") or "",
        "lip_score": shot.get("lip_score") or None,
        "keys": list(shot.get("keys") or []),
        "identity": shot.get("identity") if isinstance(shot.get("identity"), dict) else None,
        "identity_hint": shot.get("identity_hint") or "",
        "qc": shot.get("qc") if isinstance(shot.get("qc"), dict) else None,
        "locked": shot.get("locked") or [],
        "dirty": shot.get("dirty") or [],
        "status": shot.get("status"),
        "scene_source": shot.get("scene_source"),
        "chosen": shot.get("chosen") or "",
        "candidates": list(shot.get("candidates") or []),
        "assets": shot.get("assets") or {},
        "clip": (shot.get("assets") or {}).get("clip"),
    }


def script_impact(
    existing: dict[str, Any] | None,
    merged: dict[str, Any],
    *,
    old_meta: dict[str, Any] | None = None,
    new_meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compare shots.json before/after a script sync. Frozen shots stay out of affected."""
    old_by = {
        int(s.get("n") or 0): s
        for s in (existing or {}).get("shots") or []
        if s.get("n") is not None
    }
    items: list[dict[str, Any]] = []
    for shot in merged.get("shots") or []:
        n = int(shot.get("n") or 0)
        old = old_by.get(n)
        frozen = "shot" in _as_str_list(shot.get("locked"))
        changed: list[str] = []
        if old is None:
            changed = ["新增"]
        else:
            for key in ("画面", "对白", "字幕", "timing"):
                if str(old.get(key) or "") != str(shot.get(key) or ""):
                    changed.append(key)
            if roles_key(old.get("角色")) != roles_key(shot.get("角色")):
                changed.append("角色")
        items.append(
            {
                "n": n,
                "frozen": frozen,
                "changed": changed,
                "dirty": list(shot.get("dirty") or []),
                "locked": list(shot.get("locked") or []),
                "status": shot.get("status"),
            }
        )
    meta_changed: list[str] = []
    for key in ("钩子", "悬念", "时长"):
        if str((old_meta or {}).get(key) or "") != str((new_meta or {}).get(key) or ""):
            meta_changed.append(key)
    affected = [x["n"] for x in items if x["changed"] and not x["frozen"]]
    frozen = [x["n"] for x in items if x["frozen"]]
    parts: list[str] = []
    if affected:
        parts.append("影响 Shot " + "/".join(str(n) for n in affected))
    if frozen:
        parts.append("已锁 Shot " + "/".join(str(n) for n in frozen) + " 未改")
    if meta_changed:
        parts.append("元数据：" + "、".join(meta_changed))
    return {
        "meta_changed": meta_changed,
        "shots": items,
        "affected": affected,
        "frozen": frozen,
        "summary": "；".join(parts) or "没有分镜改动",
    }
