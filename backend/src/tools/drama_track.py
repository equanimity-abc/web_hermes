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


def record_shot_identity_pass(
    slug: str,
    episode: int,
    shot: dict[str, Any],
    identity: dict[str, Any],
) -> None:
    """身份验收通过后写入本镜各匹配角色的轨迹。"""
    if not identity.get("pass"):
        return
    doc = load_track(slug, episode)
    chars: dict[str, Any] = doc.setdefault("characters", {})
    sn = int(shot.get("n") or 0)
    scene_rel = str((shot.get("assets") or {}).get("scene") or "")
    for row in identity.get("matches") or []:
        if not row.get("matched"):
            continue
        cid = str(row.get("character_id") or "").strip()
        if not cid:
            continue
        entry = {
            "shot": sn,
            "cosine": row.get("cosine"),
            "bbox": row.get("bbox"),
            "face_ratio": row.get("face_ratio"),
            "scene": scene_rel,
            "in_slot": row.get("in_slot"),
        }
        hist = list((chars.get(cid) or {}).get("history") or [])
        hist = [h for h in hist if int(h.get("shot") or 0) != sn]
        hist.append(entry)
        hist = hist[-12:]
        chars[cid] = {
            "character_name": row.get("character_name") or "",
            "last": entry,
            "history": hist,
        }
    save_track(slug, episode, doc)


def previous_passed_face(slug: str, episode: int, character_id: str, *, before_shot: int) -> dict[str, Any] | None:
    """取本集该角色在 before_shot 之前最近一次通过的脸记录。"""
    cid = str(character_id or "").strip()
    if not cid:
        return None
    doc = load_track(slug, episode)
    hist = list(((doc.get("characters") or {}).get(cid) or {}).get("history") or [])
    prior = [h for h in hist if int(h.get("shot") or 0) < int(before_shot or 0)]
    if not prior:
        return None
    prior.sort(key=lambda h: int(h.get("shot") or 0))
    return prior[-1]


def speaker_face_bbox(slug: str, episode: int, shot: dict[str, Any]) -> list[float] | None:
    """口型可用：本镜 identity.matches 中 speaker/identity 的 bbox。"""
    identity = shot.get("identity") if isinstance(shot.get("identity"), dict) else {}
    subject = str(
        (identity or {}).get("character_id")
        or (shot.get("spatial_plan") or {}).get("identity_subject_id")
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
