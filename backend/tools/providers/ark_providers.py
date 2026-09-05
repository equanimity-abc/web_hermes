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


# Seedream 多参考融合过多会稀释身份，漫剧分镜默认最多 3 张定妆。
_MAX_SEEDREAM_REFS = 3


def _image_path_to_data_uri(path: Path, *, max_side: int = 1536) -> str | None:
    """本地图片 → JPEG data URI（压缩边长，避免 Seedream/Seedance 请求体过大）。"""
    import base64
    from io import BytesIO

    from PIL import Image

    if not path.is_file() or path.stat().st_size < 32:
        return None
    try:
        img = Image.open(path).convert("RGB")
        w, h = img.size
        long_side = max(w, h)
        if long_side > max_side:
            scale = max_side / float(long_side)
            img = img.resize(
                (max(1, int(w * scale)), max(1, int(h * scale))),
                Image.Resampling.LANCZOS,
            )
        buf = BytesIO()
        img.save(buf, format="JPEG", quality=90, optimize=True)
        b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        return f"data:image/jpeg;base64,{b64}"
    except Exception as e:
        log.warning("ark image encode failed (%s): %s", path, e)
        return None


def _local_ref_to_data_uri(rel: str, *, max_side: int = 1536) -> str | None:
    """把工作区内的定妆/参考图编成 Seedream ``image`` 可用的 data URI。"""
    from tools.workspace import resolve_safe

    rel = str(rel or "").strip().replace("\\", "/")
    if not rel:
        return None
    if rel.startswith(("http://", "https://", "data:image/")):
        return rel
    try:
        path = resolve_safe(rel)
    except ValueError:
        return None
    return _image_path_to_data_uri(path, max_side=max_side)


def _seedance_duration(seconds: float | int | None) -> int:
    """Seedance 2.x 要求整数秒且最短 4s（2.5: 4–30；2.0: 4–15）。

    管线 ``i2v_seconds`` 默认 2.5 → round 成 2/3，原逻辑会提交 duration=2 被 API 400。
    """
    try:
        raw = float(seconds if seconds is not None else 5)
    except (TypeError, ValueError):
        raw = 5.0
    sec = int(round(raw)) if raw > 0 else 5
    return max(4, min(sec, 12))


def _seedream_image_payload(refs: tuple[str, ...]) -> str | list[str] | None:
    """官方契约：单张 ``image=url``，多张 ``image=[url, ...]``（最多 10，我们限 3）。"""
    uris: list[str] = []
    for rel in refs:
        if len(uris) >= _MAX_SEEDREAM_REFS:
            break
        uri = _local_ref_to_data_uri(str(rel or ""))
        if uri:
            uris.append(uri)
    if not uris:
        return None
    if len(uris) == 1:
        return uris[0]
    return uris


