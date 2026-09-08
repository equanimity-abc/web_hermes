"""Phase A quality gates: Fail Loud studio profile (no silent mock success).

Phase C motion floors are enforced in HQ produce via
``tools.drama_motion_floors.assert_motion_floor`` (see ``_hq_process_one_shot``).
Export-time callers may optionally import the same helper if needed.
"""

from __future__ import annotations

from typing import Any

# Motion placeholders that do not need commercial keys (still gated elsewhere).
_MOTION_NO_KEY = frozenset({"l0", "none", "off"})

# Studio must never treat these as acceptable image backends.
_STUDIO_FORBIDDEN_IMAGE = frozenset(
    {
        "flux",
        "pollinations",
        "mock",
        "mock_ai",
        "none",
        "off",
        "",
    }
)

# Legacy: providers that may run without keys outside studio image routes.
_FREE_OK = frozenset(
    {
        "l0",
        "none",
        "off",
        "flux",
        "pollinations",
        "mock",
        "mock_ai",
        "edge-tts",
    }
)


def assert_studio_providers(slug: str) -> dict[str, Any]:
    """Fail loud if project models require keys that are missing/unusable."""
    from tools.drama_hq_contract import HQ_FORBIDDEN_IMAGE
    from tools.drama_models import load_models, provider_usable

    models = load_models(slug)
    needed: list[tuple[str, str]] = []

    for kind, route in (models.get("image") or {}).items():
        if not isinstance(route, dict):
            continue
        pid = str(route.get("provider") or "").strip().lower()
        if pid:
            needed.append((f"image.{kind}", pid))

    for kind, route in (models.get("motion") or {}).items():
        if not isinstance(route, dict):
            continue
        pid = str(route.get("provider") or "").strip().lower()
        if pid and pid not in _MOTION_NO_KEY:
            needed.append((f"motion.{kind}", pid))

    tts = models.get("tts") if isinstance(models.get("tts"), dict) else {}
    tts_pid = str(tts.get("provider") or "").strip().lower()
    if tts_pid:
        needed.append(("tts", tts_pid))

    lip = models.get("lip") if isinstance(models.get("lip"), dict) else {}
    lip_pid = str(lip.get("provider") or "").strip().lower()
    if lip_pid and lip_pid != "mock":
        needed.append(("lip", lip_pid))

    missing: list[str] = []
    checked: set[str] = set()
    for where, pid in needed:
        if where.startswith("image.") and (
            pid in _STUDIO_FORBIDDEN_IMAGE or pid in HQ_FORBIDDEN_IMAGE
        ):
            missing.append(f"{pid}（{where}：专业档禁止免费/空出图）")
            continue
        if pid in _MOTION_NO_KEY or pid in checked:
            continue
        # Image/TTS/lip: never skip via _FREE_OK under studio assert
        if where.startswith("image."):
            checked.add(pid)
            if not provider_usable(models, pid):
                missing.append(f"{pid}（用于 {where}）")
            continue
        if pid in _FREE_OK:
            continue
        checked.add(pid)
        if not provider_usable(models, pid):
            missing.append(f"{pid}（用于 {where}）")

    if missing:
        raise ValueError(
            "专业档缺少可用模型 Key 或 provider 未就绪："
            + "、".join(missing)
            + "。请在 API 设置中配置 ARK_API_KEY / DASHSCOPE_* 等后重试（禁止静默降级）。"
        )
    return {"ok": True, "checked": sorted(checked)}


def assert_shots_qc_for_export(slug: str, episode: int, doc: dict[str, Any], *, force: bool = False) -> dict[str, Any]:
    """Block export unless every shot passes identity/lip/flicker (unless force)."""
    from tools.drama_qc import qc_shot_bundle, shot_can_pass
    from tools.drama_shots import ordered_shots_from_doc

    if force:
        return {"ok": True, "forced": True, "block_reason": ""}

    blockers: list[str] = []
    for shot in ordered_shots_from_doc(doc):
        sn = int(shot.get("n") or 0)
        if sn < 1:
            continue
        if "shot" in (shot.get("locked") or []):
            continue
        # Studio: lip-eligible shots must use a real lip provider (not fallback/mock).
        try:
            assert_studio_lip_shot(slug, shot)
        except ValueError as e:
            blockers.append(f"Shot {sn}: {e}")
            continue
        bundle = qc_shot_bundle(slug, episode, shot, apply=True)
        if shot_can_pass(bundle):
            continue
        reason = str(bundle.get("block_reason") or "QC 未通过")
        blockers.append(f"Shot {sn}: {reason}")

    if blockers:
        raise ValueError(
            "导出被 QC 硬闸拦截（工作台可强制导出，Agent 不可）："
            + "；".join(blockers[:8])
            + ("…" if len(blockers) > 8 else "")
        )
    return {"ok": True, "forced": False, "block_reason": ""}


