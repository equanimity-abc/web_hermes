"""Fixed step I/O contracts for HQ automation.

Layout (project-scoped)::

    dramas/{slug}/
      step1_script/                 # narrative source of truth (immutable after
                                    # first publish; UI script edit only)
      step2_character/{temp,output,state}/
      step3_scene/{temp,output,state}/ep{NN}/
      step4_video/{temp,output,state}/ep{NN}/   # I2V motion (+ lip video)
      step5_audio/{temp,output,state}/ep{NN}/   # VO / TTS
      step6_final/{temp,output,state}/ep{NN}/   # per-shot clip + episode export

Each stage publishes formal artifacts under its ``output/``, scratch under
``temp/``, status under ``state/``. Next stage ``require_*``-checks formal
outputs. Missing/invalid → log + Fail Loud.
"""

from __future__ import annotations

import json
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tools.workspace import resolve_safe

log = logging.getLogger("drama.step")

MIN_IMAGE_BYTES = 100
MIN_AUDIO_BYTES = 100
MIN_VIDEO_BYTES = 500

STEP1 = "step1_script"
STEP2 = "step2_character"
STEP3 = "step3_scene"
STEP4 = "step4_video"
STEP5 = "step5_audio"
STEP6 = "step6_final"


class StepContractError(RuntimeError):
    """Prior step formal output missing or invalid — stop the pipeline."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── path helpers ───────────────────────────────────────────────────────


def step1_root_rel(slug: str) -> str:
    return f"dramas/{slug}/{STEP1}"


def step1_bible_rel(slug: str) -> str:
    return f"{step1_root_rel(slug)}/bible.md"


def step1_outline_rel(slug: str) -> str:
    return f"{step1_root_rel(slug)}/outline.md"


def step1_script_rel(slug: str, episode: int) -> str:
    return f"{step1_root_rel(slug)}/ep{int(episode):02d}.md"


def step1_shots_rel(slug: str, episode: int) -> str:
    return f"{step1_root_rel(slug)}/ep{int(episode):02d}/shots.json"


def step1_ok_rel(slug: str, episode: int) -> str:
    return f"{step1_root_rel(slug)}/ep{int(episode):02d}/_ok.json"


def step2_root_rel(slug: str) -> str:
    return f"dramas/{slug}/{STEP2}"


def step2_temp_rel(slug: str, *parts: str) -> str:
    base = f"{step2_root_rel(slug)}/temp"
    extra = "/".join(str(p).strip("/\\") for p in parts if str(p).strip())
    return f"{base}/{extra}" if extra else base


def step2_output_rel(slug: str, *parts: str) -> str:
    base = f"{step2_root_rel(slug)}/output"
    extra = "/".join(str(p).strip("/\\") for p in parts if str(p).strip())
    return f"{base}/{extra}" if extra else base


def step2_state_rel(slug: str, *parts: str) -> str:
    base = f"{step2_root_rel(slug)}/state"
    extra = "/".join(str(p).strip("/\\") for p in parts if str(p).strip())
    return f"{base}/{extra}" if extra else base


def cast_body_output_rel(slug: str, cid: str) -> str:
    return step2_output_rel(slug, f"{cid}.png")


def cast_face_output_rel(slug: str, cid: str) -> str:
    return step2_output_rel(slug, f"{cid}_face.png")


def cast_manifest_rel(slug: str) -> str:
    return step2_output_rel(slug, "manifest.json")


def step3_root_rel(slug: str) -> str:
    return f"dramas/{slug}/{STEP3}"


def step3_temp_rel(slug: str, episode: int, *parts: str) -> str:
    base = f"{step3_root_rel(slug)}/temp/ep{int(episode):02d}"
    extra = "/".join(str(p).strip("/\\") for p in parts if str(p).strip())
    return f"{base}/{extra}" if extra else base


def step3_output_rel(slug: str, episode: int, *parts: str) -> str:
    base = f"{step3_root_rel(slug)}/output/ep{int(episode):02d}"
    extra = "/".join(str(p).strip("/\\") for p in parts if str(p).strip())
    return f"{base}/{extra}" if extra else base


def step3_state_rel(slug: str, episode: int, *parts: str) -> str:
    base = f"{step3_root_rel(slug)}/state/ep{int(episode):02d}"
    extra = "/".join(str(p).strip("/\\") for p in parts if str(p).strip())
    return f"{base}/{extra}" if extra else base


def scene_temp_rel(slug: str, episode: int, shot_n: int) -> str:
    return step3_temp_rel(slug, episode, f"shot{int(shot_n):02d}_scene.png")


def scene_output_rel(slug: str, episode: int, shot_n: int) -> str:
    return step3_output_rel(slug, episode, f"shot{int(shot_n):02d}_scene.png")


# ── step4 video / step5 audio / step6 final ────────────────────────────


def _step_ep_bucket(step_root: str, slug: str, episode: int, kind: str, *parts: str) -> str:
    """kind is temp|output|state."""
    base = f"dramas/{slug}/{step_root}/{kind}/ep{int(episode):02d}"
    extra = "/".join(str(p).strip("/\\") for p in parts if str(p).strip())
    return f"{base}/{extra}" if extra else base


def step4_root_rel(slug: str) -> str:
    return f"dramas/{slug}/{STEP4}"


def step4_temp_rel(slug: str, episode: int, *parts: str) -> str:
    return _step_ep_bucket(STEP4, slug, episode, "temp", *parts)


def step4_output_rel(slug: str, episode: int, *parts: str) -> str:
    return _step_ep_bucket(STEP4, slug, episode, "output", *parts)


def step4_state_rel(slug: str, episode: int, *parts: str) -> str:
    return _step_ep_bucket(STEP4, slug, episode, "state", *parts)


def step5_root_rel(slug: str) -> str:
    return f"dramas/{slug}/{STEP5}"


def step5_temp_rel(slug: str, episode: int, *parts: str) -> str:
    return _step_ep_bucket(STEP5, slug, episode, "temp", *parts)


def step5_output_rel(slug: str, episode: int, *parts: str) -> str:
    return _step_ep_bucket(STEP5, slug, episode, "output", *parts)


def step5_state_rel(slug: str, episode: int, *parts: str) -> str:
    return _step_ep_bucket(STEP5, slug, episode, "state", *parts)


def step6_root_rel(slug: str) -> str:
    return f"dramas/{slug}/{STEP6}"


def step6_temp_rel(slug: str, episode: int, *parts: str) -> str:
    return _step_ep_bucket(STEP6, slug, episode, "temp", *parts)


def step6_output_rel(slug: str, episode: int, *parts: str) -> str:
    return _step_ep_bucket(STEP6, slug, episode, "output", *parts)


def step6_state_rel(slug: str, episode: int, *parts: str) -> str:
    return _step_ep_bucket(STEP6, slug, episode, "state", *parts)


def motion_temp_rel(slug: str, episode: int, shot_n: int) -> str:
    return step4_temp_rel(slug, episode, f"shot{int(shot_n):02d}_motion.mp4")


def motion_output_rel(slug: str, episode: int, shot_n: int) -> str:
    return step4_output_rel(slug, episode, f"shot{int(shot_n):02d}_motion.mp4")


def lip_temp_rel(slug: str, episode: int, shot_n: int) -> str:
    return step4_temp_rel(slug, episode, f"shot{int(shot_n):02d}_lip.mp4")


def lip_output_rel(slug: str, episode: int, shot_n: int) -> str:
    return step4_output_rel(slug, episode, f"shot{int(shot_n):02d}_lip.mp4")


def voice_temp_rel(slug: str, episode: int, shot_n: int) -> str:
    return step5_temp_rel(slug, episode, f"shot{int(shot_n):02d}.mp3")


def voice_output_rel(slug: str, episode: int, shot_n: int) -> str:
    return step5_output_rel(slug, episode, f"shot{int(shot_n):02d}.mp3")


def clip_temp_rel(slug: str, episode: int, shot_n: int) -> str:
    return step6_temp_rel(slug, episode, f"shot{int(shot_n):02d}.mp4")


def clip_output_rel(slug: str, episode: int, shot_n: int) -> str:
    return step6_output_rel(slug, episode, f"shot{int(shot_n):02d}.mp4")


def export_temp_rel(slug: str, episode: int) -> str:
    return step6_temp_rel(slug, episode, f"ep{int(episode):02d}.mp4")


def export_output_rel(slug: str, episode: int) -> str:
    return step6_output_rel(slug, episode, f"ep{int(episode):02d}.mp4")


# Legacy aliases (prefer step folders above)
def project_output_rel(slug: str) -> str:
    return f"dramas/{slug}/output"


def project_temp_rel(slug: str) -> str:
    return f"dramas/{slug}/temp"


def episode_output_rel(slug: str, episode: int) -> str:
    return step6_output_rel(slug, episode)


def episode_temp_rel(slug: str, episode: int) -> str:
    return step6_temp_rel(slug, episode)


def script_output_rel(slug: str, episode: int) -> str:
    """Alias: formal script lives in step1."""
    return step1_script_rel(slug, episode)


def shots_json_output_rel(slug: str, episode: int) -> str:
    """Alias: formal shots narrative lives in step1."""
    return step1_shots_rel(slug, episode)


def step_manifest_rel(slug: str, episode: int, step_id: str) -> str:
    sid = str(step_id or "").strip()
    if sid in ("script", "step1", STEP1):
        return step1_ok_rel(slug, episode)
    if sid in ("cast", "character", "step2", STEP2):
        return step2_output_rel(slug, "_ok.json")
    if sid in ("scene", "step3", STEP3):
        return step3_output_rel(slug, episode, "_ok.json")
    if sid in ("video", "motion", "step4", STEP4):
        return step4_output_rel(slug, episode, "_ok.json")
    if sid in ("audio", "voice", "step5", STEP5):
        return step5_output_rel(slug, episode, "_ok.json")
    if sid in ("shots_rendered", "clips"):
        return step6_output_rel(slug, episode, "_shots.ok.json")
    if sid in ("final", "export", "clip", "step6", STEP6):
        return step6_output_rel(slug, episode, "_ok.json")
    return step6_output_rel(slug, episode, f"_{sid}.ok.json")


def ensure_dir(rel: str) -> Path:
    path = resolve_safe(rel)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _fail(step_id: str, reason: str) -> None:
    msg = f"[step:{step_id}] {reason}"
    log.error(msg)
    raise StepContractError(msg)


def assert_file(rel: str, *, step_id: str, min_bytes: int = 1, label: str = "") -> Path:
    name = label or rel
    try:
        path = resolve_safe(rel)
    except ValueError as exc:
        _fail(step_id, f"非法路径 {name}：{exc}")
        raise  # pragma: no cover
    if not path.is_file():
        _fail(step_id, f"缺少正式输出：{name}")
    size = path.stat().st_size
    if size < int(min_bytes):
        _fail(step_id, f"正式输出过小（{size}<{min_bytes}）：{name}")
    return path


def publish_file(src_rel: str, dest_rel: str, *, step_id: str, min_bytes: int = 1) -> str:
    """Copy working artifact into formal output tree."""
    src = assert_file(src_rel, step_id=step_id, min_bytes=min_bytes, label=src_rel)
    dest = resolve_safe(dest_rel)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if src.resolve() != dest.resolve():
        shutil.copy2(src, dest)
    assert_file(dest_rel, step_id=step_id, min_bytes=min_bytes, label=dest_rel)
    log.info("[step:%s] published %s → %s", step_id, src_rel, dest_rel)
    return dest_rel


def write_json(rel: str, payload: dict[str, Any]) -> str:
    path = resolve_safe(rel)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return rel


def write_step_ok(
    slug: str,
    episode: int,
    step_id: str,
    *,
    paths: list[str] | None = None,
    extra: dict[str, Any] | None = None,
) -> str:
    payload: dict[str, Any] = {
        "step": step_id,
        "slug": slug,
        "episode": int(episode),
        "ok": True,
        "produced_at": _utc_now(),
        "paths": list(paths or []),
    }
    if extra:
        payload["extra"] = extra
    rel = step_manifest_rel(slug, episode, step_id)
    write_json(rel, payload)
    log.info("[step:%s] ok ep%02d paths=%d", step_id, int(episode), len(payload["paths"]))
    return rel


def write_step_state(
    slug: str,
    step: str,
    name: str,
    payload: dict[str, Any],
    *,
    episode: int = 0,
) -> str:
    """Persist per-step runtime status under that step's state/ folder."""
    fname = name if str(name).endswith(".json") else f"{name}.json"
    ep = int(episode or 0)
    if step in ("cast", "character", "step2", STEP2):
        rel = step2_state_rel(slug, fname)
    elif step in ("scene", "step3", STEP3):
        if ep < 1:
            raise ValueError("step3 state requires episode")
        rel = step3_state_rel(slug, ep, fname)
    elif step in ("video", "motion", "lip", "step4", STEP4):
        if ep < 1:
            raise ValueError("step4 state requires episode")
        rel = step4_state_rel(slug, ep, fname)
    elif step in ("audio", "voice", "step5", STEP5):
        if ep < 1:
            raise ValueError("step5 state requires episode")
        rel = step5_state_rel(slug, ep, fname)
    elif step in ("final", "clip", "export", "step6", STEP6):
        if ep < 1:
            raise ValueError("step6 state requires episode")
        rel = step6_state_rel(slug, ep, fname)
    elif step in ("script", "step1", STEP1):
        if ep < 1:
            raise ValueError("step1 state requires episode")
        rel = f"{step1_root_rel(slug)}/ep{ep:02d}/state/{fname}"
    else:
        rel = f"dramas/{slug}/output/state/{step}/{fname}"
    return write_json(rel, payload)


