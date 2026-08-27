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


def _is_character_ref_shot(shot: Any) -> bool:
    return str((shot or {}).get("kind") or "").strip().lower() == "character_ref"


def _save_provider_image(img, dest, *, shot: Any, target_w: int, target_h: int) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if _is_character_ref_shot(shot):
        img.save(dest, "PNG")
        return
    from tools.drama_video import _prepare_frame

    img = _prepare_frame(img, target_w, target_h)
    img.save(dest, "PNG")


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

    from tools.drama_retry import rate_limiter_for

    # S4: honor a default rpm for the free image endpoint to avoid being throttled.
    rpm = int(getattr(config, "DRAMA_RPM_DEFAULT", 0) or 0)
    rate_limiter_for(f"image:pollinations", rpm).acquire()

    from tools.drama_video import _prepare_frame  # pure PIL helper, no cycle

    target_w = int(width or 1620)
    target_h = int(height or 2880)
    model = config.IMAGE_GEN_MODEL or "flux"
    final_prompt = str(prompt)
    if _is_character_ref_shot(shot):
        from tools.drama_characters import character_ref_negative_prompt

        final_prompt = f"{final_prompt}。{character_ref_negative_prompt()}"
    if refs:
        # txt2img fallback: emphasize same-face / same-costume since we can't
        # feed the reference image directly. A real img2img adapter should
        # consume `refs` and skip this textual nudge.
        final_prompt = (
            f"{final_prompt}，与锁定角色参考图面部完全一致，"
            "五官结构与服装保持一致"
        )
    url = (
        "https://image.pollinations.ai/prompt/"
        f"{quote(final_prompt)}?width={target_w}&height={target_h}&model={quote(model)}"
        f"&nologo=true&enhance=true&seed={int(seed) & 0x7FFFFFFF}"
    )
    try:
        with httpx.Client(timeout=90.0, follow_redirects=True) as client:
            resp = client.get(url, headers={"User-Agent": "my-tiktok-video-agent/0.8"})
            resp.raise_for_status()
            img = Image.open(BytesIO(resp.content)).convert("RGB")
        _save_provider_image(img, dest, shot=shot, target_w=target_w, target_h=target_h)
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

    from tools.drama_video import _prepare_frame

    from tools.drama_retry import rate_limiter_for

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

    # S4: rate-limit the consistent-image gateway if a default rpm is set.
    rpm = int(getattr(config, "DRAMA_RPM_DEFAULT", 0) or 0)
    rate_limiter_for("image:consistent", rpm).acquire()

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
        img = _prepare_frame(img, target_w, target_h)
        dest.parent.mkdir(parents=True, exist_ok=True)
        img.save(dest, "PNG")
        if dest.is_file() and dest.stat().st_size > 1000:
            _store_cache(key, dest, slug=slug)
            return True
        return False
    except Exception:
        return False


def _qwen_image_plus_size(width: int, height: int) -> str:
    """qwen-image-plus / qwen-image 仅支持 5 种固定分辨率。"""
    w = max(1, int(width or 1328))
    h = max(1, int(height or 1328))
    ratio = w / h
    presets = (
        (16 / 9, "1664*928"),
        (4 / 3, "1472*1104"),
        (1.0, "1328*1328"),
        (3 / 4, "1104*1472"),
        (9 / 16, "928*1664"),
    )
    _, size = min(presets, key=lambda item: abs(item[0] - ratio))
    return size


def _kling_aspect_ratio(width: int, height: int) -> str:
    w = max(1, int(width or 1024))
    h = max(1, int(height or 1792))
    ratio = w / h
    presets = (
        (16 / 9, "16:9"),
        (4 / 3, "4:3"),
        (1.0, "1:1"),
        (3 / 4, "3:4"),
        (9 / 16, "9:16"),
    )
    _, label = min(presets, key=lambda item: abs(item[0] - ratio))
    return label


def _dashscope_gen_size(width: int, height: int, *, model: str = "") -> str:
    """Map target canvas to a DashScope-supported size string."""
    model_l = str(model or "").strip().lower()
    if "qwen-image" in model_l:
        return _qwen_image_plus_size(width, height)

    w = max(512, int(width or 720))
    h = max(512, int(height or 1280))
    ratio = w / h if h else 1.0
    presets = (
        (640, 640),
        (1024, 1024),
        (1328, 1328),
        (1664, 1664),
        (1980, 1980),
        (720, 1280),
        (768, 1344),
        (960, 1696),
        (1024, 1792),
    )
    pw, ph = min(presets, key=lambda p: abs(p[0] / p[1] - ratio) + abs(p[0] - w) * 1e-4)
    return f"{pw}*{ph}"