def assert_studio_lip_shot(slug: str, shot: dict[str, Any]) -> None:
    """Fail loud when eligible lip shots still use fallback/mock under studio profile."""
    import os

    from tools.drama_lip import lip_eligible
    from tools.drama_profiles import resolve_quality_profile
    from tools.providers.lip_providers import lip_source_is_real

    if resolve_quality_profile(slug) != "studio":
        return
    if os.getenv("DRAMA_ALLOW_FALLBACK_LIP", "").strip().lower() in ("1", "true", "yes"):
        return
    gate = lip_eligible(shot)
    if not gate.get("ok"):
        return
    source = str(shot.get("lip_source") or "")
    if not lip_source_is_real(source):
        raise ValueError(f"专业档口型源无效（lip_source={source or '空'}），禁止 fallback/mock 当通过")


def assert_loudness_after_export(slug: str, episode: int, *, force: bool = False) -> dict[str, Any]:
    """After assemble, loudness must pass unless force."""
    from tools.drama_qc import check_allows_pass, qc_episode_loudness

    loudness = qc_episode_loudness(slug, episode, apply=True)
    if force or check_allows_pass(loudness):
        return {"ok": True, "forced": force, "loudness": loudness}
    status = str(loudness.get("status") or "")
    if status == "n/a" or loudness.get("required") is False:
        return {"ok": True, "forced": False, "loudness": loudness}
    raise ValueError(
        "导出后响度验收未通过："
        + str(loudness.get("hint") or loudness.get("reason") or status or "loudness fail")
        + "。可 remix 后重试，或在工作台强制导出。"
    )


def assert_studio_bgm(slug: str, episode: int, *, force: bool = False) -> dict[str, Any]:
    """Studio export must not ship lavfi procedural tones as real BGM."""
    import os

    from tools.drama_audio import has_bgm, load_catalog, load_mix
    from tools.drama_profiles import resolve_quality_profile

    if force:
        return {"ok": True, "forced": True}
    if resolve_quality_profile(slug) == "draft":
        return {"ok": True, "draft": True}
    if os.getenv("DRAMA_ALLOW_PROCEDURAL_BGM", "").strip().lower() in ("1", "true", "yes"):
        return {"ok": True, "allowed_env": True}

    mix = load_mix(slug, episode)
    if not has_bgm(mix):
        intent = str(mix.get("bgm_intent") or "").strip()
        raise ValueError(
            "专业档导出需要真实配乐：请在成片页上传免版税/已授权 BGM"
            + (f"（剧本配乐意图：{intent}）" if intent else "")
            + "。当前曲库占位音为 lavfi 合成，不可作为上架成片。"
        )
    bgm = mix.get("bgm") if isinstance(mix.get("bgm"), dict) else {}
    procedural = bool(bgm.get("procedural"))
    if not procedural:
        # Cross-check catalog row / marker
        tid = str(bgm.get("id") or "").strip()
        tracks = load_catalog(slug).get("tracks") or []
        hit = next((t for t in tracks if t.get("id") == tid), None)
        if hit and hit.get("procedural"):
            procedural = True
        else:
            path = str(bgm.get("path") or "")
            if path:
                try:
                    from tools.workspace import resolve_safe

                    p = resolve_safe(path)
                    if p.with_suffix(p.suffix + ".procedural").is_file():
                        procedural = True
                except ValueError:
                    pass
    if procedural:
        raise ValueError(
            "专业档禁止使用 lavfi 程序化占位 BGM 导出。"
            "请上传真实免版税音频，或设置 DRAMA_ALLOW_PROCEDURAL_BGM=1（仅调试）。"
        )
    return {"ok": True, "procedural": False}
