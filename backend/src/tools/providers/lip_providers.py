"""Lip-sync 辅助函数：口型由 Seedance 内生，非 Ark 口型 provider 已移除。

仅保留判定「口型是否真实产出」的辅助函数，供 clip 组装/QC 使用。
"""

from __future__ import annotations

from typing import Any

# 真实口型来源（clip 组装时可烧录进成片）。
# 非 Ark 口型 provider（pixverse/latentsync/musetalk/wav2lip/http）已移除。
REAL_LIP_SOURCES = frozenset(
    {
        "ai",
        "seedance",  # Seedance I2V + TTS reference_audio（生产线口型）
        "recovered",  # orphan lip file restored when metadata was cleared
    }
)


def lip_source_base(source: str) -> str:
    """Strip strategy suffixes like ``pixverse+per_turn`` → ``pixverse``."""
    return str(source or "").strip().split("+")[0].strip().lower()


def lip_source_is_real(source: str) -> bool:
    """True when a lip-sync provider actually produced the lip layer."""
    base = lip_source_base(source)
    return bool(base) and base in REAL_LIP_SOURCES


def lip_video_usable(shot: dict, lip_path) -> bool:
    """Whether clip assembly should burn in the lip video (not motion-only)."""
    from pathlib import Path

    path = Path(lip_path) if lip_path is not None else None
    if path is None or not path.is_file() or path.stat().st_size <= 500:
        return False
    if lip_source_is_real(str(shot.get("lip_source") or "")):
        return True
    # Orphan lip file (provider wrote mp4 but lip_source cleared): still prefer over motion
    # when duration tracks the VO closely — avoids 9s motion + 1.8s dialogue desync.
    src = str(shot.get("lip_source") or "").strip().lower()
    if src not in ("", "fallback", "blocked", "none", "off", "skipped"):
        return False
    voice_rel = str((shot.get("assets") or {}).get("voice") or "").strip()
    if not voice_rel:
        return path.stat().st_size > 500
    try:
        from tools.workspace import resolve_safe
        from tools.drama_video import _probe_media_seconds

        voice = resolve_safe(voice_rel)
        if not voice.is_file():
            return True
        vd = float(_probe_media_seconds(voice) or 0)
        ld = float(_probe_media_seconds(path) or 0)
        if vd > 0.3 and ld > 0.2 and abs(vd - ld) <= 0.45:
            if isinstance(shot, dict) and not str(shot.get("lip_source") or "").strip():
                shot["lip_source"] = "recovered"
            return True
    except Exception:
        return path.stat().st_size > 1000
    return False
