"""Phase A quality gates: Fail Loud studio profile (no silent mock success).

Phase C motion floors are enforced in HQ produce via
``tools.drama_motion_floors.assert_motion_floor`` (see ``_hq_process_one_shot``).
Export-time callers may optionally import the same helper if needed.
"""

from __future__ import annotations

from typing import Any

# Providers that are allowed without commercial keys even in studio mode.
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
        if pid and pid not in ("l0", "none", "off"):
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
        if pid in _FREE_OK or pid in checked:
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
