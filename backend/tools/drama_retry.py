"""Generation robustness helpers (R3).

One shared retry + degrade surface for the four external generation steps
(image / tts / i2v / lip). A failure no longer silently produces a broken clip:
the shot records why a layer degraded, and the episode result carries a
`degraded` list so the user sees exactly which shots are missing voice / falling
back to still imagery.
"""

from __future__ import annotations

import time
from typing import Any, Callable

DEFAULT_ATTEMPTS = 3
_DELAY_SEC = 0.5


def retry_call(
    fn: Callable[..., Any],
    *args: Any,
    attempts: int = DEFAULT_ATTEMPTS,
    delay: float = _DELAY_SEC,
    ok: Callable[[Any], bool] | None = None,
    **kwargs: Any,
) -> Any:
    """Call ``fn`` up to ``attempts`` times, retrying on unsuccessful results.

    ``ok(result)`` marks success; by default a truthy result wins. For string
    sentinel results (e.g. lip ``"fallback"``), pass ``ok=lambda r: r != "fallback"``.
    If every attempt fails, the last result is returned (not raised) so callers
    keep their existing fallback flow.
    """
    last: Any = None
    for i in range(max(1, int(attempts))):
        last = fn(*args, **kwargs)
        good = ok(last) if ok is not None else bool(last)
        if good:
            return last
        if i < int(attempts) - 1:
            time.sleep(delay)
    return last


def degraded_entry(shot_n: Any, layer: str, reason: str) -> dict[str, Any]:
    """One-line degrade record attached to the episode result."""
    return {
        "shot": int(shot_n or 0),
        "layer": layer,
        "reason": reason,
    }