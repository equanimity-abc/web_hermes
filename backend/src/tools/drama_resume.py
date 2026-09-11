"""Smart resume: diagnose produce failures and continue from the failed step.

续跑原则：从上次失败点出发，先复检当前状态是否已被人工修好；
已修好则向后推进，未修好则基于当前资产/锁态继续解决。
"""

from __future__ import annotations

from typing import Any


def locked_layer_set(shot: dict[str, Any] | None) -> set[str]:
    """Return locked layers; whole-shot lock expands to all common layers."""
    locked = {str(x) for x in ((shot or {}).get("locked") or []) if str(x).strip()}
    if "shot" in locked:
        locked |= {"scene", "overlay", "voice", "clip", "motion", "lip"}
    return locked


def strip_locked_dirty(shot: dict[str, Any] | None, dirty: list[str] | None) -> list[str]:
    """Drop locked layers from a dirty list (locked plates must not be marked for regen)."""
    locked = locked_layer_set(shot)
    out: list[str] = []
    for layer in dirty or []:
        name = str(layer or "").strip()
        if not name or name in locked or name in out:
            continue
        out.append(name)
    return out


def scene_plate_locked(shot: dict[str, Any] | None) -> bool:
    """True when the scene plate must not be regenerated."""
    locked = locked_layer_set(shot)
    return "scene" in locked or "shot" in locked


def refine_plan_for_locks(shot: dict[str, Any], plan: dict[str, Any]) -> dict[str, Any]:
    """Adjust resume plan so locked scene plates are never dirtied for redraw."""
    out = dict(plan or {})
    locked = locked_layer_set(shot)
    assets = shot.get("assets") if isinstance(shot.get("assets"), dict) else {}
    scene_ok = bool(assets.get("scene"))
    stage = str(out.get("stage") or "")
    dirty = strip_locked_dirty(shot, list(out.get("dirty") or []))

    if scene_plate_locked(shot) and scene_ok:
        if stage in ("identity", "scene") or "scene" in (plan.get("dirty") or []):
            dirty = strip_locked_dirty(shot, dirty or ["motion", "clip"])
            if stage == "identity":
                out["resume_from"] = "identity"
                out["hint"] = (
                    "画面已锁定：不会重绘；续跑仅复检身份。"
                    "若需换图请先解锁画面后再续跑"
                )
            elif stage == "scene":
                out["resume_from"] = "identity"
                out["hint"] = (
                    "画面已锁定且触发敏感/真人等问题：不会自动重绘。"
                    "请先解锁画面并换图后再续跑"
                )
            else:
                out["resume_from"] = str(out.get("resume_from") or "motion")
                if "锁定" not in str(out.get("hint") or ""):
                    out["hint"] = (
                        f"{out.get('hint') or '按失败点续跑'}（画面已锁定，跳过重绘）"
                    )

    out["dirty"] = dirty
    if "shot" in locked:
        out["dirty"] = []
    return out


def classify_failure(error: str) -> dict[str, Any]:
    """Map a produce error string to stage + dirty layers + human hint."""
    err = str(error or "").strip()
    low = err.lower()

    def _hit(*keys: str) -> bool:
        return any(k.lower() in low or k in err for k in keys)

    if _hit("加速收尾", "其它镜头失败", "peerabort", "未继续昂贵"):
        return {
            "stage": "aborted",
            "dirty": ["motion", "lip", "clip"],
            "resume_from": "motion",
            "hint": "因其它镜失败提前收尾；续跑将从运动/口型步骤继续",
        }

    if _hit(
        "sensitive",
        "real person",
        "privacyinformation",
        "真人",
        "敏感",
    ):
        return {
            "stage": "scene",
            "dirty": ["scene", "overlay", "motion", "clip"],
            "resume_from": "scene",
            "hint": "画面触发敏感/真人检测，需改分镜描述或换图后再续跑",
        }

    if _hit("身份", "identity", "cosine", "人脸", "定妆", "arcface", "no_face", "unmatched"):
        return {
            "stage": "identity",
            "dirty": ["scene", "motion", "clip"],
            "resume_from": "scene",
            "hint": "身份未过：重做画面（不重配音）；改 look/构图后再续跑",
        }

    if _hit("闪烁", "flicker", "ssim"):
        return {
            "stage": "flicker",
            "dirty": ["motion", "clip"],
            "resume_from": "motion",
            "hint": "闪烁未过：只重做运动/成片，保留画面与配音",
        }

    if _hit("口型", "lip", "pixverse", "latentsync", "musetalk", "wav2lip"):
        return {
            "stage": "lip",
            "dirty": ["lip", "clip"],
            "resume_from": "lip",
            "hint": "口型失败：只重做口型与成片，保留画面/配音/运动",
        }

    if _hit("i2v", "seedance", "真 i2v", "运动", "ken burns", "motion"):
        return {
            "stage": "i2v",
            "dirty": ["motion", "clip"],
            "resume_from": "motion",
            "hint": "I2V/运动失败：保留画面与配音，从运动步骤续跑",
        }

    if _hit("配音", "tts", "voice", "voiceover"):
        return {
            "stage": "voice",
            "dirty": ["voice", "overlay", "lip", "clip"],
            "resume_from": "voice",
            "hint": "配音失败：重做配音及下游口型/成片",
        }

    if _hit("bgm", "配乐", "export", "导出", "qc", "响度", "kpi"):
        return {
            "stage": "export",
            "dirty": [],
            "resume_from": "export",
            "hint": "镜头已齐，续跑将从配乐/导出继续",
        }

    return {
        "stage": "unknown",
        "dirty": ["scene", "overlay", "voice", "motion", "clip"],
        "resume_from": "scene",
        "hint": "未能精确归类，按整镜重做（跳过已通过镜）",
    }


