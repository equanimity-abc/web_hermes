"""跨镜头角色追踪：记录已通过身份验收的脸轨迹。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tools.workspace import resolve_safe


def track_rel(slug: str, episode: int) -> str:
    return f"dramas/{slug}/videos/ep{int(episode):02d}/.track/faces.json"


def track_path(slug: str, episode: int) -> Path:
    path = resolve_safe(track_rel(slug, episode))
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def load_track(slug: str, episode: int) -> dict[str, Any]:
    path = track_path(slug, episode)
    if not path.is_file():
        return {"version": 1, "characters": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"version": 1, "characters": {}}
    if not isinstance(data, dict):
        return {"version": 1, "characters": {}}
    chars = data.get("characters")
    if not isinstance(chars, dict):
        chars = {}
    return {"version": int(data.get("version") or 1), "characters": chars}


def save_track(slug: str, episode: int, doc: dict[str, Any]) -> None:
    path = track_path(slug, episode)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")


def speaker_face_bbox(slug: str, episode: int, shot: dict[str, Any]) -> list[float] | None:
    """口型可用：本镜 identity.matches 中 speaker/identity 的 bbox。"""
    identity = shot.get("identity") if isinstance(shot.get("identity"), dict) else {}
    subject = str(
        (identity or {}).get("character_id")
        or (shot.get("spatial_plan") or {}).get("subject_id")
        or ""
    )
    for row in (identity or {}).get("matches") or []:
        if str(row.get("character_id") or "") == subject and row.get("bbox"):
            return list(row["bbox"])
    for row in (identity or {}).get("matches") or []:
        if row.get("role") == "identity" and row.get("bbox"):
            return list(row["bbox"])
    # 回退 track last
    if subject:
        last = ((load_track(slug, episode).get("characters") or {}).get(subject) or {}).get("last")
        if isinstance(last, dict) and last.get("bbox"):
            return list(last["bbox"])
    return None
