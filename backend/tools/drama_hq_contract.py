"""HQ / studio fail-loud contracts (no silent degrade).

Knife 1: image refs must feed generation; no free-provider cascade; no still fallback.
Knife 2/3 extend I2V / TTS+lip via the same ``is_hq_no_fallback`` gate.
"""

from __future__ import annotations

from typing import Any

# Studio image must never land on these (even if "usable" without keys).
HQ_FORBIDDEN_IMAGE = frozenset(
    {
        "pollinations",
        "flux",
        "mock",
        "mock_ai",
        "none",
        "off",
        "",
    }
)


def is_hq_no_fallback(slug: str = "", *, models: dict[str, Any] | None = None) -> bool:
    """True when quality_profile is studio (the only active hard profile)."""
    from tools.drama_profiles import resolve_quality_profile

    return resolve_quality_profile(slug, models=models) == "studio"


def hq_image_provider_chain(primary: str, shot: dict[str, Any] | None = None) -> list[str]:
    """Single commercial image provider — no cascade / free fallback."""
    from tools.providers import registry

    pid = str(primary or "").strip().lower()
    if not pid or pid in HQ_FORBIDDEN_IMAGE:
        # Prefer Seedream alias when route is empty/forbidden
        for alt in ("seedream", "ark", "doubao-image"):
            if registry.has("image", alt):
                return [alt]
        return []
    if not registry.has("image", pid):
        return []
    return [pid]


def assert_hq_image_ready(slug: str, shot: dict[str, Any]) -> dict[str, Any]:
    """Fail loud before scene gen when studio needs locked face refs."""
    from tools.drama_characters import (
        character_requires_face_identity,
        load_characters,
        ref_exists,
        resolve_shot_characters,
    )
    from tools.drama_models import load_models, provider_usable
    from tools.drama_qc import _arcface_ready, locked_face_refs_for_shot
    from tools.drama_styles import image_route

    kind = str(shot.get("kind") or "").strip().lower()
    # 定妆生成本身不要求已有 refs
    if kind == "character_ref":
        return {"ok": True, "skipped": "character_ref"}

    models = load_models(slug)
    route = image_route(slug, shot or {})
    pid = str(route.get("provider") or "").strip().lower()
    if pid in HQ_FORBIDDEN_IMAGE or not pid:
        raise ValueError(
            "专业档出图路由无效或为免费后端"
            f"（provider={pid or '空'}），请配置 Seedream/ARK 等商用出图"
        )
    if not provider_usable(models, pid):
        raise ValueError(
            f"专业档出图 provider 未就绪：{pid}（缺少 Key 或适配器不可用），禁止降级免费出图"
        )

    cards = load_characters(slug)
    cast = resolve_shot_characters(shot, cards)
    need_face = [c for c in cast if character_requires_face_identity(c)]
    if not need_face:
        return {"ok": True, "faces_required": 0, "provider": pid}

    missing: list[str] = []
    for char in need_face:
        name = str(char.get("name") or char.get("id") or "?").strip()
        if not char.get("ref_locked") or not ref_exists(slug, char):
            missing.append(name)
    if missing:
        raise ValueError(
            "专业档出图前须锁定定妆："
            + "、".join(missing[:8])
            + "。请到「角色」页生成并锁定参考图。"
        )

    faces = locked_face_refs_for_shot(slug, shot)
    if not faces:
        raise ValueError(
            "专业档出图需要至少 1 张锁定定妆参考图传入模型，当前 refs 为空"
        )

    if not _arcface_ready():
        raise ValueError(
            "专业档身份依赖未就绪（insightface/buffalo_l）。"
            "请先运行 backend/scripts/fetch_arcface_model.py。"
        )

    return {
        "ok": True,
        "faces_required": len(need_face),
        "face_refs": len(faces),
        "provider": pid,
    }