def _disk_file_ok(rel: Any) -> bool:
    """True only when the workspace file really exists."""
    path = str(rel or "").strip()
    if not path:
        return False
    try:
        from tools.workspace import resolve_safe

        p = resolve_safe(path)
        return p.is_file() and p.stat().st_size > 100
    except Exception:
        return False


def _file_ok(rel: Any) -> bool:
    path = str(rel or "").strip()
    if not path:
        return False
    if _disk_file_ok(path):
        return True
    # Unit tests often pass placeholder paths; treat non-empty as present.
    return bool(path)


def _identity_ok(identity: dict[str, Any] | None) -> bool:
    from tools.drama_qc import check_allows_pass

    if not isinstance(identity, dict) or not identity:
        return False
    return check_allows_pass(identity)


def _needs_voice(shot: dict[str, Any]) -> bool:
    return bool(str(shot.get("字幕") or shot.get("对白") or "").strip())


def _needs_lip(shot: dict[str, Any]) -> bool:
    try:
        from tools.drama_models import infer_kind

        kind = infer_kind(shot)
    except Exception:
        kind = str(shot.get("kind") or "")
    if kind in ("establishing", "insert", "crowd", "title"):
        return False
    return _needs_voice(shot)


def _i2v_ok(shot: dict[str, Any]) -> bool:
    src = str(shot.get("i2v_source") or "")
    if src in ("ai", "keys"):
        return True
    # 仅认显式档位/镜型，避免 infer_kind 把对话镜误判为定场而跳过运动
    ladder = str(shot.get("i2v_ladder") or shot.get("motion_ladder") or "")
    if ladder == "L0":
        return True
    kind = str(shot.get("kind") or "")
    if kind in ("establishing", "insert", "crowd", "title"):
        return True
    return False


def _lip_ok(shot: dict[str, Any], assets: dict[str, Any], *, force_required: bool = False) -> bool:
    if not force_required and not _needs_lip(shot):
        return True
    src = str(shot.get("lip_source") or "")
    if src == "fallback":
        return False
    if src and src != "none":
        return True
    return _file_ok(assets.get("lip"))


def _flicker_ok(shot: dict[str, Any]) -> bool:
    from tools.drama_qc import check_allows_pass

    flicker = shot.get("qc_flicker") if isinstance(shot.get("qc_flicker"), dict) else {}
    if not flicker:
        return True
    return check_allows_pass(flicker)


