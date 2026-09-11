"""Phase E research stubs: quality profiles + future degrade matrix (not enabled).

Studio remains the only active hard profile. balanced/draft are explicit hooks
for a later release — never silently activate from studio.
"""

from __future__ import annotations

from typing import Any

PROFILES = ("studio", "balanced", "draft")
DEFAULT_PROFILE = "studio"

# Research placeholders — not wired into produce yet.
L5_RESEARCH = {
    "id": "L5",
    "status": "research",
    "title": "全帧插值 / 动画中间帧",
    "note": "不阻塞专业交付；启用前需单独验收与成本模型。",
}

MULTI_CHAR_RESEARCH = {
    "id": "multi_char_consistency",
    "status": "research",
    "title": "多角色同框强一致",
    "note": "Phase D 已支持双人 CU 锁 L/R；群戏同框列入研究。",
}

CLOUD_WORKER_RESEARCH = {
    "id": "cloud_object_store_workers",
    "status": "research",
    "title": "云端对象存储 + 多机 worker",
    "note": "本机队列 + SHOT_CONCURRENCY 先行；多机调度另开项目。",
}

# Explicit degrade matrix — documentation only until product turns it on.
DEGRADE_MATRIX: dict[str, dict[str, Any]] = {
    "studio": {
        "allow_l0_narrative": False,
        "allow_mock_lip": False,
        "allow_kenburns_i2v": False,
        "identity_min": 0.75,
        "lse_c_min": 0.15,
        "badge": None,
    },
    "balanced": {
        "allow_l0_narrative": True,
        "allow_mock_lip": False,
        "allow_kenburns_i2v": False,
        "identity_min": 0.70,
        "lse_c_min": 0.10,
        "badge": None,
        "note": "后续启用：部分 L0；identity 略降；仍禁 mock lip 冒充",
    },
    "draft": {
        "allow_l0_narrative": True,
        "allow_mock_lip": True,
        "allow_kenburns_i2v": True,
        "identity_min": 0.60,
        "lse_c_min": 0.0,
        "badge": "草稿",
        "note": "后续启用：允许免费后端与 Ken Burns，须角标「草稿」",
    },
}


def normalize_quality_profile(raw: Any) -> str:
    name = str(raw or DEFAULT_PROFILE).strip().lower()
    if name in ("pro", "hq", "professional"):
        return "studio"
    if name not in PROFILES:
        return DEFAULT_PROFILE
    return name


def resolve_quality_profile(
    slug: str = "",
    *,
    explicit: str | None = None,
    models: dict[str, Any] | None = None,
) -> str:
    """Resolve active profile. Explicit arg wins; else models.quality_profile; else studio."""
    if explicit is not None and str(explicit).strip():
        return normalize_quality_profile(explicit)
    if models is None and slug:
        try:
            from tools.drama_models import load_models

            models = load_models(slug)
        except Exception:
            models = None
    if isinstance(models, dict):
        qp = models.get("quality_profile") or (models.get("nodes") or {}).get("quality_profile")
        if qp:
            return normalize_quality_profile(qp)
    return DEFAULT_PROFILE


def profile_policy(profile: str | None = None) -> dict[str, Any]:
    name = normalize_quality_profile(profile)
    row = dict(DEGRADE_MATRIX.get(name) or DEGRADE_MATRIX[DEFAULT_PROFILE])
    row["profile"] = name
    row["active"] = name == "studio"  # only studio is enforced today
    return row


def research_backlog() -> list[dict[str, Any]]:
    return [dict(L5_RESEARCH), dict(MULTI_CHAR_RESEARCH), dict(CLOUD_WORKER_RESEARCH)]


def assert_profile_allows_studio_gates(profile: str | None = None) -> None:
    """Phase E: non-studio profiles are not implemented — refuse silent degrade."""
    name = normalize_quality_profile(profile)
    if name != "studio":
        raise ValueError(
            f"quality_profile={name} 尚未启用（Phase E 仅占位）。"
            "请使用 studio，或等待 balanced/draft 正式开关上线；禁止在 studio 内偷偷降级。"
        )
