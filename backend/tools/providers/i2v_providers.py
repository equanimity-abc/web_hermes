"""I2V motion adapters (R1).

Provider contract: fn(scene, dest, shot, seconds) -> "ai" | "none".
"none" signals the caller to fall back to Ken Burns still motion.
"""

from __future__ import annotations

from tools.providers.registry import register


def _mock(scene, dest, shot, seconds) -> str:
    from tools.drama_i2v import _provider_mock_ai

    return "ai" if _provider_mock_ai(scene, dest, shot, seconds) else "none"


def _fail(_scene, _dest, _shot, _seconds) -> str:
    return "none"


def _http(scene, dest, shot, seconds) -> str:
    from tools.drama_i2v import _provider_http

    return "ai" if _provider_http(scene, dest, shot, seconds) else "none"


def _pollinations(scene, dest, shot, seconds) -> str:
    from tools.drama_i2v import _provider_pollinations

    return "ai" if _provider_pollinations(scene, dest, shot, seconds) else "none"


register("i2v", "mock", _mock)
register("i2v", "mock_ai", _mock)
register("i2v", "fail", _fail)
register("i2v", "http", _http)
register("i2v", "api", _http)
register("i2v", "kling", _http)
register("i2v", "hailuo", _http)
register("i2v", "pollinations", _pollinations)
register("i2v", "none", _fail)
register("i2v", "off", _fail)
register("i2v", "l0", _mock)