def _prompt_with_identity_refs(prompt: str, *, ref_count: int) -> str:
    """参考图是「身份锚」，不是编辑底图——避免模型只做轻微改图。"""
    base = str(prompt or "").strip()
    if ref_count <= 0:
        return base
    if ref_count == 1:
        clause = (
            "参考图为角色定妆立绘：严格保持同一张脸、同一发型发色与同一套服装配饰；"
            "生成本镜全新构图、景别与姿势，不要复制定妆立绘的站姿与背景"
        )
    else:
        clause = (
            f"参考图共{ref_count}张定妆立绘：图1为身份锁（本镜说话人/主体），"
            "必须与图1同一张脸、同一发型与服装；"
            "图2起为同镜其它角色外形参考；"
            "生成本镜全新构图与姿势，不要复制定妆立绘构图"
        )
    if not base:
        return clause
    return f"{base}。{clause}"


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
    """Seedream 文生图 / 图生图（带定妆 ``image`` 参考）→ PNG。

    官方示例：
      - 单参考：``image="https://..."``
      - 多参考：``image=["url1", "url2"]``
    本地定妆无 data URI，免公网上传。
    """
    key = _ark_key()
    if not key:
        return False
    try:
        from tools.drama_parallel import acquire_lane

        acquire_lane("ark")
    except Exception:
        pass

    from PIL import Image

    model = str(getattr(config, "ARK_IMAGE_MODEL", "") or "doubao-seedream-5-0-pro-260628").strip()
    # Prefer portrait for drama; Ark size strings like 2K / 1024x1792
    w = int(width or 1080)
    h = int(height or 1920)
    size = f"{w}x{h}" if w and h else "1080x1920"

    image_payload = _seedream_image_payload(tuple(refs or ()))
    ref_count = (
        0
        if image_payload is None
        else (len(image_payload) if isinstance(image_payload, list) else 1)
    )
    final_prompt = _prompt_with_identity_refs(str(prompt), ref_count=ref_count)

    body: dict[str, Any] = {
        "model": model,
        "prompt": final_prompt,
        # 官方图生图示例用 size="2K"；带参考图时跟官方走，像素串易削弱锁脸。
        "size": "2K" if image_payload is not None else size,
        "response_format": "url",
        "output_format": "png",
        "watermark": False,
        "n": 1,
    }
    if image_payload is not None:
        body["image"] = image_payload
        log.info("ark seedream i2i refs=%s size=2K", ref_count)
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
        if isinstance(shot, dict):
            shot["i2v_error"] = "missing_ARK_API_KEY"
        return "none"

    try:
        from tools.drama_parallel import acquire_lane

        acquire_lane("ark")
    except Exception:
        pass

    from tools.drama_i2v import _motion_prompt

    model = str(getattr(config, "ARK_VIDEO_MODEL", "") or "doubao-seedance-2-5-260628").strip()
    prompt = _motion_prompt(shot)
    scene_path = Path(scene)
    if not scene_path.is_file():
        if isinstance(shot, dict):
            shot["i2v_error"] = "missing_scene"
        return "none"

    # 与 Seedream refs 相同：JPEG 压缩，避免 4K PNG base64 撑爆 / 超时。
    image_url = _image_path_to_data_uri(scene_path, max_side=1536)
    if not image_url:
        if isinstance(shot, dict):
            shot["i2v_error"] = "scene_encode_failed"
        return "none"
    duration = _seedance_duration(seconds)

    body = {
        "model": model,
        "content": [
            {"type": "text", "text": prompt},
            {
                "type": "image_url",
                "image_url": {"url": image_url},
                "role": "first_frame",
            },
        ],
        "duration": duration,
        # Seedance 2.5 首帧/首尾帧任务强制 ratio=adaptive，传 9:16 会 400。
        "ratio": "adaptive",
        "generate_audio": False,
    }

    def _remember_error(msg: str) -> None:
        if isinstance(shot, dict):
            shot["i2v_error"] = str(msg or "")[:240]

    def _format_http_error(resp: httpx.Response) -> str:
        text = (resp.text or "").strip()
        try:
            data = resp.json()
            err = data.get("error") if isinstance(data, dict) else None
            if isinstance(err, dict):
                code = err.get("code") or err.get("type") or ""
                message = err.get("message") or err.get("msg") or ""
                detail = f"{code}: {message}".strip(": ").strip()
                if detail:
                    return f"HTTP {resp.status_code}: {detail}"[:240]
            if isinstance(data, dict) and data.get("message"):
                return f"HTTP {resp.status_code}: {data.get('message')}"[:240]
        except Exception:
            pass
        return f"HTTP {resp.status_code}: {text[:200]}"

    try:
        with httpx.Client(timeout=300.0, follow_redirects=True) as client:
            submit = client.post(
                f"{_ark_base()}/contents/generations/tasks",
                headers=_ark_headers(),
                json=body,
            )
            if submit.status_code >= 400:
                _remember_error(_format_http_error(submit))
                log.warning("ark i2v submit failed: %s", submit.text[:500])
                return "none"
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
                    if isinstance(shot, dict):
                        shot.pop("i2v_error", None)
                    return "ai"
                log.warning("ark i2v no task id: %s", job)
                _remember_error("no_task_id")
                return "none"

            deadline = time.monotonic() + float(getattr(config, "I2V_POLL_TIMEOUT", 300) or 300)
            while time.monotonic() < deadline:
                time.sleep(float(getattr(config, "I2V_POLL_INTERVAL", 2.0) or 2.0))
                poll = client.get(
                    f"{_ark_base()}/contents/generations/tasks/{task_id}",
                    headers=_ark_headers(),
                )
                if poll.status_code >= 400:
                    _remember_error(_format_http_error(poll))
                    return "none"
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
                        if isinstance(shot, dict):
                            shot.pop("i2v_error", None)
                        return "ai"
                    _remember_error("succeeded_but_no_video_url")
                    return "none"
                if status in ("failed", "error", "cancelled"):
                    err = info.get("error") or info.get("message") or info
                    log.warning("ark i2v task failed: %s", info)
                    _remember_error(f"task_{status}: {err}"[:240])
                    return "none"
            log.warning("ark i2v timeout task=%s", task_id)
            _remember_error(f"timeout task={task_id}")
            return "none"
    except Exception as e:
        log.warning("ark i2v failed: %s", e)
        # 保留已解析的 HTTP 业务错误，不被通用异常文案覆盖。
        if isinstance(shot, dict) and not shot.get("i2v_error"):
            _remember_error(str(e))
        return "none"


def _ark_tts(text, dest, *, voice=None) -> bool:
    """Seed Audio TTS（OpenAI 兼容 audio/speech）。"""
    key = _ark_key()
    if not key:
        from tools.providers.tts_providers import _edge_tts

        return _edge_tts(text, dest, voice=voice)

    try:
        from tools.drama_parallel import acquire_lane
        acquire_lane("ark")
    except Exception:
        pass

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