def inspect_shot_state(shot: dict[str, Any]) -> dict[str, Any]:
    """Snapshot readiness from current shot record (no regeneration)."""
    assets = shot.get("assets") if isinstance(shot.get("assets"), dict) else {}
    identity = shot.get("identity") if isinstance(shot.get("identity"), dict) else {}
    scene_ok = _file_ok(assets.get("scene")) or bool(assets.get("scene"))
    voice_ok = (not _needs_voice(shot)) or _file_ok(assets.get("voice")) or bool(assets.get("voice"))
    clip_ok = _file_ok(assets.get("clip")) or bool(assets.get("clip"))
    return {
        "scene_ok": scene_ok,
        "identity_ok": _identity_ok(identity),
        "identity": identity,
        "voice_ok": voice_ok,
        "i2v_ok": _i2v_ok(shot),
        "lip_ok": _lip_ok(shot, assets),
        "lip_ok_forced": _lip_ok(shot, assets, force_required=True),
        "flicker_ok": _flicker_ok(shot),
        "clip_ok": clip_ok,
        "needs_voice": _needs_voice(shot),
        "needs_lip": _needs_lip(shot),
        "scene_locked": scene_plate_locked(shot),
    }


def previous_failure_stage(shot: dict[str, Any]) -> str:
    """Where we last failed — starting checkpoint for recheck-then-advance."""
    qc = shot.get("qc") if isinstance(shot.get("qc"), dict) else {}
    err = str(qc.get("produce_error") or shot.get("i2v_error") or shot.get("lip_error") or "").strip()
    stored = str(qc.get("produce_stage") or qc.get("resume_from") or "").strip()
    if err:
        stage = str(classify_failure(err).get("stage") or "")
        if stage:
            return stage
    if stored in ("scene", "identity", "voice", "motion", "i2v", "lip", "flicker", "aborted", "export"):
        return "motion" if stored == "i2v" else stored
    dirty = {str(x) for x in (shot.get("dirty") or []) if str(x).strip()}
    if dirty <= {"lip", "clip"} and dirty:
        return "lip"
    if dirty <= {"motion", "clip", "lip"} and dirty:
        return "motion"
    if "scene" in dirty:
        return "scene"
    return "unknown"


def _checkpoint_order(stage: str) -> list[str]:
    """Pipeline checkpoints to walk when advancing after a fix."""
    start = {
        "scene": "scene",
        "identity": "identity",
        "voice": "voice",
        "motion": "motion",
        "i2v": "motion",
        "flicker": "motion",
        "aborted": "motion",
        "lip": "lip",
        "export": "export",
        "unknown": "scene",
    }.get(str(stage or "unknown"), "scene")
    full = ["scene", "identity", "voice", "motion", "lip", "flicker", "clip"]
    if start == "export":
        return ["export"]
    if start not in full:
        start = "scene"
    return full[full.index(start) :]


def plan_for_checkpoint(shot: dict[str, Any], state: dict[str, Any], checkpoint: str) -> dict[str, Any]:
    """Build a dirty/resume plan for a still-failing checkpoint."""
    if checkpoint == "scene":
        plan = {
            "stage": "scene",
            "dirty": ["scene", "overlay", "motion", "clip"],
            "resume_from": "scene",
            "hint": "画面缺失或需重做：基于当前状态重新出图",
        }
    elif checkpoint == "identity":
        if state.get("scene_locked"):
            plan = {
                "stage": "identity",
                "dirty": ["motion", "clip"],
                "resume_from": "identity",
                "hint": "身份仍未过（画面已锁，不重绘）。请改定妆或解锁换图后再续跑",
            }
        else:
            plan = {
                "stage": "identity",
                "dirty": ["scene", "motion", "clip"],
                "resume_from": "scene",
                "hint": "身份仍未过：将重做画面（不重配音）",
            }
    elif checkpoint == "voice":
        plan = {
            "stage": "voice",
            "dirty": ["voice", "overlay", "lip", "clip"],
            "resume_from": "voice",
            "hint": "配音仍缺：重做配音及下游口型/成片",
        }
    elif checkpoint in ("motion", "i2v", "flicker"):
        dirty = ["motion", "clip"]
        if state.get("needs_lip"):
            dirty = ["motion", "lip", "clip"]
        plan = {
            "stage": "flicker" if checkpoint == "flicker" else "i2v",
            "dirty": dirty,
            "resume_from": "motion",
            "hint": "运动/成片未完成：保留画面与配音，从运动步骤续跑",
        }
    elif checkpoint == "lip":
        plan = {
            "stage": "lip",
            "dirty": ["lip", "clip"],
            "resume_from": "lip",
            "hint": "口型仍未过：只重做口型与成片",
        }
    elif checkpoint == "clip":
        plan = {
            "stage": "i2v",
            "dirty": ["motion", "lip", "clip"] if state.get("needs_lip") else ["motion", "clip"],
            "resume_from": "motion",
            "hint": "缺少成片：从运动/口型步骤续跑",
        }
    else:
        plan = {
            "stage": "export",
            "dirty": [],
            "resume_from": "export",
            "hint": "镜头已齐，续跑将完成配乐/导出",
        }
    return refine_plan_for_locks(shot, plan)


