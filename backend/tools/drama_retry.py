"""Generation robustness helpers (R3 + P1-6).

One shared retry + circuit-breaker + degrade surface for the four external
generation steps (image / tts / i2v / lip). A failure no longer silently
produces a broken clip: the shot records why a layer degraded, and the episode
result carries a `degraded` list so the user sees exactly which shots are
missing voice / falling back to still imagery.

Circuit breakers are keyed per provider, so a flaky external endpoint (e.g.
one http adapter) trips its own breaker without blocking the mock/L0 fallback.
"""
from __future__ import annotations

import threading
import time
from typing import Any, Callable

DEFAULT_ATTEMPTS = 3
_DELAY_SEC = 0.5
_DEFAULT_BACKOFF = 1.6
DEFAULT_FAILURE_THRESHOLD = 5
DEFAULT_COOLDOWN_SEC = 60.0


class CircuitBreaker:
    """Open after ``failure_threshold`` consecutive failures; half-open a probe
    after ``cooldown_sec``. Thread-safe and per-provider keyed."""

    def __init__(
        self,
        *,
        failure_threshold: int = DEFAULT_FAILURE_THRESHOLD,
        cooldown_sec: float = DEFAULT_COOLDOWN_SEC,
    ) -> None:
        self.failure_threshold = max(1, int(failure_threshold))
        self.cooldown_sec = max(0.0, float(cooldown_sec))
        self._failures = 0
        self._opened_at = 0.0
        self._lock = threading.Lock()

    def should_attempt(self) -> bool:
        with self._lock:
            if self._failures < self.failure_threshold:
                return True
            return (time.monotonic() - self._opened_at) >= self.cooldown_sec

    def record_success(self) -> None:
        with self._lock:
            self._failures = 0
            self._opened_at = 0.0

    def record_failure(self) -> None:
        with self._lock:
            self._failures += 1
            if self._failures >= self.failure_threshold and self._opened_at == 0.0:
                self._opened_at = time.monotonic()

    @property
    def open(self) -> bool:
        with self._lock:
            return self._failures >= self.failure_threshold and (
                (time.monotonic() - self._opened_at) < self.cooldown_sec
            )

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "failures": self._failures,
                "open": self._failures >= self.failure_threshold
                and ((time.monotonic() - self._opened_at) < self.cooldown_sec),
                "failure_threshold": self.failure_threshold,
                "cooldown_sec": self.cooldown_sec,
            }


_breakers: dict[str, CircuitBreaker] = {}
_breakers_lock = threading.Lock()


def breaker_for(key: str) -> CircuitBreaker:
    with _breakers_lock:
        breaker = _breakers.get(key)
        if breaker is None:
            breaker = CircuitBreaker()
            _breakers[key] = breaker
        return breaker


def breaker_snapshot(key: str) -> dict[str, Any]:
    with _breakers_lock:
        breaker = _breakers.get(key)
    return breaker.snapshot() if breaker else {"failures": 0, "open": False}


def retry_call(
    fn: Callable[..., Any],
    *args: Any,
    attempts: int = DEFAULT_ATTEMPTS,
    delay: float = _DELAY_SEC,
    ok: Callable[[Any], bool] | None = None,
    backoff: float = _DEFAULT_BACKOFF,
    circuit_key: str | None = None,
    **kwargs: Any,
) -> Any:
    """Call ``fn`` up to ``attempts`` times with exponential backoff.

    ``ok(result)`` marks success; by default a truthy result wins. For string
    sentinel results (e.g. lip ``"fallback"``), pass ``ok=lambda r: r != "fallback"``.
    If ``circuit_key`` is given, a per-key breaker short-circuits when open.

    If every attempt fails the last result is returned (not raised) so callers
    keep their existing fallback flow. Exceptions are caught and treated as
    failures (the last result becomes ``None``).
    """
    attempts = max(1, int(attempts))
    backoff = max(1.0, float(backoff))
    breaker = breaker_for(circuit_key) if circuit_key else None
    last: Any = None

    for i in range(attempts):
        if breaker is not None and not breaker.should_attempt():
            break
        try:
            last = fn(*args, **kwargs)
            failed = False
        except Exception:
            last = None
            failed = True

        good = ok(last) if ok is not None else bool(last)
        if good and not failed:
            if breaker is not None:
                breaker.record_success()
            return last

        if breaker is not None:
            breaker.record_failure()
        if i < attempts - 1:
            time.sleep(delay * (backoff ** i))

    return last


def degrade_entry(
    shot_n: Any,
    layer: str,
    reason: str,
    *,
    provider: str = "",
    attempts: int = DEFAULT_ATTEMPTS,
) -> dict[str, Any]:
    """Structured degrade record attached to the episode result (P1-6)."""
    entry: dict[str, Any] = {
        "shot": int(shot_n or 0),
        "layer": layer,
        "reason": reason,
    }
    if provider:
        entry["provider"] = str(provider)
    entry["attempts"] = max(1, int(attempts))
    return entry


def degraded_entry(shot_n: Any, layer: str, reason: str) -> dict[str, Any]:
    """Backward-compatible one-line degrade record (kept for existing callers)."""
    return degrade_entry(shot_n, layer, reason)