def require_step_ok(slug: str, episode: int, step_id: str) -> dict[str, Any]:
    rel = step_manifest_rel(slug, episode, step_id)
    try:
        path = resolve_safe(rel)
    except ValueError as exc:
        _fail(step_id, f"步骤清单路径非法：{exc}")
        raise  # pragma: no cover
    if not path.is_file():
        _fail(step_id, f"上一步未完成（缺少 {rel}）")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        _fail(step_id, f"步骤清单损坏 {rel}：{exc}")
        raise  # pragma: no cover
    if not isinstance(data, dict) or not data.get("ok"):
        _fail(step_id, f"步骤清单未通过：{rel}")
    for p in data.get("paths") or []:
        assert_file(str(p), step_id=step_id, min_bytes=1, label=str(p))
    return data


def step1_is_frozen(slug: str, episode: int) -> bool:
    try:
        return resolve_safe(step1_ok_rel(slug, episode)).is_file()
    except ValueError:
        return False


def load_step1_doc(slug: str, episode: int) -> dict[str, Any] | None:
    """Load narrative shots.json from step1 (unique truth)."""
    rel = step1_shots_rel(slug, episode)
    try:
        path = resolve_safe(rel)
    except ValueError:
        return None
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def load_step1_script_text(slug: str, episode: int) -> str:
    rel = step1_script_rel(slug, episode)
    try:
        path = resolve_safe(rel)
    except ValueError:
        return ""
    if not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def require_step1(slug: str, episode: int) -> dict[str, Any]:
    """Downstream steps must read narrative truth only from step1."""
    step = "script"
    assert_file(
        step1_script_rel(slug, episode),
        step_id=step,
        min_bytes=20,
        label=f"{STEP1}/ep{int(episode):02d}.md",
    )
    assert_file(
        step1_shots_rel(slug, episode),
        step_id=step,
        min_bytes=20,
        label=f"{STEP1}/ep{int(episode):02d}/shots.json",
    )
    return require_step_ok(slug, episode, "script")


