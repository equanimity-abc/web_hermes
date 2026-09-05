"""历史通过帧记忆（V1 文件索引，非外部向量库）。"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from tools.workspace import resolve_safe


def frames_index_rel(slug: str) -> str:
    return f"dramas/{slug}/.series/frames/index.json"


def frames_index_path(slug: str) -> Path:
    path = resolve_safe(frames_index_rel(slug))
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def load_frame_index(slug: str) -> dict[str, Any]:
    path = frames_index_path(slug)
    if not path.is_file():
        return {"version": 1, "frames": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"version": 1, "frames": []}
    if not isinstance(data, dict):
        return {"version": 1, "frames": []}
    frames = data.get("frames")
    if not isinstance(frames, list):
        frames = []
    return {"version": int(data.get("version") or 1), "frames": frames}


def save_frame_index(slug: str, doc: dict[str, Any]) -> None:
    path = frames_index_path(slug)
    path.parent.mkdir(parents=True, exist_ok=True)
    # 控制体积：每项目最多保留最近 200 条
    frames = list(doc.get("frames") or [])[-200:]
    doc = {"version": 1, "frames": frames}
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")


def _cast_key(cids: list[str]) -> str:
    return ",".join(sorted({str(c).strip() for c in cids if str(c).strip()}))


def add_passed_frame(
    slug: str,
    *,
    episode: int,
    shot: dict[str, Any],
    identity: dict[str, Any],
) -> dict[str, Any] | None:
    """仅身份全过闸后入库。"""
    if not identity.get("pass"):
        return None
    scene = str((shot.get("assets") or {}).get("scene") or "").replace("\\", "/")
    if not scene:
        return None
    try:
        if not resolve_safe(scene).is_file():
            return None
    except ValueError:
        return None
    plan = shot.get("spatial_plan") if isinstance(shot.get("spatial_plan"), dict) else {}
    cids = [
        str(m.get("character_id") or "")
        for m in (identity.get("matches") or [])
        if m.get("matched") and m.get("character_id")
    ]
    if not cids:
        sid = str(identity.get("character_id") or "")
        if sid:
            cids = [sid]
    entry = {
        "episode": int(episode),
        "shot": int(shot.get("n") or 0),
        "scene": scene,
        "character_ids": cids,
        "cast_key": _cast_key(cids),
        "plan_hash": str((plan or {}).get("hash") or ""),
        "identity_subject_id": str((plan or {}).get("identity_subject_id") or identity.get("character_id") or ""),
        "cosine": identity.get("cosine"),
        "ts": int(time.time()),
    }
    doc = load_frame_index(slug)
    # 同镜覆盖
    frames = [
        f
        for f in doc.get("frames") or []
        if not (int(f.get("episode") or 0) == entry["episode"] and int(f.get("shot") or 0) == entry["shot"])
    ]
    frames.append(entry)
    doc["frames"] = frames
    save_frame_index(slug, doc)
    return entry


def search_similar_frames(
    slug: str,
    *,
    character_ids: list[str],
    plan_hash: str = "",
    identity_subject_id: str = "",
    exclude_episode: int | None = None,
    exclude_shot: int | None = None,
    limit: int = 2,
) -> list[dict[str, Any]]:
    """按角色集合 / plan_hash / 主体优先检索历史通过帧。"""
    want = set(str(c).strip() for c in character_ids if str(c).strip())
    cast_key = _cast_key(list(want))
    subj = str(identity_subject_id or "").strip()
    scored: list[tuple[int, dict[str, Any]]] = []
    for frame in load_frame_index(slug).get("frames") or []:
        ep = int(frame.get("episode") or 0)
        sn = int(frame.get("shot") or 0)
        if exclude_episode is not None and exclude_shot is not None:
            if ep == int(exclude_episode) and sn == int(exclude_shot):
                continue
        score = 0
        if cast_key and str(frame.get("cast_key") or "") == cast_key:
            score += 50
        else:
            have = set(str(x) for x in (frame.get("character_ids") or []))
            score += 10 * len(want & have)
        if plan_hash and str(frame.get("plan_hash") or "") == plan_hash:
            score += 30
        if subj and str(frame.get("identity_subject_id") or "") == subj:
            score += 20
        if score <= 0:
            continue
        scored.append((score, frame))
    scored.sort(key=lambda x: (x[0], int(x[1].get("ts") or 0)), reverse=True)
    return [f for _, f in scored[: max(1, int(limit))]]


def memory_prompt_clause(hits: list[dict[str, Any]]) -> str:
    if not hits:
        return ""
    bits = []
    for h in hits[:2]:
        bits.append(f"ep{int(h.get('episode') or 0):02d}/shot{int(h.get('shot') or 0):02d}")
    return "构图记忆参考（站位/景别对齐，脸仍以定妆为准）：" + "、".join(bits)