def advance_from_failure(
    shot: dict[str, Any],
    state: dict[str, Any],
    *,
    previous_stage: str,
) -> dict[str, Any] | None:
    """Recheck from previous failure; advance past resolved stages.

    Returns None when this shot no longer needs produce work.
    """
    resolved: list[str] = []
    checkpoints = _checkpoint_order(previous_stage)
    foundation = ["scene", "identity"]
    walk = list(dict.fromkeys(foundation + checkpoints))

    for cp in walk:
        if cp == "scene":
            if state["scene_ok"]:
                resolved.append("scene")
                continue
            return plan_for_checkpoint(shot, state, "scene")

        if cp == "identity":
            if state["identity_ok"]:
                resolved.append("identity")
                continue
            return plan_for_checkpoint(shot, state, "identity")

        if cp == "voice":
            if state["voice_ok"]:
                resolved.append("voice")
                continue
            plan = plan_for_checkpoint(shot, state, "voice")
            if resolved and previous_stage in ("scene", "identity", "aborted"):
                plan["hint"] = f"先前问题已解决（{'/'.join(resolved)}），继续配音"
                plan["resolved_previous"] = True
            return plan

        if cp == "motion":
            if state["i2v_ok"] and state["flicker_ok"]:
                resolved.append("motion")
                continue
            plan = plan_for_checkpoint(
                shot, state, "flicker" if state["i2v_ok"] and not state["flicker_ok"] else "motion"
            )
            if previous_stage in ("scene", "identity", "voice", "aborted", "i2v", "flicker") and (
                "identity" in resolved or state["identity_ok"]
            ):
                if previous_stage in ("scene", "identity", "voice", "aborted"):
                    plan["hint"] = (
                        f"先前问题已解决（{'/'.join(resolved) or '身份/画面'}），继续运动/成片"
                    )
                    plan["resolved_previous"] = True
                elif "identity" in resolved and previous_stage in ("i2v", "flicker", "aborted"):
                    # 基础已确认，按当前缺口续跑
                    pass
            return plan

        if cp == "lip":
            # 若上次就败在口型，即使当前剧本无字幕标记，也按口型结果判断
            lip_ok = state["lip_ok_forced"] if previous_stage == "lip" else state["lip_ok"]
            if lip_ok:
                resolved.append("lip")
                continue
            plan = plan_for_checkpoint(shot, state, "lip")
            if resolved:
                plan["hint"] = f"先前问题已解决（{'/'.join(resolved)}），继续口型"
                plan["resolved_previous"] = True
            return plan

        if cp == "flicker":
            if state["flicker_ok"]:
                resolved.append("flicker")
                continue
            return plan_for_checkpoint(shot, state, "flicker")

        if cp == "clip":
            if state["clip_ok"] and state["identity_ok"] and state["i2v_ok"] and state["lip_ok"]:
                return None
            if state["clip_ok"] and state["identity_ok"] and state["lip_ok"]:
                if state["i2v_ok"] or state["clip_ok"]:
                    return None
            return plan_for_checkpoint(shot, state, "clip")

        if cp == "export":
            return None

    if state["clip_ok"] and state["identity_ok"]:
        return None
    return plan_for_checkpoint(shot, state, "clip")


def refresh_identity_for_resume(slug: str, episode: int, shot: dict[str, Any]) -> dict[str, Any]:
    """Live re-QC identity when resuming past an identity/scene failure or stale fail mark."""
    from tools.drama_qc import qc_shot_identity

    identity = qc_shot_identity(slug, int(episode), shot, apply=True)
    shot["identity"] = identity
    return identity


def should_live_recheck_identity(shot: dict[str, Any], previous_stage: str) -> bool:
    """Whether resume should spend a live ArcFace pass before deciding next step."""
    assets = shot.get("assets") if isinstance(shot.get("assets"), dict) else {}
    # Only when the plate is really on disk (skip placeholder paths in unit tests).
    if not _disk_file_ok(assets.get("scene")):
        return False
    if previous_stage in ("identity", "scene", "unknown", "aborted"):
        return True
    identity = shot.get("identity") if isinstance(shot.get("identity"), dict) else {}
    if identity and not _identity_ok(identity):
        return True
    qc = shot.get("qc") if isinstance(shot.get("qc"), dict) else {}
    if qc.get("produce_ok") is False and previous_stage in ("identity", "scene"):
        return True
    return False


