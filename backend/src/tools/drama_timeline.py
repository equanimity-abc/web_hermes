"""Episode timeline (D6): shot order, trim, volume, transitions — assemble-only edits."""

from __future__ import annotations

from typing import Any

from tools.drama_shots import (
    DEFAULT_FADE_SEC,
    MIN_PLAY_SEC,
    TRANSITIONS,
    find_shot,
    normalize_shot_timeline,
    normalize_timeline,
    ordered_shots_from_doc,
)
from tools.workspace import resolve_safe


def ordered_shots(doc: dict[str, Any]) -> list[dict[str, Any]]:
    return ordered_shots_from_doc(doc)


def play_duration(shot: dict[str, Any], source_duration: float) -> float:
    tl = normalize_shot_timeline(shot)
    start = tl["trim_in"]
    end = max(start + MIN_PLAY_SEC, float(source_duration) - tl["trim_out"])
    return max(MIN_PLAY_SEC, end - start)


def resolve_transition_name(shot: dict[str, Any], index: int, *, auto_fn) -> str:
    transition = normalize_shot_timeline(shot)["transition"]
    if transition == "auto":
        return auto_fn(str(shot.get("camera") or "punch_in"), index)
    if transition == "cut":
        return "fade"
    return str(transition)


def junction_fade_sec(shot: dict[str, Any], default: float) -> float:
    transition = normalize_shot_timeline(shot)["transition"]
    if transition in ("cut",):
        return 0.05
    return default


def build_assemble_specs(
    doc: dict[str, Any],
    *,
    probe_duration,
) -> tuple[list[dict[str, Any]], float]:
    timeline = normalize_timeline(doc.get("timeline"), doc.get("shots") or [])
    fade_sec = float(timeline["fade_sec"])
    specs: list[dict[str, Any]] = []
    for shot in ordered_shots(doc):
        rel = (shot.get("assets") or {}).get("clip") or ""
        if not rel:
            continue
        path = resolve_safe(rel)
        try:
            authored = float(shot.get("duration") or 0)
        except (TypeError, ValueError):
            authored = 0.0
        if authored <= 0:
            authored = 5.0
        tl = normalize_shot_timeline(shot)
        if not path.is_file():
            play = play_duration(shot, authored)
            specs.append(
                {
                    "n": int(shot.get("n") or 0),
                    "path": path,
                    "source_duration": round(authored, 3),
                    "file_duration": 0.0,
                    "trim_in": tl["trim_in"],
                    "trim_out": tl["trim_out"],
                    "volume": tl["volume"],
                    "transition": tl["transition"],
                    "camera": str(shot.get("camera") or "punch_in"),
                    "play_duration": round(play, 3),
                    "missing": True,
                }
            )
            continue
        probe = float(probe_duration(path) or 0.0)
        # 成片目标时长以剧本分镜为准；磁盘 clip 偏短时在拼接阶段补齐，偏长则取较大值以免裁切配音
        source = max(authored, probe) if probe > 0.05 else authored
        play = play_duration(shot, source)
        specs.append(
            {
                "n": int(shot.get("n") or 0),
                "path": path,
                "source_duration": round(source, 3),
                "file_duration": round(probe, 3),
                "trim_in": tl["trim_in"],
                "trim_out": tl["trim_out"],
                "volume": tl["volume"],
                "transition": tl["transition"],
                "camera": str(shot.get("camera") or "punch_in"),
                "play_duration": round(play, 3),
            }
        )
    return specs, fade_sec


def apply_timeline_patch(shot: dict[str, Any], patch: dict[str, Any]) -> None:
    if "trim_in" in patch and patch["trim_in"] is not None:
        shot["trim_in"] = max(0.0, float(patch["trim_in"]))
    if "trim_out" in patch and patch["trim_out"] is not None:
        shot["trim_out"] = max(0.0, float(patch["trim_out"]))
    if "volume" in patch and patch["volume"] is not None:
        vol = float(patch["volume"])
        shot["volume"] = max(0.0, min(vol, 2.0))
    if "transition" in patch and patch["transition"] is not None:
        t = str(patch["transition"]).strip() or "auto"
        shot["transition"] = t if t in TRANSITIONS else "auto"


def patch_timeline_doc(doc: dict[str, Any], body: dict[str, Any]) -> dict[str, Any]:
    timeline = normalize_timeline(doc.get("timeline"), doc.get("shots") or [])
    if "order" in body and body["order"] is not None:
        nums = set(_shot_numbers(doc.get("shots") or []))
        order: list[int] = []
        seen: set[int] = set()
        for item in body["order"]:
            try:
                n = int(item)
            except (TypeError, ValueError):
                continue
            if n in nums and n not in seen:
                order.append(n)
                seen.add(n)
        for n in sorted(nums):
            if n not in seen:
                order.append(n)
        timeline["order"] = order
    if "fade_sec" in body and body["fade_sec"] is not None:
        fade = float(body["fade_sec"])
        timeline["fade_sec"] = round(max(0.05, min(fade, 1.5)), 3)
    shots_patch = body.get("shots")
    if isinstance(shots_patch, dict):
        for key, fields in shots_patch.items():
            try:
                n = int(key)
            except (TypeError, ValueError):
                continue
            shot = find_shot(doc, n)
            if shot is None or not isinstance(fields, dict):
                continue
            apply_timeline_patch(shot, fields)
    doc["timeline"] = timeline
    return timeline


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


def public_timeline(doc: dict[str, Any] | None, *, probe_duration) -> dict[str, Any]:
    if not doc:
        return {"order": [], "fade_sec": DEFAULT_FADE_SEC, "items": [], "total_duration": 0, "transitions": list(TRANSITIONS)}
    timeline = normalize_timeline(doc.get("timeline"), doc.get("shots") or [])
    items: list[dict[str, Any]] = []
    total = 0.0
    specs, _ = build_assemble_specs(doc, probe_duration=probe_duration)
    for i, spec in enumerate(specs):
        play = float(spec["play_duration"])
        total += play
        shot = find_shot(doc, spec["n"]) or {}
        items.append(
            {
                "n": spec["n"],
                "画面": shot.get("画面") or "",
                "duration": float(shot.get("duration") or play),
                "source_duration": spec["source_duration"],
                "play_duration": play,
                "trim_in": spec["trim_in"],
                "trim_out": spec["trim_out"],
                "volume": spec["volume"],
                "transition": spec["transition"],
                "clip": (shot.get("assets") or {}).get("clip"),
            }
        )
    return {
        "order": timeline["order"],
        "fade_sec": timeline["fade_sec"],
        "items": items,
        "total_duration": round(max(total, 0), 2),
        "transitions": list(TRANSITIONS),
    }
