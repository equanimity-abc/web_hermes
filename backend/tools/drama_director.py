"""Director coverage suggestions (Q5).

Suggest hook-in-3s, size rhythm, and at most two reaction cuts.
Never apply patches or locks — the workbench / human does that.
"""

from __future__ import annotations

from typing import Any

from tools.drama_characters import normalize_roles
from tools.drama_models import infer_kind, infer_size, infer_speaker, KIND_DEFAULT_SIZE
from tools.drama_shots import (
    apply_patch,
    find_shot,
    ordered_shots_from_doc,
    set_shot_locks,
    utc_now,
)

MAX_REACTION_SUGGESTIONS = 2
HOOK_SECONDS = 3.0
RHYTHM_RUN = 3
KEPT_STATUSES = frozenset({"dismissed", "applied"})
SIZE_STEP = {
    "ECU": "CU",
    "CU": "MCU",
    "MCU": "MS",
    "MS": "MCU",
    "WS": "MS",
}
HOOK_MARKERS = ("钩子", "悬念", "反转", "冲突", "反差", "秘密", "竟然")


def coverage_locked(shot: dict[str, Any] | None) -> bool:
    if not shot:
        return True
    locked = set(shot.get("locked") or [])
    return "shot" in locked or "kind" in locked


def normalize_coverage(raw: Any) -> dict[str, Any]:
    data = raw if isinstance(raw, dict) else {}
    items: list[dict[str, Any]] = []
    for item in data.get("suggestions") or []:
        if not isinstance(item, dict) or not str(item.get("id") or "").strip():
            continue
        items.append(_public_item(item))
    return {
        "updated_at": str(data.get("updated_at") or ""),
        "suggestions": items,
    }


def public_coverage(doc: dict[str, Any] | None) -> dict[str, Any]:
    cov = normalize_coverage((doc or {}).get("coverage"))
    suggestions = cov["suggestions"]
    open_items = [s for s in suggestions if s.get("status") == "open"]
    return {
        **cov,
        "open": len(open_items),
        "reaction_open": sum(1 for s in open_items if s.get("type") == "reaction"),
    }


def _public_item(item: dict[str, Any]) -> dict[str, Any]:
    status = str(item.get("status") or "open")
    if status not in ("open", "dismissed", "applied"):
        status = "open"
    patch = item.get("patch") if isinstance(item.get("patch"), dict) else {}
    return {
        "id": str(item.get("id") or "").strip(),
        "type": str(item.get("type") or ""),
        "status": status,
        "shot": int(item.get("shot") or 0) or None,
        "after_shot": int(item.get("after_shot") or 0) or None,
        "title": str(item.get("title") or ""),
        "reason": str(item.get("reason") or ""),
        "patch": patch,
    }


def _start(shot: dict[str, Any]) -> float:
    try:
        return float(shot.get("start") or 0)
    except (TypeError, ValueError):
        return 0.0


def _hook_meta(doc: dict[str, Any]) -> str:
    raw = str((doc.get("meta") or {}).get("钩子") or "").strip()
    cleaned = raw.strip("（）() ").replace(" ", "")
    if cleaned in ("", "前3秒"):
        return ""
    return raw


def _has_hook(doc: dict[str, Any], shots: list[dict[str, Any]]) -> bool:
    if _hook_meta(doc):
        return True
    covering = [s for s in shots if _start(s) < HOOK_SECONDS]
    if not covering and shots:
        covering = shots[:1]
    blob = " ".join(f"{s.get('画面') or ''} {s.get('字幕') or s.get('对白') or ''}" for s in covering)
    return any(mark in blob for mark in HOOK_MARKERS)


def _reaction_speaker(shot: dict[str, Any]) -> str:
    speaker = infer_speaker(shot)
    for rid in normalize_roles(shot.get("角色")):
        if rid and rid != speaker:
            return rid
    return speaker


