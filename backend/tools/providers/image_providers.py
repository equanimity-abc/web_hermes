"""Image generation adapters (R1).

Provider contract: fn(prompt, dest, *, seed=0, slug="", shot=None,
width=0, height=0) -> bool. Returns False so business code falls back to the
atmospheric still.
"""

from __future__ import annotations

from typing import Any

from config import config
from tools.providers.registry import register


def _pollinations(
    prompt: str,
    dest,
    *,
    seed: int = 0,
    slug: str = "",
    shot: Any = None,
    width: int = 0,
    height: int = 0,
) -> bool:
    from io import BytesIO
    from urllib.parse import quote

    import httpx
    from PIL import Image

    from tools.drama_video import _fit_cover  # pure PIL helper, no cycle

    target_w = int(width or 1620)
    target_h = int(height or 2880)
    model = config.IMAGE_GEN_MODEL or "flux"
    url = (
        "https://image.pollinations.ai/prompt/"
        f"{quote(str(prompt))}?width=1024&height=1792&model={quote(model)}"
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


register("image", "pollinations", _pollinations)
register("image", "flux", _pollinations)
register("image", "http", _pollinations)
# mock / none / off are intentionally unfilled → caller falls back.
register("image", "mock", _never)
register("image", "none", _never)
register("image", "off", _never)