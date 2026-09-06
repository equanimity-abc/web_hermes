"""Lip-sync score proxy (Q2).

Real SyncNet LSE-C/LSE-D is optional. This script always produces a numeric
score from mouth-ROI luma vs audio envelope so QC is not blocked on torch.
Missing files → status=skipped (must not be treated as pass).

Audio envelope MUST be RMS (or abs) before downsampling. Raw PCM at 24 Hz
averages bipolar speech to ~0 → constant u8 128 → corr always 0 (false fail).
"""

from __future__ import annotations

import math
import os
import shutil
import struct
import subprocess
from pathlib import Path
from typing import Any

SAMPLE_HZ = 24
# Bump when scoring math changes so cached lip_score is recomputed.
SCORE_VERSION = 2
_SAMPLES_PER_FRAME = 100


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


def _audio_rms_envelope(src: str, *, hz: int = SAMPLE_HZ, timeout: int = 40) -> list[float]:
    """Per-frame RMS envelope at ``hz`` Hz (abs energy, not bipolar average)."""
    rate = max(1, int(hz) * _SAMPLES_PER_FRAME)
    ff = _ffmpeg_bin()
    creationflags = 0
    if os.name == "nt":
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    proc = subprocess.run(
        [
            ff,
            "-i",
            src,
            "-ac",
            "1",
            "-ar",
            str(rate),
            "-f",
            "s16le",
            "-",
        ],
        capture_output=True,
        timeout=timeout,
        creationflags=creationflags,
    )
    raw = proc.stdout or b""
    if proc.returncode != 0 or len(raw) < 2:
        return []
    n = len(raw) // 2
    samples = struct.unpack("<" + "h" * n, raw[: n * 2])
    chunk = _SAMPLES_PER_FRAME
    out: list[float] = []
    for i in range(0, len(samples) - chunk + 1, chunk):
        window = samples[i : i + chunk]
        rms = math.sqrt(sum(x * x for x in window) / chunk) / 32768.0
        out.append(rms)
    return out


def score_lip(video: Path, audio: Path | None = None) -> dict[str, Any]:
    """Return lse_c (higher better) / lse_d (lower better) proxy."""
    if not shutil.which(_ffmpeg_bin()):
        return {
            "status": "skipped",
            "reason": "no_ffmpeg",
            "method": "proxy",
            "version": SCORE_VERSION,
            "lse_c": None,
            "lse_d": None,
        }
    if not video.is_file() or video.stat().st_size < 500:
        return {
            "status": "skipped",
            "reason": "no_lip_video",
            "method": "proxy",
            "version": SCORE_VERSION,
            "lse_c": None,
            "lse_d": None,
        }
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
    envelope = _audio_rms_envelope(src_audio, hz=SAMPLE_HZ)
    if len(mouth) < 8 or len(envelope) < 8:
        return {
            "status": "skipped",
            "reason": "too_short",
            "method": "proxy",
            "version": SCORE_VERSION,
            "lse_c": None,
            "lse_d": None,
        }
    lse_c = round(_corr(mouth, envelope), 4)
    lse_d = round(max(0.0, 1.0 - abs(lse_c)), 4)
    return {
        "status": "ok",
        "method": "proxy",
        "version": SCORE_VERSION,
        "lse_c": lse_c,
        "lse_d": lse_d,
        "frames": min(len(mouth), len(envelope)),
    }
