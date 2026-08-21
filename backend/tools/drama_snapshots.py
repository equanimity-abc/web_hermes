"""R6: per-episode shots.json + scene asset snapshots with undo/restore.

Snapshots live under `dramas/{slug}/videos/epNN/.snapshots/`. Each snapshot
is a timestamp-scoped copy of shots.json plus the scene PNGs that existed at
shoot time, so restoring a previous version also restores locked frames.

This module does NOT touch agent/loop.py. Workbench service layer calls it
*before* mutating operations (patch_shot / patch_shots / choose_candidate /
upload_shot_scene / generate_candidates / save_script / classify_shots).
"""

from __future__ import annotations

import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tools.drama_shots import shot_assets
from tools.workspace import resolve_safe

MAX_SNAPSHOTS = 20
_SID_RE = re.compile(r"^[0-9]{14}_[a-z0-9_-]+$")


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")


def snap_rel(slug: str, episode: int, sid: str = "") -> str:
    base = f"dramas/{slug}/videos/ep{episode:02d}/.snapshots"
    return f"{base}/{sid}" if sid else base


def _snap_dir(slug: str, episode: int) -> Path:
    return resolve_safe(snap_rel(slug, episode))


def _snap_json_rel(slug: str, episode: int, sid: str) -> str:
    return f"{snap_rel(slug, episode)}/{sid}.json"


def _snap_assets_dir(slug: str, episode: int, sid: str) -> Path:
    return _snap_dir(slug, episode) / "assets" / sid


def _scene_path(slug: str, episode: int, n: int, sid: str) -> Path:
    return _snap_assets_dir(slug, episode, sid) / f"shot{n:02d}_scene.png"


def _list_snap_ids(slug: str, episode: int) -> list[str]:
    snap_dir = _snap_dir(slug, episode)
    if not snap_dir.is_dir():
        return []
    ids: list[str] = []
    for path in snap_dir.glob("*.json"):
        sid = path.stem
        if _SID_RE.match(sid):
            ids.append(sid)
    ids.sort()
    return ids


def _enforce_cap(slug: str, episode: int) -> None:
    ids = _list_snap_ids(slug, episode)
    if len(ids) <= MAX_SNAPSHOTS:
        return
    snap_dir = _snap_dir(slug, episode)
    for old in ids[: len(ids) - MAX_SNAPSHOTS]:
        try:
            (snap_dir / f"{old}.json").unlink(missing_ok=True)
        except OSError:
            pass
        assets = snap_dir / "assets" / old
        if assets.is_dir():
            shutil.rmtree(assets, ignore_errors=True)


def take_snapshot(
    slug: str,
    episode: int,
    doc: dict[str, Any] | None,
    *,
    tag: str = "edit",
) -> dict[str, Any] | None:
    """Snapshot current shots.json + existing scene PNGs before a mutation.

    Returns the snapshot metadata, or None when there is no doc yet.
    """
    if doc is None:
        return None
    now = _utc_stamp()
    # Keep sid unique within the same second for burst mutations.
    sid = f"{now}_{tag}"
    counter = 1
    while (resolve_safe(_snap_json_rel(slug, episode, sid))).exists():
        sid = f"{now}_{tag}_{counter}"
        counter += 1

    snap_dir = _snap_dir(slug, episode)
    snap_dir.mkdir(parents=True, exist_ok=True)
    # Copy shots.json (raw, to preserve exact previous content).
    payload = dict(doc)
    payload["_snap"] = {
        "sid": sid,
        "tag": tag,
        "created_at": now,
        "episode": episode,
    }
    (snap_dir / f"{sid}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    # Copy every existing scene asset so restore brings back locked frames.
    saved_scenes = 0
    for shot in doc.get("shots") or []:
        if not isinstance(shot, dict):
            continue
        try:
            n = int(shot.get("n") or 0)
        except (TypeError, ValueError):
            continue
        if n < 1:
            continue
        rel = str(((shot.get("assets") or {}).get("scene") or "").strip() or "")
        if not rel:
            continue
        try:
            src = resolve_safe(rel)
        except ValueError:
            continue
        if not src.is_file():
            continue
        dest = _scene_path(slug, episode, n, sid)
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copy2(src, dest)
            saved_scenes += 1
        except OSError:
            continue
    _enforce_cap(slug, episode)
    return {
        "sid": sid,
        "tag": tag,
        "created_at": now,
        "scenes": saved_scenes,
        "shots": len(doc.get("shots") or []),
    }


def _read_snapshot(slug: str, episode: int, sid: str) -> dict[str, Any] | None:
    sid = str(sid or "").strip()
    if not _SID_RE.match(sid):
        return None
    path = resolve_safe(_snap_json_rel(slug, episode, sid))
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def list_snapshots(slug: str, episode: int) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for sid in reversed(_list_snap_ids(slug, episode)):
        data = _read_snapshot(slug, episode, sid)
        meta = (data or {}).get("_snap") or {}
        out.append(
            {
                "sid": sid,
                "tag": str(meta.get("tag") or "edit"),
                "created_at": str(meta.get("created_at") or ""),
                "shots": int(meta.get("shots") or len((data or {}).get("shots") or []) or 0),
                "scenes": int(meta.get("scenes") or 0),
            }
        )
    return out


def restore_snapshot(slug: str, episode: int, sid: str) -> dict[str, Any]:
    """Overwrite shots.json with the snapshot and restore its scene assets."""
    data = _read_snapshot(slug, episode, sid)
    if data is None:
        raise LookupError(f"快照不存在：{sid}")
    # Remove the marker added by take_snapshot so save_doc normalization is clean.
    data.pop("_snap", None)
    data["slug"] = slug
    data["episode"] = int(episode)

    from tools.drama_shots import load_doc, save_doc

    # Restore binary scene assets first (they already exist on the shot doc paths).
    assets_dir = _snap_assets_dir(slug, episode, sid)
    restored_scenes = 0
    if assets_dir.is_dir():
        for scene_file in assets_dir.glob("shot*_scene.png"):
            try:
                n = int(re.match(r"shot(\d+)_scene\.png", scene_file.name).group(1))  # type: ignore[union-attr]
            except (AttributeError, ValueError):
                continue
            dest = resolve_safe(shot_assets(slug, episode, n)["scene"])
            dest.parent.mkdir(parents=True, exist_ok=True)
            try:
                shutil.copy2(scene_file, dest)
                restored_scenes += 1
            except OSError:
                continue

    existing = load_doc(slug, episode)
    from tools.drama_shots import normalize_doc

    merged = normalize_doc(data, slug, episode)
    # Carry over assets dicts for shots that exist in the snapshot (normalize keeps them).
    save_doc(merged)
    return {
        "sid": sid,
        "episode": int(episode),
        "restored_scenes": restored_scenes,
        "shots": len(merged.get("shots") or []),
        "had_previous": existing is not None,
    }


def drop_snapshot(slug: str, episode: int, sid: str) -> dict[str, Any]:
    sid = str(sid or "").strip()
    if not _SID_RE.match(sid):
        raise LookupError("非法的快照 id")
    snap_dir = _snap_dir(slug, episode)
    try:
        (snap_dir / f"{sid}.json").unlink(missing_ok=True)
    except OSError as e:
        raise LookupError(f"快照不存在：{sid}") from e
    assets = snap_dir / "assets" / sid
    if assets.is_dir():
        shutil.rmtree(assets, ignore_errors=True)
    return {"ok": True, "sid": sid}