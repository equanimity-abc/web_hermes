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


# Narrative kinds that must never use Ken Burns under studio.
HQ_I2V_REQUIRED_KINDS = frozenset(
    {
        "dialogue",
        "reaction",
        "action",
        "cu",
        "ms",
        "ws",
    }
)

# Still-image kinds allowed without I2V in HQ v1 (title cards etc.).
HQ_I2V_OPTIONAL_KINDS = frozenset(
    {
        "establishing",
        "insert",
        "crowd",
        "title",
    }
)


def assert_hq_i2v_ready(slug: str, shot: dict[str, Any]) -> dict[str, Any]:
    """Fail loud when studio narrative motion has no usable real I2V provider."""
    from tools.drama_models import infer_kind, load_models, provider_usable

    kind = infer_kind(shot)
    if kind in HQ_I2V_OPTIONAL_KINDS:
        return {"ok": True, "skipped": kind, "optional": True}

    models = load_models(slug)
    candidates = (
        "seedance",
        "ark",
        "doubao-video",
        "kling",
        "kling-video",
        "kling-maas",
        "hailuo",
    )
    usable = [p for p in candidates if provider_usable(models, p)]
    if not usable:
        raise ValueError(
            "专业档运动需要可用的真 I2V（Seedance/Kling/Hailuo 等），"
            "当前无可用 Key；禁止 Ken Burns/mock 顶替。"
        )
    return {"ok": True, "kind": kind, "providers": usable}


# Commercial TTS only — edge-tts is never HQ.
HQ_TTS_OK = frozenset(
    {
        "seed-audio",
        "ark",
        "doubao-audio",
        "cosyvoice",
        "dashscope-tts",
        "http",
        "api",
        "volcano",
        "azure",
        "ms",
    }
)

HQ_TTS_FORBIDDEN = frozenset({"edge-tts", "edge", "mock", "none", "off", ""})

HQ_LIP_OK = frozenset(
    {
        "pixverse",
        "pixverse-lipsync",
        "latentsync",
        "latent-sync",
        "replicate-lip",
        "musetalk",
        "wav2lip",
        "http",
        "api",
    }
)


def assert_hq_tts_ready(slug: str, shot: dict[str, Any] | None = None) -> dict[str, Any]:
    """Fail loud when studio TTS is missing or routed to edge-tts."""
    from tools.drama_models import load_models, models_with_overrides, provider_usable

    models = models_with_overrides(slug, shot=shot) if shot else load_models(slug)
    tts = models.get("tts") if isinstance(models.get("tts"), dict) else {}
    pid = str(tts.get("provider") or "").strip().lower()
    if pid in HQ_TTS_FORBIDDEN or pid not in HQ_TTS_OK:
        raise ValueError(
            f"专业档 TTS 必须为商用引擎（当前 provider={pid or '空'}），禁止 edge-tts"
        )
    if not provider_usable(models, pid):
        raise ValueError(
            f"专业档 TTS provider 未就绪：{pid}（缺少 ARK/DASHSCOPE/TTS_API_*），禁止降级 edge-tts"
        )
    return {"ok": True, "provider": pid}


def assert_hq_lip_ready(slug: str, shot: dict[str, Any]) -> dict[str, Any]:
    """Fail loud before lip: real provider + real motion base; multi-speaker → split shots."""
    from tools.drama_lip import lip_eligible, lip_provider_cascade
    from tools.drama_models import models_with_overrides
    from tools.workspace import resolve_safe

    models = models_with_overrides(slug, shot=shot)
    gate = lip_eligible(shot, models=models)
    if not gate.get("ok"):
        return {"ok": True, "skipped": gate.get("reason") or "not_eligible"}

    # Multi-speaker: HQ default is auto_split before produce. Same-frame multi lip is forbidden.
    track = shot.get("dialogue_track") if isinstance(shot.get("dialogue_track"), dict) else {}
    turns = list(track.get("turns") or [])
    speakers = {
        str(t.get("speaker") or t.get("character_id") or t.get("name") or "").strip()
        for t in turns
        if isinstance(t, dict)
    }
    speakers.discard("")
    # Also count character_id diversity
    from tools.drama_dialogue import track_distinct_speakers

    if len(track_distinct_speakers(track)) >= 2 or len(speakers) >= 2:
        raise ValueError(
            "专业档多说话人同镜须先 auto_split 为单人段（产片会自动拆镜）。"
            "请重新产片，或手动拆成单说话人镜后再口型。"
        )

    lip_cfg = models.get("lip") if isinstance(models.get("lip"), dict) else {}
    wanted = str(lip_cfg.get("provider") or "").strip().lower()
    if wanted in ("mock", "none", "off", "l0", "fail"):
        raise ValueError("专业档口型禁止 mock/关闭路由，请配置 PixVerse/LatentSync/LIP_API_URL")
    cascade = lip_provider_cascade(wanted or None, slug=slug)
    if not cascade:
        raise ValueError(
            "专业档无可用口型模型：请配置 DASHSCOPE_MAAS_BASE_URL+DASHSCOPE_API_KEY（PixVerse）"
            " 或 REPLICATE_API_TOKEN（LatentSync）或 LIP_API_URL"
        )
    head = cascade[0]
    if head not in HQ_LIP_OK:
        raise ValueError(f"专业档口型 provider 无效：{head}")

    assets = shot.get("assets") if isinstance(shot.get("assets"), dict) else {}
    motion_ok = False
    for key in ("motion", "i2v"):
        rel = str(assets.get(key) or "").strip()
        if not rel:
            continue
        try:
            path = resolve_safe(rel)
        except ValueError:
            continue
        if path.is_file() and path.suffix.lower() in (".mp4", ".mov", ".webm") and path.stat().st_size > 1000:
            motion_ok = True
            break
    src = str(shot.get("i2v_source") or "").strip().lower()
    if not motion_ok or src not in ("ai", "keys"):
        raise ValueError(
            "专业档口型必须以真 I2V 运动片为底（i2v_source=ai|keys），"
            "禁止静图 lip_base / Ken Burns 顶替"
        )

    return {"ok": True, "provider": head, "cascade": cascade, "i2v_source": src}
