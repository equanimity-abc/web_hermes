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

from tools.workspace import resolve_safe

LAYERS = ("scene", "overlay", "voice", "clip")
_CONTENT_KEYS = ("画面", "对白", "字幕", "duration", "timing")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


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
    }


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
    return data


def save_doc(doc: dict[str, Any]) -> str:
    slug = str(doc["slug"])
    episode = int(doc["episode"])
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


def empty_shot(slug: str, episode: int, raw: dict[str, Any]) -> dict[str, Any]:
    n = int(raw.get("n") or 0)
    assets = shot_assets(slug, episode, n)
    duration = float(raw.get("duration") or 5)
    return {
        "n": n,
        "timing": str(raw.get("timing") or ""),
        "start": float(raw.get("start") or 0),
        "end": float(raw.get("end") or duration),
        "duration": duration,
        "画面": str(raw.get("画面") or ""),
        "对白": str(raw.get("对白") or ""),
        "字幕": str(raw.get("字幕") or ""),
        "camera": str(raw.get("camera") or ""),
        "prompt": str(raw.get("prompt") or ""),
        "locked": _as_str_list(raw.get("locked")),
        "dirty": list(LAYERS),
        "status": "pending",
        "scene_source": str(raw.get("scene_source") or ""),
        "assets": assets,
    }


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
        dirty.extend(["voice", "overlay", "clip"])
    if changed("字幕"):
        dirty.extend(["overlay", "clip"])
    if changed("timing"):
        dirty.extend(["clip"])
    if str(old.get("camera") or "") != str(new_content.get("camera") or "") and str(
        new_content.get("camera") or ""
    ):
        if str(old.get("camera") or ""):
            dirty.extend(["clip"])

    locked = set(_as_str_list(old.get("locked")))
    ordered: list[str] = []
    for layer in LAYERS:
        if layer in dirty and layer not in locked and layer not in ordered:
            ordered.append(layer)
    return ordered


def layers_for_patch(patch: dict[str, Any]) -> list[str]:
    dirty: list[str] = []
    if "画面" in patch:
        dirty.extend(["scene", "clip"])
    if "对白" in patch:
        dirty.extend(["voice", "overlay", "clip"])
    if "字幕" in patch:
        dirty.extend(["overlay", "clip"])
    if "timing" in patch or "duration" in patch or "camera" in patch:
        dirty.extend(["clip"])
    ordered: list[str] = []
    for layer in LAYERS:
        if layer in dirty and layer not in ordered:
            ordered.append(layer)
    return ordered


def apply_patch(shot: dict[str, Any], patch: dict[str, Any]) -> list[str]:
    """Apply field edits and return newly dirtied layers (minus locks)."""
    before = {k: shot.get(k) for k in (*_CONTENT_KEYS, "camera")}
    for key in ("画面", "对白", "字幕", "timing", "camera"):
        if key in patch and patch[key] is not None:
            shot[key] = str(patch[key])
    if "duration" in patch and patch["duration"] is not None:
        shot["duration"] = float(patch["duration"])
    if "start" in patch and patch["start"] is not None:
        shot["start"] = float(patch["start"])
    if "end" in patch and patch["end"] is not None:
        shot["end"] = float(patch["end"])
    dirty = infer_dirty({**shot, **before, "locked": shot.get("locked")}, shot)
    if "duration" in patch and patch["duration"] is not None:
        if "clip" not in dirty:
            dirty.append("clip")
    merged = _as_str_list(shot.get("dirty"))
    for layer in dirty:
        if layer not in merged:
            merged.append(layer)
    shot["dirty"] = merged
    shot["status"] = "dirty" if merged else shot.get("status") or "pending"
    return dirty


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
    shots: list[dict[str, Any]] = []
    for raw in parsed.get("shots") or []:
        rec = empty_shot(slug, episode, raw)
        old = old_by_n.get(rec["n"])
        if old:
            rec["locked"] = _as_str_list(old.get("locked"))
            rec["camera"] = str(old.get("camera") or rec["camera"])
            rec["prompt"] = str(old.get("prompt") or "")
            rec["scene_source"] = str(old.get("scene_source") or "")
            rec["assets"] = {**rec["assets"], **(old.get("assets") or {})}
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
        "updated_at": utc_now(),
    }


def find_shot(doc: dict[str, Any], n: int) -> dict[str, Any] | None:
    for shot in doc.get("shots") or []:
        if int(shot.get("n") or 0) == int(n):
            return shot
    return None


def clip_list(doc: dict[str, Any]) -> list[tuple[Path, float, str]]:
    clips: list[tuple[Path, float, str]] = []
    for shot in doc.get("shots") or []:
        rel = (shot.get("assets") or {}).get("clip") or ""
        path = resolve_safe(rel)
        if not path.is_file():
            raise FileNotFoundError(f"缺少镜头成片：{rel}")
        clips.append(
            (
                path,
                float(shot.get("duration") or 5),
                str(shot.get("camera") or "punch_in"),
            )
        )
    return clips


def public_shot(shot: dict[str, Any]) -> dict[str, Any]:
    return {
        "n": shot.get("n"),
        "timing": shot.get("timing"),
        "duration": shot.get("duration"),
        "画面": shot.get("画面"),
        "对白": shot.get("对白"),
        "字幕": shot.get("字幕"),
        "camera": shot.get("camera"),
        "locked": shot.get("locked") or [],
        "dirty": shot.get("dirty") or [],
        "status": shot.get("status"),
        "scene_source": shot.get("scene_source"),
        "assets": shot.get("assets") or {},
        "clip": (shot.get("assets") or {}).get("clip"),
    }
