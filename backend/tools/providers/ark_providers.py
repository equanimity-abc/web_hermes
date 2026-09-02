"""火山方舟 Ark adapters — Seedream 生图 / Seedance 视频 / Seed Audio 配音。"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

import httpx

from config import config
from tools.providers.registry import register

log = logging.getLogger("drama.ark")


def _ark_key() -> str:
    return str(getattr(config, "ARK_API_KEY", "") or "").strip()


def _ark_base() -> str:
    return str(
        getattr(config, "ARK_BASE_URL", "") or "https://ark.cn-beijing.volces.com/api/v3"
    ).rstrip("/")


def _ark_headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {_ark_key()}",
        "Content-Type": "application/json",
        "User-Agent": "my-tiktok-video-agent/1.0",
    }


def _download(url: str, dest: Path) -> bool:
    try:
        with httpx.Client(timeout=180.0, follow_redirects=True) as client:
            resp = client.get(url)
            resp.raise_for_status()
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(resp.content)
        return dest.is_file() and dest.stat().st_size > 0
    except Exception as e:
        log.warning("ark download failed: %s", e)
        return False


def _ark_image(
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
    """Seedream 文生图 → PNG."""
    key = _ark_key()
    if not key:
        return False

    from io import BytesIO

    from PIL import Image

    model = str(getattr(config, "ARK_IMAGE_MODEL", "") or "doubao-seedream-5-0-pro-260628").strip()
    # Prefer portrait for drama; Ark size strings like 2K / 1024x1792
    w = int(width or 1080)
    h = int(height or 1920)
    size = f"{w}x{h}" if w and h else "1080x1920"

    body: dict[str, Any] = {
        "model": model,
        "prompt": str(prompt),
        "size": size,
        "response_format": "url",
        "n": 1,
    }
    if seed:
        body["seed"] = int(seed) % 2147483647

    try:
        with httpx.Client(timeout=180.0, follow_redirects=True) as client:
            resp = client.post(
                f"{_ark_base()}/images/generations",
                headers=_ark_headers(),
                json=body,
            )
            resp.raise_for_status()
            data = resp.json()
            items = data.get("data") or []
            if not items:
                log.warning("ark image empty response: %s", data)
                return False
            item = items[0]
            url = item.get("url") or ""
            b64 = item.get("b64_json") or ""
            dest = Path(dest)
            dest.parent.mkdir(parents=True, exist_ok=True)
            if url:
                if not _download(url, dest):
                    return False
            elif b64:
                import base64

                dest.write_bytes(base64.b64decode(b64))
            else:
                return False

            # Normalize to target canvas for non-character_ref shots
            from tools.providers.image_providers import _is_character_ref_shot, _save_provider_image

            img = Image.open(dest).convert("RGB")
            tw = int(width or 1620)
            th = int(height or 2880)
            _save_provider_image(img, dest, shot=shot, target_w=tw, target_h=th)
            return dest.is_file() and dest.stat().st_size > 0
    except Exception as e:
        log.warning("ark image failed: %s", e)
        return False


def _ark_i2v(scene, dest, shot, seconds) -> str:
    """Seedance 图生视频（异步任务）。"""
    key = _ark_key()
    if not key:
        return "none"

    import base64

    from tools.drama_i2v import _motion_prompt

    model = str(getattr(config, "ARK_VIDEO_MODEL", "") or "doubao-seedance-2-5-260628").strip()
    prompt = _motion_prompt(shot)
    scene_path = Path(scene)
    if not scene_path.is_file():
        return "none"

    # Prefer data URL for first frame when public upload is unavailable.
    mime = "image/png" if scene_path.suffix.lower() == ".png" else "image/jpeg"
    b64 = base64.b64encode(scene_path.read_bytes()).decode("ascii")
    image_url = f"data:{mime};base64,{b64}"
    duration = max(2, min(int(round(float(seconds) or 5)), 12))

    body = {
        "model": model,
        "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": image_url}},
        ],
        "duration": duration,
    }

    try:
        with httpx.Client(timeout=300.0, follow_redirects=True) as client:
            submit = client.post(
                f"{_ark_base()}/contents/generations/tasks",
                headers=_ark_headers(),
                json=body,
            )
            submit.raise_for_status()
            job = submit.json()
            task_id = str(job.get("id") or job.get("task_id") or "").strip()
            if not task_id:
                # Some responses return result inline
                video_url = (
                    ((job.get("content") or {}) if isinstance(job.get("content"), dict) else {}).get("video_url")
                    or job.get("video_url")
                    or ""
                )
                if video_url and _download(video_url, Path(dest)):
                    return "ai"
                log.warning("ark i2v no task id: %s", job)
                return "none"

            deadline = time.monotonic() + float(getattr(config, "I2V_POLL_TIMEOUT", 300) or 300)
            while time.monotonic() < deadline:
                time.sleep(float(getattr(config, "I2V_POLL_INTERVAL", 2.0) or 2.0))
                poll = client.get(
                    f"{_ark_base()}/contents/generations/tasks/{task_id}",
                    headers=_ark_headers(),
                )
                poll.raise_for_status()
                info = poll.json()
                status = str(info.get("status") or info.get("task_status") or "").lower()
                if status in ("succeeded", "success", "completed", "done"):
                    content = info.get("content") if isinstance(info.get("content"), dict) else {}
                    video_url = (
                        (content or {}).get("video_url")
                        or info.get("video_url")
                        or ((info.get("result") or {}) if isinstance(info.get("result"), dict) else {}).get("video_url")
                        or ""
                    )
                    if video_url and _download(str(video_url), Path(dest)):
                        return "ai"
                    return "none"
                if status in ("failed", "error", "cancelled"):
                    log.warning("ark i2v task failed: %s", info)
                    return "none"
            log.warning("ark i2v timeout task=%s", task_id)
            return "none"
    except Exception as e:
        log.warning("ark i2v failed: %s", e)
        return "none"


def _ark_tts(text, dest, *, voice=None) -> bool:
    """Seed Audio TTS（OpenAI 兼容 audio/speech）。"""
    key = _ark_key()
    if not key:
        from tools.providers.tts_providers import _edge_tts

        return _edge_tts(text, dest, voice=voice)

    model = str(getattr(config, "ARK_AUDIO_MODEL", "") or "doubao-seed-audio-1-0").strip()
    body = {
        "model": model,
        "input": str(text),
        "voice": str(voice or "zh_female_vv_uranus_bigtts"),
        "response_format": "mp3",
    }
    try:
        with httpx.Client(timeout=120.0, follow_redirects=True) as client:
            resp = client.post(
                f"{_ark_base()}/audio/speech",
                headers=_ark_headers(),
                json=body,
            )
            resp.raise_for_status()
            dest = Path(dest)
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(resp.content)
        return dest.is_file() and dest.stat().st_size > 0
    except Exception as e:
        log.warning("ark tts failed: %s", e)
        from tools.providers.tts_providers import _edge_tts

        return _edge_tts(text, dest, voice=voice)


register("image", "ark", _ark_image)
register("image", "seedream", _ark_image)
register("image", "doubao-image", _ark_image)
register("i2v", "ark", _ark_i2v)
register("i2v", "seedance", _ark_i2v)
register("i2v", "doubao-video", _ark_i2v)
register("tts", "ark", _ark_tts)
register("tts", "seed-audio", _ark_tts)
register("tts", "doubao-audio", _ark_tts)
