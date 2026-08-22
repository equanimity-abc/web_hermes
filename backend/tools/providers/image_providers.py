"""Image generation adapters (R1 + R4 refs contract).

Provider contract: fn(prompt, dest, *, seed=0, slug="", shot=None,
width=0, height=0, refs=()) -> bool. Returns False so business code falls back
to the atmospheric still.

`refs`: list[str] of locked character reference-image paths. Providers that
support img2img / IP-Adapter must consume them for face consistency; txt2img
providers (pollinations/flux) degrade to a stronger identity clause in prompt.
"""

from __future__ import annotations

import hashlib
import os
import shutil
from pathlib import Path
from typing import Any

from config import config
from tools.providers.registry import register
from tools.workspace import resolve_safe


def _pollinations(
    prompt: str,
    dest,
    *,
    seed: int = 0,
    slug: str = "",
    shot: Any = None,
    width: int = 0,
    height: int = 0,
    refs: tuple[str, ...] = (),
) -> bool:
    from io import BytesIO
    from urllib.parse import quote

    import httpx
    from PIL import Image

    from tools.drama_video import _fit_cover  # pure PIL helper, no cycle

    target_w = int(width or 1620)
    target_h = int(height or 2880)
    model = config.IMAGE_GEN_MODEL or "flux"
    final_prompt = str(prompt)
    if refs:
        # txt2img fallback: emphasize same-face / same-costume since we can't
        # feed the reference image directly. A real img2img adapter should
        # consume `refs` and skip this textual nudge.
        final_prompt = (
            f"{final_prompt}, keep face identical to the locked character "
            f"reference sheet, same facial structure and costume"
        )
    url = (
        "https://image.pollinations.ai/prompt/"
        f"{quote(final_prompt)}?width=1024&height=1792&model={quote(model)}"
        f"&nologo=true&enhance=true&seed={int(seed) & 0x7FFFFFFF}"
    )
    try:
        with httpx.Client(timeout=90.0, follow_redirects=True) as client:
            resp = client.get(url, headers={"User-Agent": "my-tiktok-video-agent/0.8"})
            resp.raise_for_status()
            img = Image.open(BytesIO(resp.content)).convert("RGB")
        img = _fit_cover(img, target_w, target_h)
        dest.parent.mkdir(parents=True, exist_ok=True)
        img.save(dest, "PNG")
        return dest.is_file() and dest.stat().st_size > 1000
    except Exception:
        return False


def _never(_prompt, _dest, **_kwargs) -> bool:
    return False


def _cache_key(
    prompt: str,
    *,
    seed: int,
    width: int,
    height: int,
    model: str,
    refs: tuple[str, ...] = (),
) -> str:
    """Content-addressed cache key: prompt + seed + size + model + ref bytes digest."""
    h = hashlib.sha256()
    h.update(str(prompt).encode("utf-8"))
    h.update(b"\x00")
    h.update(str(int(seed)).encode("ascii"))
    h.update(b"\x00")
    h.update(str(int(width)).encode("ascii"))
    h.update(b"\x00")
    h.update(str(int(height)).encode("ascii"))
    h.update(b"\x00")
    h.update(str(model).encode("ascii"))
    for ref in sorted(str(r or "") for r in refs):
        if not ref:
            continue
        try:
            path = resolve_safe(ref)
        except ValueError:
            continue
        h.update(b"\x00" + ref.encode("utf-8"))
        if path.is_file():
            size = path.stat().st_size
            h.update(b"\x00" + str(size).encode("ascii"))
            # Digest only the first 64KB to keep hashing fast on 1080p refs.
            with path.open("rb") as f:
                h.update(f.read(65536))
    return h.hexdigest()


def _cache_dir(slug: str) -> Path | None:
    if not slug:
        return None
    try:
        base = resolve_safe(f"dramas/{slug}/_image_cache")
    except ValueError:
        return None
    base.mkdir(parents=True, exist_ok=True)
    return base