def _dashscope_image(
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
    """阿里云百炼 DashScope 通义万相文生图。

    Provider: wanx / dashscope。契约与 image adapter 一致（返回 bool）。

    注意：wan2.7-image-pro 是纯文生图，不支持传参考图。refs（锁定的定妆图）
    在这里退化为更强的外形/配色提示词（与 pollinations 一致）。图生图/角色
    一致性需另接支持 img2img 的模型（如 wanx imageedit）。
    """
    import time

    import httpx
    from PIL import Image

    from tools.drama_video import _prepare_frame

    key = (getattr(config, "DASHSCOPE_API_KEY", "") or "").strip()
    if not key:
        return False

    target_w = int(width or 1620)
    target_h = int(height or 2880)

    # 提示词：refs 退化为加强一致性描述；定妆图关闭扩写以免被改写成设定表风格。
    final_prompt = str(prompt)
    is_char_ref = _is_character_ref_shot(shot)
    if is_char_ref:
        from tools.drama_characters import character_ref_negative_prompt

        final_prompt = f"{final_prompt}。{character_ref_negative_prompt()}"
    if refs:
        final_prompt = (
            f"{final_prompt}，与锁定角色参考图面部完全一致，"
            "五官结构与服装保持一致"
        )

    base = (getattr(config, "DASHSCOPE_BASE_URL", "") or "https://dashscope.aliyuncs.com").rstrip("/")
    model = (getattr(config, "DASHSCOPE_IMAGE_MODEL", "") or "qwen-image-plus").strip()

    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "X-DashScope-Async": "enable",
        "User-Agent": "my-tiktok-video-agent/1.0",
    }
    query_headers = {"Authorization": f"Bearer {key}", "User-Agent": "my-tiktok-video-agent/1.0"}

    seed_val = int(seed) & 0x7FFFFFFF
    params: dict[str, Any] = {
        "size": _dashscope_gen_size(target_w, target_h, model=model),
        "n": 1,
        "seed": seed_val,
        "prompt_extend": not is_char_ref,
        "watermark": False,
    }
    if is_char_ref:
        from tools.drama_characters import character_ref_negative_prompt

        params["negative_prompt"] = character_ref_negative_prompt()
    body = {
        "model": model,
        "input": {"prompt": final_prompt},
        "parameters": params,
    }

    try:
        timeout = httpx.Timeout(30.0, read=200.0)
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            submit = client.post(
                f"{base}/api/v1/services/aigc/text2image/image-synthesis",
                headers=headers,
                json=body,
            )
            submit.raise_for_status()
            payload = submit.json()
            task_id = str(
                ((payload.get("output") or {}).get("task_id"))
                or ((payload.get("output") or {}).get("task_id"))
                or ""
            ).strip()
            if not task_id:
                return False

            deadline = time.monotonic() + 180.0
            while time.monotonic() < deadline:
                time.sleep(2.0)
                st = client.get(
                    f"{base}/api/v1/tasks/{task_id}",
                    headers=query_headers,
                )
                st.raise_for_status()
                info = st.json()
                out = info.get("output") or {}
                status = str(out.get("task_status") or "").upper()
                if status in ("SUCCEEDED", "SUCCESS"):
                    results = out.get("results") or []
                    url = ""
                    for r in results:
                        url = str(r.get("url") or "").strip()
                        if url:
                            break
                    if not url:
                        return False
                    img_resp = client.get(url)
                    img_resp.raise_for_status()
                    img = Image.open(__import__("io").BytesIO(img_resp.content)).convert("RGB")
                    _save_provider_image(img, dest, shot=shot, target_w=target_w, target_h=target_h)
                    return dest.is_file() and dest.stat().st_size > 1000
                if status in ("FAILED", "CANCELED", "UNKNOWN"):
                    return False
            return False
    except Exception:
        return False


def _dashscope_upload_public_url(rel: str, client, *, mime: str | None = None) -> str:
    """上传本地文件到百炼，返回公网 OSS 签名 URL（用于给可灵/PixVerse 当参考媒体）。

    走通用 dashscope 端点（已验证 purpose=chat-image-understanding 可上传图片）。
    mime 缺省时按扩展名推断（png/jpg/mp4/mp3/wav）。失败/限流返回空串。
    """
    import time

    key = (getattr(config, "DASHSCOPE_API_KEY", "") or "").strip()
    dbase = (getattr(config, "DASHSCOPE_BASE_URL", "") or "https://dashscope.aliyuncs.com").rstrip("/")
    if not key:
        return ""

    try:
        path = resolve_safe(str(rel))
        if not path.is_file():
            return ""
        if not mime:
            ext = path.suffix.lower()
            mime = {
                ".png": "image/png",
                ".jpg": "image/jpeg",
                ".jpeg": "image/jpeg",
                ".mp4": "video/mp4",
                ".mp3": "audio/mpeg",
                ".wav": "audio/wav",
            }.get(ext, "application/octet-stream")
        headers = {"Authorization": f"Bearer {key}"}
        with path.open("rb") as f:
            data = f.read()
        upload = client.post(
            f"{dbase}/api/v1/files",
            headers=headers,
            files={"files": (path.name, data, mime)},
            data={"purpose": "chat-image-understanding"},
        )
        upload.raise_for_status()
        uploaded = ((upload.json() or {}).get("data") or {}).get("uploaded_files") or []
        if not uploaded:
            return ""
        fid = str(uploaded[0].get("file_id") or "").strip()
        if not fid:
            return ""
        # 查询 file url，限流时简单重试几次。
        for _ in range(4):
            time.sleep(1.0)
            info = client.get(f"{dbase}/api/v1/files/{fid}", headers=headers)
            if info.status_code == 200:
                return str(((info.json() or {}).get("data") or {}).get("url") or "").strip()
        return ""
    except Exception:
        return ""


