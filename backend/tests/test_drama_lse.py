"""Lip LSE proxy: audio envelope must use RMS (not bipolar average)."""

from __future__ import annotations

import math
import struct
import wave
from pathlib import Path

from tools.drama_lse import SCORE_VERSION, _audio_rms_envelope, _corr, score_lip


def _write_tone_wav(path: Path, *, hz: float = 4.0, seconds: float = 1.0, rate: int = 2400) -> None:
    """Amplitude-modulated tone so RMS envelope varies at ``hz``."""
    n = int(rate * seconds)
    frames = bytearray()
    for i in range(n):
        t = i / rate
        env = 0.35 + 0.65 * (0.5 + 0.5 * math.sin(2 * math.pi * hz * t))
        sample = int(12000 * env * math.sin(2 * math.pi * 440 * t))
        frames += struct.pack("<h", max(-32767, min(32767, sample)))
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(bytes(frames))


def test_audio_rms_envelope_has_variance(tmp_path: Path):
    wav = tmp_path / "tone.wav"
    _write_tone_wav(wav)
    env = _audio_rms_envelope(str(wav), hz=24)
    assert len(env) >= 8
    assert max(env) - min(env) > 0.05


def test_corr_with_rms_envelope_not_stuck_at_zero(tmp_path: Path):
    wav = tmp_path / "tone.wav"
    _write_tone_wav(wav, hz=3.0, seconds=1.2)
    env = _audio_rms_envelope(str(wav), hz=24)
    # Synthetic mouth motion correlated with envelope
    mouth = [0.4 + 0.2 * e for e in env]
    assert _corr(mouth, env) > 0.5


def test_score_version_constant():
    assert SCORE_VERSION >= 2


def test_real_lip_proxy_advisory_does_not_hard_fail(monkeypatch, tmp_path: Path):
    from tools.drama_qc import qc_shot_lip

    lip = tmp_path / "shot01_lip.mp4"
    lip.write_bytes(b"x" * 2048)
    shot = {
        "n": 1,
        "kind": "dialogue",
        "size": "MCU",
        "speaker": "嫦娥",
        "lip_source": "pixverse",
        "assets": {"lip": str(lip)},
        "lip_score": {
            "status": "ok",
            "method": "proxy",
            "version": SCORE_VERSION,
            "lse_c": 0.0,
            "lse_d": 1.0,
        },
    }
    monkeypatch.setattr("tools.drama_lip.lip_eligible", lambda _s: {"ok": True})
    monkeypatch.setattr("tools.drama_qc._asset_file", lambda _s, layer: lip if layer == "lip" else None)
    monkeypatch.setattr("tools.drama_qc.qc_thresholds", lambda _slug: {"lse_c_min": 0.15, "lse_d_max": 0.9})
    result = qc_shot_lip("demo", shot, apply=False)
    assert result["pass"] is True
    assert result.get("reason") == "proxy_advisory"