def _try_cache(key: str, dest: Path, slug: str = "") -> bool:
    """Copy a cached image to dest if present. Returns True on hit."""
    if not slug:
        return False
    cache_dir = _cache_dir(slug)
    if cache_dir is None:
        return False
    src = cache_dir / f"{key}.png"
    if not src.is_file() or src.stat().st_size <= 1000:
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dest)
    return dest.is_file() and dest.stat().st_size > 1000


def _store_cache(key: str, dest: Path, slug: str = "") -> None:
    if not slug:
        return
    cache_dir = _cache_dir(slug)
    if cache_dir is None:
        return
    try:
        shutil.copyfile(dest, cache_dir / f"{key}.png")
    except OSError:
        pass


def _consistent_http(
    prompt: str,
    dest,
    *,
    seed: int = 0,
    slug: str = "",
    shot: Any = None,
    width: int = 0,
    height: int = 0,
    refs: tuple[str, ...] = (),
) -> bool:
    """S1: character-consistent image via a generic HTTP service.

    Contract (multipart/form-data):
        image   = reference image(s), repeated field, image/png
        prompt  = full text prompt
        seed    = reproducible seed
        width   = target width
        height  = target height
        model   = e.g. char-consistent
    Response body = PNG/JPEG. Uses CONSISTENT_IMAGE_URL / _KEY / _MODEL env.

    Falls back to cache (content-addressed) then, on miss, no network when the
    URL is unset (honest degrade to pollinations by the caller).
    """
    from io import BytesIO

    import httpx
    from PIL import Image

    from tools.drama_video import _fit_cover

    url = (config.CONSISTENT_IMAGE_URL or "").strip()
    if not url:
        # No consistent-image backend configured → honest degrade to the free
        # txt2img provider, still consuming refs as a stronger prompt clause.
        return _pollinations(
            prompt,
            dest,
            seed=seed,
            slug=slug,
            shot=shot,
            width=width,
            height=height,
            refs=refs,
        )

    target_w = int(width or 1620)
    target_h = int(height or 2880)
    model = config.CONSISTENT_IMAGE_MODEL or "char-consistent"
    key = _cache_key(prompt, seed=seed, width=target_w, height=target_h, model=model, refs=refs)
    if _try_cache(key, dest, slug=slug):
        return True

    fields: dict[str, str] = {
        "prompt": str(prompt),
        "seed": str(int(seed) & 0x7FFFFFFF),
        "width": str(target_w),
        "height": str(target_h),
        "model": model,
    }
    files: list[tuple[str, tuple[str, bytes, str]]] = []
    ref_idx = 0
    for rel in refs:
        if not str(rel or ""):
            continue
        try:
            path = resolve_safe(str(rel))
        except ValueError:
            continue
        if not path.is_file():
            continue
        data = path.read_bytes()
        files.append((f"image", (f"ref{ref_idx}.png", data, "image/png")))
        ref_idx += 1

    headers = {"User-Agent": "my-tiktok-video-agent/1.0"}
    auth = (config.CONSISTENT_IMAGE_KEY or "").strip()
    if auth:
        headers["Authorization"] = f"Bearer {auth}"

    try:
        with httpx.Client(timeout=180.0, follow_redirects=True) as client:
            resp = client.post(url, headers=headers, data=fields, files=files or None)
            resp.raise_for_status()
            img = Image.open(BytesIO(resp.content)).convert("RGB")
        img = _fit_cover(img, target_w, target_h)
        dest.parent.mkdir(parents=True, exist_ok=True)
        img.save(dest, "PNG")
        if dest.is_file() and dest.stat().st_size > 1000:
            _store_cache(key, dest, slug=slug)
            return True
        return False
    except Exception:
        return False


register("image", "jimeng", _consistent_http)
register("image", "pollinations", _pollinations)
register("image", "flux", _pollinations)
register("image", "http", _pollinations)
# mock / none / off are intentionally unfilled → caller falls back.
register("image", "mock", _never)
register("image", "none", _never)
register("image", "off", _never)