def _kling_image(
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
    """可灵 Kling 出图（走专属 MaaS 端点）。

    协议（与通用 DashScope 不同）：
      - 提交：POST /api/v1/services/aigc/image-generation/generation，
        带头 X-DashScope-Async: enable，input 用 messages（非 prompt）。
      - 查询：GET /api/v1/tasks/{task_id}，只带 Authorization（不带异步头）。
      - 结果：output.choices[0].message.content[0].image

    refs（本地的定妆图文件）会逐个上传到百炼换取公网 URL，再作为参考图
    注入 input.messages（{"image": url}），实现可灵的真·锁脸。
    """
    import time
    from io import BytesIO

    import httpx
    from PIL import Image

    from tools.drama_video import _prepare_frame

    key = (getattr(config, "DASHSCOPE_API_KEY", "") or "").strip()
    maas = (getattr(config, "DASHSCOPE_MAAS_BASE_URL", "") or "").strip()
    if not key or not maas:
        return False

    model = (getattr(config, "KLING_IMAGE_MODEL", "") or "kling/kling-v3-omni-image-generation").strip()
    target_w = int(width or 1024)
    target_h = int(height or 1792)
    is_char_ref = _is_character_ref_shot(shot)

    final_prompt = str(prompt)
    if _is_character_ref_shot(shot):
        from tools.drama_characters import character_ref_negative_prompt

        final_prompt = f"{final_prompt}。不要出现：{character_ref_negative_prompt()}"
    base = maas.rstrip("/")
    submit_headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "X-DashScope-Async": "enable",
    }
    query_headers = {"Authorization": f"Bearer {key}"}

    # 组装 input.messages 的 content：先放 text，再把参考图逐个上传成公网 URL 注入。
    content: list[dict[str, Any]] = [{"text": final_prompt}]

    try:
        timeout = httpx.Timeout(30.0, read=260.0)
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            if refs:
                for rel in refs:
                    url = _dashscope_upload_public_url(str(rel), client)
                    if url:
                        content.append({"image": url})

            body = {
                "model": model,
                "input": {
                    "messages": [
                        {"role": "user", "content": content}
                    ]
                },
                "parameters": {
                    "n": 1,
                    "result_type": "single",
                    "aspect_ratio": _kling_aspect_ratio(target_w, target_h),
                    "resolution": "1k",
                },
            }

            submit = client.post(
                f"{base}/api/v1/services/aigc/image-generation/generation",
                headers=submit_headers,
                json=body,
            )
            submit.raise_for_status()
            task_id = str(((submit.json() or {}).get("output") or {}).get("task_id") or "").strip()
            if not task_id:
                return False

            deadline = time.monotonic() + 240.0
            while time.monotonic() < deadline:
                time.sleep(3.0)
                st = client.get(f"{base}/api/v1/tasks/{task_id}", headers=query_headers)
                st.raise_for_status()
                out = (st.json() or {}).get("output") or {}
                status = str(out.get("task_status") or "").upper()
                if status in ("SUCCEEDED", "SUCCESS"):
                    choices = out.get("choices") or []
                    url = ""
                    for ch in choices:
                        msg = ch.get("message") or {}
                        content = msg.get("content") or []
                        if isinstance(content, list) and content:
                            url = str((content[0] or {}).get("image") or "").strip()
                            if url:
                                break
                    if not url:
                        return False
                    img_resp = client.get(url)
                    img_resp.raise_for_status()
                    img = Image.open(BytesIO(img_resp.content)).convert("RGB")
                    _save_provider_image(img, dest, shot=shot, target_w=target_w, target_h=target_h)
                    return dest.is_file() and dest.stat().st_size > 1000
                if status in ("FAILED", "CANCELED", "UNKNOWN"):
                    return False
            return False
    except Exception:
        return False


register("image", "jimeng", _consistent_http)
register("image", "wanx", _dashscope_image)
register("image", "dashscope", _dashscope_image)
register("image", "kling", _kling_image)
register("image", "kling-image", _kling_image)
register("image", "pollinations", _pollinations)
register("image", "flux", _pollinations)
register("image", "http", _pollinations)
# mock / none / off are intentionally unfilled → caller falls back.
register("image", "mock", _never)
register("image", "none", _never)
register("image", "off", _never)