def _prev_status(coverage: dict[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    for item in coverage.get("suggestions") or []:
        sid = str(item.get("id") or "")
        if sid:
            out[sid] = str(item.get("status") or "open")
    return out


def _build_hook(doc: dict[str, Any], shots: list[dict[str, Any]], kept: dict[str, str]) -> dict[str, Any] | None:
    if _has_hook(doc, shots) or not shots:
        return None
    target = next((s for s in shots if _start(s) < HOOK_SECONDS), shots[0])
    n = int(target.get("n") or 0)
    sid = f"hook-{n}"
    if kept.get(sid) in KEPT_STATUSES:
        return None
    scene = str(target.get("画面") or "").strip()
    patch: dict[str, Any] = {}
    if scene and "开场钩子" not in scene and not coverage_locked(target):
        patch = {"画面": f"开场钩子，冲突入画。{scene}"}
    return {
        "id": sid,
        "type": "hook_3s",
        "status": "open",
        "shot": n,
        "title": "前 3 秒缺钩子",
        "reason": "开场偏慢热，建议在首镜画面写冲突/悬念/反差（不自动改台词）",
        "patch": patch,
    }


def _build_rhythm(shots: list[dict[str, Any]], kept: dict[str, str]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    i = 0
    while i < len(shots):
        size = infer_size(shots[i])
        j = i + 1
        while j < len(shots) and size and infer_size(shots[j]) == size:
            j += 1
        run = shots[i:j]
        if size and len(run) >= RHYTHM_RUN:
            target = next((s for s in run[1:] if not coverage_locked(s)), None)
            if target:
                n = int(target.get("n") or 0)
                sid = f"rhythm-{n}"
                alt = SIZE_STEP.get(size, "MCU")
                if alt != size and kept.get(sid) not in KEPT_STATUSES:
                    out.append(
                        {
                            "id": sid,
                            "type": "size_rhythm",
                            "status": "open",
                            "shot": n,
                            "title": f"景别连 {len(run)} 镜 {size}",
                            "reason": f"连续 {size} 缺少节奏，建议 Shot {n} 改为 {alt}",
                            "patch": {"size": alt},
                        }
                    )
        i = max(j, i + 1)
    return out


def _build_reactions(shots: list[dict[str, Any]], kept: dict[str, str]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for idx, shot in enumerate(shots[:-1]):
        if len(out) >= MAX_REACTION_SUGGESTIONS:
            break
        if infer_kind(shot) != "dialogue" or not str(shot.get("字幕") or shot.get("对白") or "").strip():
            continue
        nxt = shots[idx + 1]
        if infer_kind(nxt) == "reaction":
            continue
        if infer_kind(nxt) != "dialogue":
            continue
        if coverage_locked(nxt):
            continue
        n = int(nxt.get("n") or 0)
        sid = f"reaction-{n}"
        if kept.get(sid) in KEPT_STATUSES:
            continue
        speaker = _reaction_speaker(nxt) or _reaction_speaker(shot)
        out.append(
            {
                "id": sid,
                "type": "reaction",
                "status": "open",
                "shot": n,
                "after_shot": int(shot.get("n") or 0),
                "title": f"Shot {shot.get('n')} 台词后切反应镜",
                "reason": f"连续台词缺少反应镜，建议 Shot {n} 改为 reaction CU（一集最多 {MAX_REACTION_SUGGESTIONS} 条）",
                "patch": {
                    "kind": "reaction",
                    "size": KIND_DEFAULT_SIZE["reaction"],
                    "speaker": speaker,
                },
            }
        )
    return out


def _merge(previous: list[dict[str, Any]], generated: list[dict[str, Any]]) -> list[dict[str, Any]]:
    prev_by = {str(s.get("id") or ""): s for s in previous if s.get("id")}
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for item in generated:
        sid = str(item.get("id") or "")
        seen.add(sid)
        old = prev_by.get(sid)
        if old and str(old.get("status") or "") in KEPT_STATUSES:
            out.append(_public_item(old))
        else:
            out.append(_public_item(item))
    for old in previous:
        sid = str(old.get("id") or "")
        if sid and sid not in seen and str(old.get("status") or "") in KEPT_STATUSES:
            out.append(_public_item(old))
    return out


def refresh_coverage(doc: dict[str, Any]) -> dict[str, Any]:
    """Write open suggestions onto the episode doc. Does not patch shots or locks."""
    previous = normalize_coverage(doc.get("coverage"))
    kept = _prev_status(previous)
    shots = ordered_shots_from_doc(doc)
    generated: list[dict[str, Any]] = []
    hook = _build_hook(doc, shots, kept)
    if hook:
        generated.append(hook)
    generated.extend(_build_rhythm(shots, kept))
    generated.extend(_build_reactions(shots, kept))
    coverage = {
        "updated_at": utc_now(),
        "suggestions": _merge(previous.get("suggestions") or [], generated),
    }
    doc["coverage"] = coverage
    return public_coverage(doc)


def _require_item(doc: dict[str, Any], sid: str) -> dict[str, Any]:
    cov = normalize_coverage(doc.get("coverage"))
    hit = next((s for s in cov["suggestions"] if s.get("id") == sid), None)
    if hit is None:
        raise ValueError(f"找不到建议：{sid}")
    return hit


def apply_suggestion(doc: dict[str, Any], sid: str) -> dict[str, Any]:
    item = _require_item(doc, sid)
    if item.get("status") != "open":
        raise ValueError("只能采纳未处理的建议")
    shot_n = int(item.get("shot") or 0)
    shot = find_shot(doc, shot_n) if shot_n else None
    if shot is None:
        raise ValueError(f"找不到 Shot {shot_n}")
    if "shot" in (shot.get("locked") or []):
        raise ValueError("该镜已锁整镜，无法采纳建议")
    patch = dict(item.get("patch") or {})
    dirtied: list[str] = []
    if patch:
        dirtied = apply_patch(shot, patch)
    for other in (doc.get("coverage") or {}).get("suggestions") or []:
        if str(other.get("id") or "") == sid:
            other["status"] = "applied"
            break
    doc["coverage"] = normalize_coverage(doc.get("coverage"))
    doc["coverage"]["updated_at"] = utc_now()
    return {"id": sid, "dirtied": dirtied, "locked": list(shot.get("locked") or [])}


def dismiss_suggestion(doc: dict[str, Any], sid: str) -> dict[str, Any]:
    item = _require_item(doc, sid)
    if item.get("status") == "applied":
        raise ValueError("已采纳的建议不能改成忽略")
    for other in (doc.get("coverage") or {}).get("suggestions") or []:
        if str(other.get("id") or "") == sid:
            other["status"] = "dismissed"
            break
    doc["coverage"] = normalize_coverage(doc.get("coverage"))
    doc["coverage"]["updated_at"] = utc_now()
    return {"id": sid, "status": "dismissed"}


def lock_suggestion(doc: dict[str, Any], sid: str) -> dict[str, Any]:
    """Lock kind on the target shot and dismiss. Does not apply the patch."""
    item = _require_item(doc, sid)
    shot_n = int(item.get("shot") or 0)
    shot = find_shot(doc, shot_n) if shot_n else None
    if shot is None:
        raise ValueError(f"找不到 Shot {shot_n}")
    set_shot_locks(shot, lock=["kind"])
    if item.get("status") == "open":
        for other in (doc.get("coverage") or {}).get("suggestions") or []:
            if str(other.get("id") or "") == sid:
                other["status"] = "dismissed"
                break
    doc["coverage"] = normalize_coverage(doc.get("coverage"))
    doc["coverage"]["updated_at"] = utc_now()
    return {"id": sid, "status": "dismissed", "locked": list(shot.get("locked") or [])}