def _copy_optional(src_rel: str, dest_rel: str, *, step_id: str) -> str | None:
    try:
        src = resolve_safe(src_rel)
    except ValueError:
        return None
    if not src.is_file() or src.stat().st_size < 1:
        return None
    dest = resolve_safe(dest_rel)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if src.resolve() != dest.resolve():
        shutil.copy2(src, dest)
    log.info("[step:%s] published optional %s → %s", step_id, src_rel, dest_rel)
    return dest_rel


def _narrative_shots_snapshot(doc: dict[str, Any] | None) -> dict[str, Any]:
    """Strip runtime assets/qc so step1 stays narrative-only."""
    src = dict(doc or {})
    shots_out: list[dict[str, Any]] = []
    for shot in src.get("shots") or []:
        if not isinstance(shot, dict):
            continue
        keep = {
            k: shot.get(k)
            for k in (
                "n",
                "画面",
                "地点",
                "道具",
                "角色",
                "字幕",
                "旁白",
                "对白",
                "duration",
                "start",
                "end",
                "timing",
                "kind",
                "shot_class",
                "camera",
                "notes",
                "spatial",
                "dialogue",
            )
            if k in shot
        }
        shots_out.append(keep)
    return {
        "slug": src.get("slug"),
        "episode": src.get("episode"),
        "title": src.get("title"),
        "meta": src.get("meta") if isinstance(src.get("meta"), dict) else {},
        "shots": shots_out,
        "source": "step1_script",
        "frozen_at": _utc_now(),
    }


