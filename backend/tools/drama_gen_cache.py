"""Content-addressed generation cache for image/TTS bytes."""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path
from typing import Any

from tools.workspace import resolve_safe


def _key(*parts: Any) -> str:
    raw = "|".join(str(p if p is not None else "") for p in parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:40]


def cache_rel(slug: str, kind: str, digest: str, suffix: str) -> str:
    safe_kind = "".join(ch for ch in str(kind or "gen") if ch.isalnum() or ch in "-_")[:24] or "gen"
    suf = suffix if str(suffix).startswith(".") else f".{suffix or 'bin'}"
    return f"dramas/{slug}/.gencache/{safe_kind}/{digest}{suf}"


def lookup(
    slug: str,
    *,
    kind: str,
    prompt: str,
    seed: Any = 0,
    provider: str = "",
    model: str = "",
    suffix: str = ".png",
) -> Path | None:
    digest = _key(kind, prompt, seed, provider, model)
    rel = cache_rel(slug, kind, digest, suffix)
    try:
        path = resolve_safe(rel)
    except ValueError:
        return None
    if path.is_file() and path.stat().st_size > 32:
        return path
    return None


def store(
    slug: str,
    src: Path,
    *,
    kind: str,
    prompt: str,
    seed: Any = 0,
    provider: str = "",
    model: str = "",
    suffix: str = "",
) -> str | None:
    if not src.is_file() or src.stat().st_size < 32:
        return None
    suf = suffix or src.suffix or ".bin"
    digest = _key(kind, prompt, seed, provider, model)
    rel = cache_rel(slug, kind, digest, suf)
    try:
        dest = resolve_safe(rel)
    except ValueError:
        return None
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.resolve() != src.resolve():
        shutil.copy2(src, dest)
    return rel
