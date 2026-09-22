"""TTS 降级策略：仅火山方舟 Seed Audio，不再静默降级 edge-tts。"""

from __future__ import annotations

from contextvars import ContextVar
from typing import Any

# 仅火山方舟 Seed Audio：无 edge-tts 降级（保留此开关以兼容旧调用，但不再生效）。
_allow_edge_degrade: ContextVar[bool] = ContextVar("drama_tts_allow_edge_degrade", default=True)


def allow_tts_edge_degrade() -> bool:
    return bool(_allow_edge_degrade.get())


def set_tts_edge_degrade(allowed: bool) -> Any:
    """Return a context token; reset with token or reset_tts_edge_degrade."""
    return _allow_edge_degrade.set(bool(allowed))


def reset_tts_edge_degrade(token: Any) -> None:
    _allow_edge_degrade.reset(token)


def refuse_or_edge(text: str, dest: Any, *, voice: str | None, reason: str) -> bool:
    """仅火山方舟 Seed Audio；不再降级 edge-tts（draft 档也如此）。"""
    raise RuntimeError(
        f"TTS 失败（{reason}）。仅支持火山方舟 Seed Audio，请配置 ARK_API_KEY。"
    )


def resolve_tts_degrade_for_slug(slug: str) -> bool:
    """Only draft profile may silently fall back to edge-tts."""
    try:
        from tools.drama_profiles import resolve_quality_profile

        return resolve_quality_profile(slug) == "draft"
    except Exception:
        return False