# ── stage publishers / gates ───────────────────────────────────────────


def publish_script_step(
    slug: str,
    episode: int,
    *,
    script_rel: str,
    shots_rel: str,
    bible_rel: str = "",
    outline_rel: str = "",
    from_ui: bool = False,
    doc: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Freeze narrative into step1_script.

    Once ``_ok.json`` exists, automation must not rewrite — only ``from_ui=True``
    (manual workbench script edit) may update step1.
    """
    step = "script"
    n = int(episode)
    if step1_is_frozen(slug, n) and not from_ui:
        log.info("[step:script] step1 already frozen for ep%02d — skip rewrite", n)
        return {
            "step": step,
            "paths": [step1_script_rel(slug, n), step1_shots_rel(slug, n)],
            "frozen": True,
            "skipped_write": True,
        }

    paths: list[str] = [
        publish_file(script_rel, step1_script_rel(slug, n), step_id=step, min_bytes=20),
    ]

    dest_shots = step1_shots_rel(slug, n)
    if doc is not None:
        snap = _narrative_shots_snapshot(doc)
        snap["slug"] = slug
        snap["episode"] = n
        write_json(dest_shots, snap)
        assert_file(dest_shots, step_id=step, min_bytes=20, label=dest_shots)
        paths.append(dest_shots)
    else:
        paths.append(publish_file(shots_rel, dest_shots, step_id=step, min_bytes=20))

    bible_src = bible_rel or f"dramas/{slug}/bible.md"
    outline_src = outline_rel or f"dramas/{slug}/outline.md"
    for src, dest in (
        (bible_src, step1_bible_rel(slug)),
        (outline_src, step1_outline_rel(slug)),
    ):
        copied = _copy_optional(src, dest, step_id=step)
        if copied:
            paths.append(copied)

    write_step_ok(
        slug,
        n,
        step,
        paths=paths,
        extra={"immutable": True, "from_ui": bool(from_ui)},
    )
    write_step_state(
        slug,
        "script",
        "publish",
        {"ok": True, "from_ui": bool(from_ui), "paths": paths, "at": _utc_now()},
        episode=n,
    )
    return {"step": step, "paths": paths, "frozen": True, "from_ui": bool(from_ui)}


def publish_cast_step(slug: str, doc: dict[str, Any] | None = None) -> dict[str, Any]:
    """Publish locked character body+face refs into step2_character/output/.

    Roles are taken from step1 shots when available (unique truth).
    """
    from tools.drama_characters import (
        character_requires_face_identity,
        find_character,
        load_characters,
        normalize_category,
        ref_exists,
        ref_face_exists,
        ref_face_rel,
        ref_rel,
    )
    from tools.drama_shots import normalize_roles

    step = "cast"
    ep = int((doc or {}).get("episode") or 0)
    if ep > 0:
        require_step1(slug, ep)
        truth = load_step1_doc(slug, ep)
        if truth is not None:
            doc = truth

    ensure_dir(step2_temp_rel(slug))
    ensure_dir(step2_output_rel(slug))
    ensure_dir(step2_state_rel(slug))

    cards = load_characters(slug)
    needed: dict[str, dict[str, Any]] = {}
    for shot in (doc or {}).get("shots") or []:
        if not isinstance(shot, dict):
            continue
        for role in normalize_roles(shot.get("角色")):
            char = find_character(cards, role)
            if char is None or normalize_category(char.get("category")) != "character":
                continue
            if not character_requires_face_identity(char):
                continue
            cid = str(char.get("id") or "").strip()
            if cid:
                needed[cid] = char

    published: list[str] = []
    missing: list[str] = []
    for cid, char in needed.items():
        if not ref_exists(slug, char) or not bool(char.get("ref_locked")):
            missing.append(f"{cid}:缺少锁定全身定妆")
            continue
        if not ref_face_exists(slug, char):
            missing.append(f"{cid}:缺少正脸定妆")
            continue
        body_src = str(char.get("ref") or ref_rel(slug, cid))
        face_src = str(char.get("ref_face") or ref_face_rel(slug, cid))
        temp_body = step2_temp_rel(slug, f"{cid}.png")
        temp_face = step2_temp_rel(slug, f"{cid}_face.png")
        try:
            if resolve_safe(temp_body).is_file():
                body_src = temp_body
            if resolve_safe(temp_face).is_file():
                face_src = temp_face
        except ValueError:
            pass
        published.append(
            publish_file(body_src, cast_body_output_rel(slug, cid), step_id=step, min_bytes=MIN_IMAGE_BYTES)
        )
        published.append(
            publish_file(face_src, cast_face_output_rel(slug, cid), step_id=step, min_bytes=MIN_IMAGE_BYTES)
        )

    if missing:
        write_step_state(
            slug,
            "cast",
            "error",
            {"ok": False, "missing": missing, "at": _utc_now()},
        )
        _fail(step, "定妆正式输出不满足：" + "；".join(missing[:8]))
    if needed and not published:
        _fail(step, f"分镜需要角色定妆，但 {STEP2}/output 为空")

    manifest = {
        "step": step,
        "ok": True,
        "produced_at": _utc_now(),
        "paths": published,
        "count": len(published) // 2,
        "source_step": STEP1,
    }
    write_json(cast_manifest_rel(slug), manifest)
    write_step_ok(slug, ep if ep > 0 else 1, step, paths=published, extra={"count": manifest["count"]})
    write_step_state(
        slug,
        "cast",
        "publish",
        {"ok": True, "count": manifest["count"], "paths": published, "at": _utc_now()},
    )
    log.info("[step:cast] published %d files → %s/output", len(published), STEP2)
    return manifest


def require_cast_for_shot(slug: str, shot: dict[str, Any]) -> None:
    """Before scene gen: every face-need role must have formal cast in step2 output."""
    from tools.drama_characters import (
        character_requires_face_identity,
        find_character,
        load_characters,
        normalize_category,
    )
    from tools.drama_shots import normalize_roles

    step = "cast"
    cards = load_characters(slug)
    roles = normalize_roles(shot.get("角色"))
    if not roles:
        return
    missing: list[str] = []
    for role in roles:
        char = find_character(cards, role)
        if char is None or normalize_category(char.get("category")) != "character":
            continue
        if not character_requires_face_identity(char):
            continue
        cid = str(char.get("id") or "").strip()
        try:
            assert_file(
                cast_body_output_rel(slug, cid),
                step_id=step,
                min_bytes=MIN_IMAGE_BYTES,
                label=f"{STEP2}/output/{cid}.png",
            )
            assert_file(
                cast_face_output_rel(slug, cid),
                step_id=step,
                min_bytes=MIN_IMAGE_BYTES,
                label=f"{STEP2}/output/{cid}_face.png",
            )
        except StepContractError as exc:
            missing.append(str(exc))
    if missing:
        sn = int(shot.get("n") or 0)
        _fail(step, f"Shot {sn} 定妆门禁失败：" + "；".join(missing[:6]))


def publish_scene_step(slug: str, episode: int, shot_n: int, scene_work_rel: str) -> str:
    ensure_dir(step3_temp_rel(slug, episode))
    ensure_dir(step3_output_rel(slug, episode))
    ensure_dir(step3_state_rel(slug, episode))
    try:
        work = resolve_safe(scene_work_rel)
        temp_dest = scene_temp_rel(slug, episode, shot_n)
        if work.is_file() and work.resolve() != resolve_safe(temp_dest).resolve():
            resolve_safe(temp_dest).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(work, resolve_safe(temp_dest))
    except Exception:
        pass
    out = publish_file(
        scene_work_rel,
        scene_output_rel(slug, episode, shot_n),
        step_id="scene",
        min_bytes=MIN_IMAGE_BYTES,
    )
    write_step_state(
        slug,
        "scene",
        f"shot{int(shot_n):02d}",
        {"ok": True, "shot": int(shot_n), "path": out, "at": _utc_now()},
        episode=int(episode),
    )
    return out


def require_scene_step(slug: str, episode: int, shot_n: int) -> None:
    assert_file(
        scene_output_rel(slug, episode, shot_n),
        step_id="scene",
        min_bytes=MIN_IMAGE_BYTES,
        label=f"{STEP3}/output/ep{int(episode):02d}/shot{int(shot_n):02d}_scene.png",
    )


def mark_scenes_ok(slug: str, episode: int, shot_ns: list[int]) -> str:
    paths = [scene_output_rel(slug, episode, sn) for sn in shot_ns]
    for rel in paths:
        assert_file(rel, step_id="scene", min_bytes=MIN_IMAGE_BYTES, label=rel)
    return write_step_ok(slug, episode, "scene", paths=paths, extra={"shots": list(shot_ns)})


def _mirror_work_to_temp(work_rel: str, temp_rel: str) -> None:
    try:
        work = resolve_safe(work_rel)
        dest = resolve_safe(temp_rel)
        if work.is_file() and work.resolve() != dest.resolve():
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(work, dest)
    except Exception:
        pass


def publish_motion_step(slug: str, episode: int, shot_n: int, motion_work_rel: str) -> str:
    ensure_dir(step4_temp_rel(slug, episode))
    ensure_dir(step4_output_rel(slug, episode))
    ensure_dir(step4_state_rel(slug, episode))
    _mirror_work_to_temp(motion_work_rel, motion_temp_rel(slug, episode, shot_n))
    out = publish_file(
        motion_work_rel,
        motion_output_rel(slug, episode, shot_n),
        step_id="motion",
        min_bytes=MIN_VIDEO_BYTES,
    )
    write_step_state(
        slug,
        "video",
        f"shot{int(shot_n):02d}_motion",
        {"ok": True, "shot": int(shot_n), "path": out, "at": _utc_now()},
        episode=int(episode),
    )
    return out


def require_motion_step(slug: str, episode: int, shot_n: int) -> None:
    assert_file(
        motion_output_rel(slug, episode, shot_n),
        step_id="motion",
        min_bytes=MIN_VIDEO_BYTES,
        label=f"{STEP4}/output/ep{int(episode):02d}/shot{int(shot_n):02d}_motion.mp4",
    )


def publish_lip_step(slug: str, episode: int, shot_n: int, lip_work_rel: str) -> str:
    ensure_dir(step4_temp_rel(slug, episode))
    ensure_dir(step4_output_rel(slug, episode))
    _mirror_work_to_temp(lip_work_rel, lip_temp_rel(slug, episode, shot_n))
    out = publish_file(
        lip_work_rel,
        lip_output_rel(slug, episode, shot_n),
        step_id="motion",
        min_bytes=MIN_VIDEO_BYTES,
    )
    write_step_state(
        slug,
        "video",
        f"shot{int(shot_n):02d}_lip",
        {"ok": True, "shot": int(shot_n), "path": out, "at": _utc_now()},
        episode=int(episode),
    )
    return out


def publish_voice_step(slug: str, episode: int, shot_n: int, voice_work_rel: str) -> str:
    ensure_dir(step5_temp_rel(slug, episode))
    ensure_dir(step5_output_rel(slug, episode))
    ensure_dir(step5_state_rel(slug, episode))
    _mirror_work_to_temp(voice_work_rel, voice_temp_rel(slug, episode, shot_n))
    out = publish_file(
        voice_work_rel,
        voice_output_rel(slug, episode, shot_n),
        step_id="voice",
        min_bytes=MIN_AUDIO_BYTES,
    )
    write_step_state(
        slug,
        "audio",
        f"shot{int(shot_n):02d}",
        {"ok": True, "shot": int(shot_n), "path": out, "at": _utc_now()},
        episode=int(episode),
    )
    return out


def require_voice_step(slug: str, episode: int, shot_n: int) -> None:
    assert_file(
        voice_output_rel(slug, episode, shot_n),
        step_id="voice",
        min_bytes=MIN_AUDIO_BYTES,
        label=f"{STEP5}/output/ep{int(episode):02d}/shot{int(shot_n):02d}.mp3",
    )


def publish_clip_step(slug: str, episode: int, shot_n: int, clip_work_rel: str) -> str:
    ensure_dir(step6_temp_rel(slug, episode))
    ensure_dir(step6_output_rel(slug, episode))
    ensure_dir(step6_state_rel(slug, episode))
    _mirror_work_to_temp(clip_work_rel, clip_temp_rel(slug, episode, shot_n))
    out = publish_file(
        clip_work_rel,
        clip_output_rel(slug, episode, shot_n),
        step_id="clip",
        min_bytes=MIN_VIDEO_BYTES,
    )
    write_step_state(
        slug,
        "final",
        f"shot{int(shot_n):02d}",
        {"ok": True, "shot": int(shot_n), "path": out, "at": _utc_now()},
        episode=int(episode),
    )
    return out


def require_clip_step(slug: str, episode: int, shot_n: int) -> None:
    assert_file(
        clip_output_rel(slug, episode, shot_n),
        step_id="clip",
        min_bytes=MIN_VIDEO_BYTES,
        label=f"{STEP6}/output/ep{int(episode):02d}/shot{int(shot_n):02d}.mp4",
    )


def publish_shots_rendered_step(slug: str, episode: int, shot_ns: list[int]) -> dict[str, Any]:
    step = "shots_rendered"
    paths: list[str] = []
    for sn in shot_ns:
        rel = clip_output_rel(slug, episode, sn)
        assert_file(
            rel,
            step_id=step,
            min_bytes=MIN_VIDEO_BYTES,
            label=f"{STEP6}/output/ep{int(episode):02d}/shot{int(sn):02d}.mp4",
        )
        paths.append(rel)
    write_step_ok(slug, episode, step, paths=paths, extra={"shots": list(shot_ns)})
    return {"step": step, "paths": paths}


def publish_export_step(slug: str, episode: int, export_work_rel: str) -> str:
    step = "export"
    ensure_dir(step6_temp_rel(slug, episode))
    ensure_dir(step6_output_rel(slug, episode))
    _mirror_work_to_temp(export_work_rel, export_temp_rel(slug, episode))
    out = publish_file(
        export_work_rel,
        export_output_rel(slug, episode),
        step_id=step,
        min_bytes=MIN_VIDEO_BYTES,
    )
    write_step_ok(slug, episode, step, paths=[out])
    write_step_state(
        slug,
        "final",
        "export",
        {"ok": True, "path": out, "at": _utc_now()},
        episode=int(episode),
    )
    return out


def temp_path(slug: str, episode: int, *parts: str) -> Path:
    """Absolute path under step6 temp (creates parents)."""
    rel = step6_temp_rel(slug, episode, *parts)
    path = resolve_safe(rel)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def step2_temp_path(slug: str, *parts: str) -> Path:
    rel = step2_temp_rel(slug, *parts)
    path = resolve_safe(rel)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def step3_temp_path(slug: str, episode: int, *parts: str) -> Path:
    rel = step3_temp_rel(slug, episode, *parts)
    path = resolve_safe(rel)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def step4_temp_path(slug: str, episode: int, *parts: str) -> Path:
    rel = step4_temp_rel(slug, episode, *parts)
    path = resolve_safe(rel)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def step5_temp_path(slug: str, episode: int, *parts: str) -> Path:
    rel = step5_temp_rel(slug, episode, *parts)
    path = resolve_safe(rel)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def step6_temp_path(slug: str, episode: int, *parts: str) -> Path:
    rel = step6_temp_rel(slug, episode, *parts)
    path = resolve_safe(rel)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path
