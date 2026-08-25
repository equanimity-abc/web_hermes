"""Lip-sync adapters (R1).

Provider contract: fn(scene, voice, dest, shot, duration) ->
"mock" | "http" | "fallback".
"""

from __future__ import annotations

import shutil

from config import config
from tools.providers.registry import register


def _mock(scene, voice, dest, shot, duration) -> str:
    from tools.drama_lip import _mock_lip

    if not shutil.which("ffmpeg"):
        return "fallback"
    return "mock" if _mock_lip(scene, voice, dest, duration) else "fallback"


def _http(scene, voice, dest, shot, duration) -> str:
    from tools.drama_lip import _http_lip

    return "http" if _http_lip(scene, voice, dest, shot, duration) else "fallback"


def _fallback(_scene, _voice, _dest, _shot, _duration) -> str:
    return "fallback"


def _pixverse_lip(scene, voice, dest, shot, duration) -> str:
    """PixVerse 对口型（走 MaaS video-synthesis，协议已实测）。

    - 上传运动视频(scene 即 motion mp4) 与配音音频到百炼换公网 URL；
    - 提交 pixverse/pixverse-lipsync，input.media 需 video_url；
    - 失败回退到通用 http 适配器，再回退 mock。
    """
    import time

    import httpx

    from tools.drama_video import ffmpeg_available
    from tools.providers.image_providers import _dashscope_upload_public_url

    key = (getattr(config, "DASHSCOPE_API_KEY", "") or "").strip()
    maas = (getattr(config, "DASHSCOPE_MAAS_BASE_URL", "") or "").strip()
    if not key or not maas:
        return _mock(scene, voice, dest, shot, duration) if ffmpeg_available() else "fallback"

    model = (getattr(config, "PIXVERSE_LIP_MODEL", "") or "pixverse/pixverse-lipsync").strip()
    base = maas.rstrip("/")

    submit_headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "X-DashScope-Async": "enable",
    }
    query_headers = {"Authorization": f"Bearer {key}"}

    try:
        with httpx.Client(timeout=120.0, follow_redirects=True) as client:
            # 视频：scene 实际是上一层的 motion mp4
            is_video = str(scene).endswith(".mp4")
            video_url = _dashscope_upload_public_url(str(scene), client, mime="video/mp4") if is_video else ""
            if not video_url:
                return _http(scene, voice, dest, shot, duration) if ffmpeg_available() else "fallback"
            # 音频
            is_audio = str(voice).endswith((".mp3", ".wav"))
            audio_url = _dashscope_upload_public_url(str(voice), client, mime="audio/mpeg") if is_audio else ""

            body = {
                "model": model,
                "input": {
                    "media": {
                        "video_url": video_url,
                        **({"audio_url": audio_url} if audio_url else {}),
                    }
                },
                "parameters": {"duration": int(round(float(duration or 3)))},
            }
            r = client.post(
                f"{base}/api/v1/services/aigc/video-generation/video-synthesis",
                headers=submit_headers,
                json=body,
            )
            r.raise_for_status()
            tid = str(((r.json() or {}).get("output") or {}).get("task_id") or "").strip()
            if not tid:
                return "fallback"

            deadline = time.monotonic() + 240.0
            while time.monotonic() < deadline:
                time.sleep(5.0)
                st = client.get(f"{base}/api/v1/tasks/{tid}", headers=query_headers)
                st.raise_for_status()
                out = (st.json() or {}).get("output") or {}
                status = str(out.get("task_status") or "").upper()
                if status in ("SUCCEEDED", "SUCCESS"):
                    video_url = str(out.get("video_url") or "").strip()
                    if not video_url:
                        return "fallback"
                    v = client.get(video_url)
                    v.raise_for_status()
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_bytes(v.content)
                    return "http" if (dest.is_file() and dest.stat().st_size > 1000) else "fallback"
                if status in ("FAILED", "CANCELED", "UNKNOWN"):
                    return "fallback"
            return "fallback"
    except Exception:
        return _http(scene, voice, dest, shot, duration) if ffmpeg_available() else "fallback"


# musetalk / wav2lip are real endpoints via the same http adapter today.
for pid in ("http", "api", "musetalk", "wav2lip"):
    register("lip", pid, _http)
for pid in ("pixverse", "pixverse-lipsync"):
    register("lip", pid, _pixverse_lip)
for pid in ("none", "off", "fail"):
    register("lip", pid, _fallback)
register("lip", "mock", _mock)