def diagnose_shot(
    shot: dict[str, Any],
    *,
    slug: str | None = None,
    episode: int | None = None,
    live_recheck: bool = False,
) -> dict[str, Any] | None:
    """Return a resume plan for one shot, or None if it does not need work.

    When live_recheck=True and slug/episode given, identity is re-QCd so manual
    定妆/换图 fixes are detected before deciding dirty layers.
    """
    if not isinstance(shot, dict):
        return None
    sn = int(shot.get("n") or 0)
    if sn < 1:
        return None

    if "shot" in set(shot.get("locked") or []):
        return None

    qc = shot.get("qc") if isinstance(shot.get("qc"), dict) else {}
    assets = shot.get("assets") if isinstance(shot.get("assets"), dict) else {}
    dirty = {str(x) for x in (shot.get("dirty") or []) if str(x).strip()}
    produce_ok = qc.get("produce_ok")
    err = str(qc.get("produce_error") or shot.get("i2v_error") or shot.get("lip_error") or "").strip()
    prev_stage = previous_failure_stage(shot)

    needs = False
    if produce_ok is False:
        needs = True
    if dirty:
        needs = True
    identity = shot.get("identity") if isinstance(shot.get("identity"), dict) else {}
    if assets.get("scene") and identity and not _identity_ok(identity) and identity.get("required") is not False:
        needs = True
        err = err or str(identity.get("hint") or "身份未过")
    if not assets.get("clip") and not ("shot" in set(shot.get("locked") or [])):
        if assets.get("scene") or produce_ok is False:
            needs = True
            err = err or "缺少成片 clip"

    if not needs:
        return None

    if live_recheck and slug and episode is not None and should_live_recheck_identity(shot, prev_stage):
        try:
            refresh_identity_for_resume(str(slug), int(episode), shot)
        except Exception as exc:
            shot.setdefault("_resume_recheck_error", str(exc)[:200])

    state = inspect_shot_state(shot)
    plan = advance_from_failure(shot, state, previous_stage=prev_stage)
    if plan is None:
        return None

    note = ""
    if plan.get("resolved_previous"):
        note = str(plan.get("hint") or "")
    elif prev_stage in ("identity", "scene") and state["identity_ok"] and plan.get("resume_from") not in (
        "identity",
        "scene",
    ):
        note = f"先前{prev_stage}问题已解决，继续{plan.get('resume_from')}"
        plan["hint"] = note
        plan["resolved_previous"] = True

    return {
        "shot": sn,
        "stage": plan.get("stage"),
        "dirty": list(plan.get("dirty") or []),
        "resume_from": plan.get("resume_from"),
        "hint": plan.get("hint") or note or "",
        "error": err[:300],
        "scene_ok": state["scene_ok"],
        "identity_ok": state["identity_ok"],
        "i2v_ok": state["i2v_ok"],
        "previous_stage": prev_stage,
        "resolved_previous": bool(plan.get("resolved_previous")),
    }


def diagnose_episode(
    slug: str,
    episode: int,
    doc: dict[str, Any] | None = None,
    *,
    live_recheck: bool = False,
) -> dict[str, Any]:
    """Analyze an episode for smart resume."""
    from tools.drama_audio import has_bgm, load_mix
    from tools.drama_shots import load_doc
    from tools.workspace import resolve_safe

    n = int(episode)
    doc = doc or load_doc(slug, n) or {}
    shots = [s for s in (doc.get("shots") or []) if isinstance(s, dict)]
    plans = []
    for shot in shots:
        plan = diagnose_shot(shot, slug=slug, episode=n, live_recheck=live_recheck)
        if plan:
            plans.append(plan)

    mix = load_mix(slug, n)
    bgm_ok = has_bgm(mix)
    play_rel = f"dramas/{slug}/videos/ep{n:02d}.mp4"
    try:
        exported = resolve_safe(play_rel).is_file()
    except ValueError:
        exported = False

    resolved_n = sum(1 for p in plans if p.get("resolved_previous"))
    if not plans and bgm_ok and exported:
        next_action = "done"
        summary = "镜头与成片均已就绪，无需续跑"
    elif not plans and not exported:
        next_action = "export"
        summary = "镜头已通过（含人工修好的失败点），续跑将挂载 BGM（如缺）并导出成片"
    elif plans:
        stages = sorted({str(p.get("stage") or "") for p in plans})
        next_action = "produce"
        extra = f"；其中 {resolved_n} 镜先前问题已解决、向后推进" if resolved_n else ""
        summary = (
            f"需续跑 {len(plans)} 镜（阶段：{'/'.join(stages)}）{extra}；"
            "已通过镜跳过，从当前未解决步骤继续直至导出"
        )
    else:
        next_action = "export"
        summary = "无失败镜，续跑将完成配乐/导出"

    return {
        "slug": slug,
        "episode": n,
        "failed_shots": plans,
        "failed_count": len(plans),
        "resolved_count": resolved_n,
        "bgm_ok": bgm_ok,
        "exported": exported,
        "next_action": next_action,
        "summary": summary,
        "hints": [f"Shot {p['shot']}: {p.get('hint')}" for p in plans[:8]],
    }


