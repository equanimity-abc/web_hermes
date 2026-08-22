"""Provider adapter registry (R1).

Every external generation capability (image / i2v / lip / tts) is dispatched
through one surface. Adding a new model = dropping a module into this package
that calls `register(...)`; business code never changes.

Capability contract:
  - image:  fn(prompt, dest, *, seed=0, slug="", shot=None, width=0, height=0) -> bool
  - i2v:    fn(scene, dest, shot, seconds) -> "ai" | "none"
  - lip:    fn(scene, voice, dest, shot, duration) -> "mock" | "http" | "fallback"
  - tts:    fn(text, dest, *, voice=None) -> bool
"""

from __future__ import annotations

import importlib
import pkgutil
import sys
from pathlib import Path
from typing import Any, Callable

CAPABILITIES = ("image", "i2v", "lip", "tts")

# Failure sentinel per capability (dispatch returns this on missing/exception).
_FALLBACK = {
    "image": False,
    "i2v": "none",
    "lip": "fallback",
    "tts": False,
}

_registry: dict[str, dict[str, Callable[..., Any]]] = {cap: {} for cap in CAPABILITIES}
_loaded = False


def register(capability: str, provider_id: str, fn: Callable[..., Any]) -> None:
    """Register a generation function for a provider id. Idempotent (last wins)."""
    if capability not in CAPABILITIES:
        raise ValueError(f"未知 capability：{capability}，可选 {', '.join(CAPABILITIES)}")
    pid = str(provider_id or "").strip()
    if not pid:
        raise ValueError("provider_id 不能为空")
    _registry[capability][pid] = fn


def has(capability: str, provider_id: str) -> bool:
    if capability not in CAPABILITIES:
        return False
    return str(provider_id or "").strip() in _registry[capability]


def available_ids(capability: str) -> list[str]:
    if capability not in CAPABILITIES:
        return []
    return sorted(_registry[capability].keys())


def registered_snapshot() -> dict[str, dict[str, bool]]:
    """One-shot view of every registered adapter (used by S0 health checks)."""
    return {
        cap: {pid: True for pid in _registry[cap]}
        for cap in CAPABILITIES
    }


def dispatch(capability: str, provider_id: str, *args: Any, **kwargs: Any) -> Any:
    """Route one generation call to the right adapter (with failure sentinel)."""
    if capability not in CAPABILITIES:
        raise ValueError(f"未知 capability：{capability}")
    pid = str(provider_id or "").strip()
    fn = _registry[capability].get(pid)
    if fn is None:
        return _FALLBACK[capability]
    try:
        return fn(*args, **kwargs)
    except Exception:
        # Never let a broken provider take down render; caller falls back.
        return _FALLBACK[capability]


def load_all() -> list[str]:
    """Import every module in this package so its register() side effects run."""
    global _loaded
    if _loaded:
        return []
    _loaded = True
    loaded: list[str] = []
    # __name__ == "tools.providers.registry"; the package is its parent.
    pkg_name = __name__.rsplit(".", 1)[0]
    try:
        package = importlib.import_module(pkg_name)
    except Exception:
        return loaded
    pkg_path = Path(package.__file__).resolve().parent if package.__file__ else None
    if pkg_path is None:
        return loaded
    for mod in pkgutil.iter_modules([str(pkg_path)]):
        if mod.ispkg or mod.name in ("registry", "__init__"):
            continue
        try:
            importlib.import_module(f"{pkg_name}.{mod.name}")
            loaded.append(mod.name)
        except Exception as e:  # pragma: no cover - log but don't crash startup
            print(f"[providers] failed to load {mod.name}: {e}")
    return loaded
