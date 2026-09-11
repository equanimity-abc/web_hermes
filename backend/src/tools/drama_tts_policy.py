"""TTS degrade policy: studio forbids silent edge-tts fallback."""

from __future__ import annotations

from contextvars import ContextVar
from typing import Any

# When False, commercial TTS adapters must raise instead of falling back to edge-tts.
_allow_edge_degrade: ContextVar[bool] = ContextVar("drama_tts_allow_edge_degrade", default=True)


def allow_tts_edge_degrade() -> bool:
    return bool(_allow_edge_degrade.get())


def set_tts_edge_degrade(allowed: bool) -> Any:
    """Return a context token; reset with token or reset_tts_edge_degrade."""
    return _allow_edge_degrade.set(bool(allowed))


def reset_tts_edge_degrade(token: Any) -> None:
    _allow_edge_degrade.reset(token)


def refuse_or_edge(text: str, dest: Any, *, voice: str | None, reason: str) -> bool:
    """Studio: raise; draft/balanced: fall back to edge-tts."""
    if not allow_tts_edge_degrade():
        raise RuntimeError(
            f"专业档 TTS 禁止静默降级到 edge-tts（{reason}）。"
            "请配置 ARK_API_KEY / DASHSCOPE_API_KEY / TTS_API_URL，或将 quality_profile 设为 draft。"
        )
    from tools.providers.tts_providers import _edge_tts

    return _edge_tts(text, dest, voice=voice)


def resolve_tts_degrade_for_slug(slug: str) -> bool:
    """Only draft profile may silently fall back to edge-tts."""
    try:
        from tools.drama_profiles import resolve_quality_profile

        return resolve_quality_profile(slug) == "draft"
    except Exception:
        return False
