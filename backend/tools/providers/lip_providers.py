"""Lip-sync adapters (R1).

Provider contract: fn(scene, voice, dest, shot, duration) ->
"mock" | "http" | "fallback".
"""

from __future__ import annotations

import shutil

from tools.providers.registry import register


def _mock(scene, voice, dest, shot, duration) -> str:
    from tools.drama_lip import _mock_lip

    if not shutil.which("ffmpeg"):
        return "fallback"
    return "mock" if _mock_lip(scene, voice, dest, duration) else "fallback"


def _http(scene, voice, dest, shot, duration) -> str:
    from tools.drama_lip import _http_lip

    return "http" if _http_lip(scene, voice, dest, shot, duration) else "fallback"


def _fallback(_scene, _voice, _dest, _shot, _duration) -> str:
    return "fallback"


# musetalk / wav2lip are real endpoints via the same http adapter today.
for pid in ("http", "api", "musetalk", "wav2lip"):
    register("lip", pid, _http)
for pid in ("none", "off", "fail"):
    register("lip", pid, _fallback)
register("lip", "mock", _mock)