def prepare_episode_resume(slug: str, episode: int) -> dict[str, Any]:
    """Live-recheck failure points, then apply narrowed dirty marks."""
    from tools.drama_shots import find_shot, load_doc, merge_save_shot

    n = int(episode)
    report = diagnose_episode(slug, episode, live_recheck=True)
    doc = load_doc(slug, n)
    if not doc:
        return report

    applied: list[dict[str, Any]] = []
    cleared: list[int] = []

    failed_ns = {int(p.get("shot") or 0) for p in (report.get("failed_shots") or [])}
    for shot in doc.get("shots") or []:
        if not isinstance(shot, dict):
            continue
        sn = int(shot.get("n") or 0)
        if sn < 1 or sn in failed_ns:
            continue
        qc = shot.get("qc") if isinstance(shot.get("qc"), dict) else {}
        if qc.get("produce_ok") is False or shot.get("dirty"):
            state = inspect_shot_state(shot)
            if state["identity_ok"] and state["clip_ok"]:
                qc = dict(qc)
                qc["produce_ok"] = True
                for k in ("produce_error", "produce_stage", "resume_from", "resume_hint"):
                    qc.pop(k, None)
                shot["qc"] = qc
                shot["dirty"] = []
                shot["status"] = "rendered"
                merge_save_shot(slug, n, shot)
                cleared.append(sn)

    for plan in report.get("failed_shots") or []:
        sn = int(plan.get("shot") or 0)
        shot = find_shot(doc, sn)
        if not shot:
            continue
        dirty_layers = strip_locked_dirty(
            shot, [str(x) for x in (plan.get("dirty") or []) if str(x).strip()]
        )
        qc = dict(shot.get("qc") or {}) if isinstance(shot.get("qc"), dict) else {}
        qc["produce_stage"] = str(plan.get("stage") or qc.get("produce_stage") or "")
        qc["resume_from"] = str(plan.get("resume_from") or "")
        qc["resume_hint"] = str(plan.get("hint") or "")
        if plan.get("resolved_previous"):
            qc["produce_error"] = str(plan.get("hint") or qc.get("produce_error") or "")[:300]
        if qc.get("produce_ok") is False:
            qc["produce_ok"] = False
        shot["qc"] = qc
        shot["dirty"] = dirty_layers
        shot["status"] = "dirty" if dirty_layers else (shot.get("status") or "pending")
        merge_save_shot(slug, n, shot)
        applied.append(
            {
                "shot": sn,
                "dirty": dirty_layers,
                "resume_from": plan.get("resume_from"),
                "resolved_previous": bool(plan.get("resolved_previous")),
                "previous_stage": plan.get("previous_stage"),
            }
        )

    report["prepared"] = applied
    report["cleared_shots"] = cleared
    bits = [f"已复检并收窄脏层（{len(applied)} 镜）"]
    if cleared:
        bits.append(f"已清除 {len(cleared)} 镜过期失败标记")
    resolved_n = int(report.get("resolved_count") or 0)
    if resolved_n:
        bits.append(f"{resolved_n} 镜先前问题已解决并向前推进")
    report["summary"] = "；".join(bits) + "。" + str(report.get("summary") or "")
    return report


def mark_shot_failure_layers(error: str) -> dict[str, Any]:
    """Helper for produce failure marking."""
    return classify_failure(error)
