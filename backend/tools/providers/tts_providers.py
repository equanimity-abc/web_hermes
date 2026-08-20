"""TTS adapters (R1).

Provider contract: fn(text, dest, *, voice=None) -> bool.
edge-tts is the real local backend. volcano / ms (high-fidelity) are named in
the pro preset but have no real adapter yet — registered as edge-tts aliases so
pro renders still work (degraded), and a future drop-in module can override
these ids via register() (last wins).
"""

from __future__ import annotations

from tools.providers.registry import register


def _edge_tts(text, dest, *, voice=None) -> bool:
    from tools.drama_video import _tts_to_file

    return _tts_to_file(text, dest, voice=voice)


def _none(_text, _dest, **_kwargs) -> bool:
    return False


register("tts", "edge-tts", _edge_tts)
# Degraded aliases until a real high-fidelity adapter is added.
register("tts", "volcano", _edge_tts)
register("tts", "ms", _edge_tts)
register("tts", "azure", _edge_tts)
register("tts", "none", _none)
register("tts", "off", _none)