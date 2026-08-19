"""Lip-sync score proxy (Q2).

Real SyncNet LSE-C/LSE-D is optional. This script always produces a numeric
score from mouth-ROI luma vs audio envelope so QC is not blocked on torch.
Missing files → status=skipped (must not be treated as pass).
"""

from __future__ import annotations

import math
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

SAMPLE_HZ = 24


def _ffmpeg_bin() -> str:
    return os.getenv("FFMPEG_BIN", "ffmpeg")


def _corr(xs: list[float], ys: list[float]) -> float:
    n = min(len(xs), len(ys))
    if n < 8:
        return 0.0
    a = xs[:n]
    b = ys[:n]
    ma = sum(a) / n
    mb = sum(b) / n
    num = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    da = math.sqrt(sum((x - ma) ** 2 for x in a))
    db = math.sqrt(sum((y - mb) ** 2 for y in b))
    if da < 1e-9 or db < 1e-9:
        return 0.0
    return max(-1.0, min(1.0, num / (da * db)))


def _u8_series(args: list[str], *, timeout: int = 40) -> list[float]:
    creationflags = 0
    if os.name == "nt":
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    proc = subprocess.run(
        args,
        capture_output=True,
        timeout=timeout,
        creationflags=creationflags,
    )
    if proc.returncode != 0 or not proc.stdout:
        return []
    return [b / 255.0 for b in proc.stdout]


def score_lip(video: Path, audio: Path | None = None) -> dict[str, Any]:
    """Return lse_c (higher better) / lse_d (lower better) proxy."""
    if not shutil.which(_ffmpeg_bin()):
        return {"status": "skipped", "reason": "no_ffmpeg", "method": "proxy", "lse_c": None, "lse_d": None}
    if not video.is_file() or video.stat().st_size < 500:
        return {"status": "skipped", "reason": "no_lip_video", "method": "proxy", "lse_c": None, "lse_d": None}
    ff = _ffmpeg_bin()
    mouth = _u8_series(
        [
            ff,
            "-i",
            str(video),
            "-vf",
            f"fps={SAMPLE_HZ},crop=200:90:(iw-200)/2:ih*0.62,scale=1:1,format=gray",
            "-an",
            "-f",
            "rawvideo",
            "-",
        ]
    )
    src_audio = str(audio) if audio and audio.is_file() else str(video)
    envelope = _u8_series(
        [
            ff,
            "-i",
            src_audio,
            "-ac",
            "1",
            "-ar",
            str(SAMPLE_HZ),
            "-f",
            "u8",
            "-",
        ]
    )
    if len(mouth) < 8 or len(envelope) < 8:
        return {
            "status": "skipped",
            "reason": "too_short",
            "method": "proxy",
            "lse_c": None,
            "lse_d": None,
        }
    lse_c = round(_corr(mouth, envelope), 4)
    lse_d = round(max(0.0, 1.0 - abs(lse_c)), 4)
    return {
        "status": "ok",
        "method": "proxy",
        "lse_c": lse_c,
        "lse_d": lse_d,
        "frames": min(len(mouth), len(envelope)),
    }
