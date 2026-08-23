"""I2V motion adapters (R1).

Provider contract: fn(scene, dest, shot, seconds) -> "ai" | "none".
"none" signals the caller to fall back to Ken Burns still motion.
"""

from __future__ import annotations

from config import config
from tools.providers.registry import register


def _mock(scene, dest, shot, seconds) -> str:
    from tools.drama_i2v import _provider_mock_ai

    return "ai" if _provider_mock_ai(scene, dest, shot, seconds) else "none"


def _fail(_scene, _dest, _shot, _seconds) -> str:
    return "none"


def _http(scene, dest, shot, seconds) -> str:
    from tools.drama_i2v import _provider_http

    return "ai" if _provider_http(scene, dest, shot, seconds) else "none"


def _pollinations(scene, dest, shot, seconds) -> str:
    from tools.drama_i2v import _provider_pollinations

    return "ai" if _provider_pollinations(scene, dest, shot, seconds) else "none"


register("i2v", "mock", _mock)
register("i2v", "mock_ai", _mock)
register("i2v", "fail", _fail)
register("i2v", "http", _http)
register("i2v", "api", _http)
register("i2v", "kling", _http)
register("i2v", "hailuo", _http)
def _dashscope_i2v(scene, dest, shot, seconds) -> str:
    """阿里云百炼 DashScope 通义万相图生视频（异步提交→轮询→下载）。

    Provider: wanx-video / dashscope-i2v。失败返回 "none"（调用方回退 Ken Burns）。
    """
    import time

    import httpx

    key = (getattr(config, "DASHSCOPE_API_KEY", "") or "").strip()
    if not key:  # 未配置 Key → 诚实回退
        return "none"

    base = (getattr(config, "DASHSCOPE_BASE_URL", "") or "https://dashscope.aliyuncs.com").rstrip("/")
    model = (getattr(config, "DASHSCOPE_I2V_MODEL", "") or "wanx2.1-i2v-turbo").strip()

    # 运动提示词复用 drama_i2v 的能力（含角色一致性描述）。
    from tools.drama_i2v import _motion_prompt

    prompt = _motion_prompt(shot)
    headers = {
        "Authorization": f"Bearer {key}",
        "X-DashScope-Async": "enable",
        "User-Agent": "my-tiktok-video-agent/1.0",
    }

    try:
        # 1) 先上传本地关键帧到百炼，换取可访问 URL。
        upload_headers = {
            "Authorization": f"Bearer {key}",
            "X-DashScope-OssResourceResolve": "enable",
            "User-Agent": "my-tiktok-video-agent/1.0",
        }
        with httpx.Client(timeout=180.0, follow_redirects=True) as client:
            up = client.post(
                f"{base}/api/v1/uploads",
                headers=upload_headers,
                files={"file": (scene.name, scene.read_bytes(), "image/png")},
            )
            up.raise_for_status()
            up_data = up.json()
            img_url = ""
            url_candidates = [up_data, (up_data.get("data") or {})]
            for cand in url_candidates:
                if isinstance(cand, dict):
                    img_url = str(cand.get("url") or cand.get("uploaded_url") or "").strip()
                    if not img_url and isinstance(cand.get("file"), dict):
                        img_url = str(cand["file"].get("url") or "").strip()
                    if img_url:
                        break
            if not img_url:
                return "none"

            # 2) 提交图生视频任务（异步）。
            body = {
                "model": model,
                "input": {
                    "img_url": img_url,
                    "prompt": prompt,
                },
                "parameters": {
                    "duration": float(seconds),
                    "resolution": "720P",
                },
            }
            submit = client.post(
                f"{base}/api/v1/services/aigc/video-generation/video-synthesis",
                headers={**headers, "Content-Type": "application/json"},
                json=body,
            )
            submit.raise_for_status()
            payload = submit.json()
            task_id = str(
                ((payload.get("output") or {}).get("task_id"))
                or ((payload.get("data") or {}).get("task_id"))
                or ""
            ).strip()
            if not task_id:
                return "none"

            # 3) 轮询任务直到完成。
            deadline = time.monotonic() + 300.0
            while time.monotonic() < deadline:
                time.sleep(3.0)
                st = client.get(f"{base}/api/v1/tasks/{task_id}", headers=headers)
                st.raise_for_status()
                info = st.json()
                out = info.get("output") or {}
                status = str(out.get("task_status") or "").upper()
                if status in ("SUCCEEDED", "SUCCESS"):
                    video_url = str((out.get("video_url") or "").strip())
                    if not video_url and isinstance(out.get("results"), list) and out.get("results"):
                        video_url = str(out["results"][0].get("url") or "").strip()
                    if not video_url:
                        return "none"
                    v = client.get(video_url)
                    v.raise_for_status()
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_bytes(v.content)
                    return "ai" if (dest.is_file() and dest.stat().st_size > 1000) else "none"
                if status in ("FAILED", "CANCELED", "UNKNOWN"):
                    return "none"
            return "none"
    except Exception:
        return "none"


def _kling_video(scene, dest, shot, seconds) -> str:
    """可灵 Kling 首帧图生视频（走专属 MaaS 端点）。

    协议（官方）：
      - 上传场景关键帧到百炼，取公网 URL；
      - 提交 POST video-generation/video-synthesis，omni 模型，
        input: {prompt, media:[{type:first_frame, url}]}；
      - 查询 GET /api/v1/tasks/{id}，只带 Authorization（不带异步头）；
      - 结果 output.video_url。

    首帧图失败时回退到纯文生视频（kling-v3-video-generation），再失败返回 "none"。
    """
    import time

    import httpx

    key = (getattr(config, "DASHSCOPE_API_KEY", "") or "").strip()
    maas = (getattr(config, "DASHSCOPE_MAAS_BASE_URL", "") or "").strip()
    if not key or not maas:
        return "none"

    base = maas.rstrip("/")
    omni_model = (getattr(config, "KLING_OMNI_VIDEO_MODEL", "") or "kling/kling-v3-omni-video-generation").strip()
    t2v_model = (getattr(config, "KLING_VIDEO_MODEL", "") or "kling/kling-v3-video-generation").strip()

    from tools.drama_i2v import _motion_prompt
    from tools.providers.image_providers import _dashscope_upload_public_url

    prompt = _motion_prompt(shot)
    duration = max(1, min(int(round(float(seconds))), 10))

    submit_headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "X-DashScope-Async": "enable",
    }
    query_headers = {"Authorization": f"Bearer {key}"}

    def _submit_and_fetch(client, body) -> str:
        submit = client.post(
            f"{base}/api/v1/services/aigc/video-generation/video-synthesis",
            headers=submit_headers,
            json=body,
        )
        submit.raise_for_status()
        task_id = str(((submit.json() or {}).get("output") or {}).get("task_id") or "").strip()
        if not task_id:
            return "none"

        deadline = time.monotonic() + 420.0
        while time.monotonic() < deadline:
            time.sleep(10.0)
            st = client.get(f"{base}/api/v1/tasks/{task_id}", headers=query_headers)
            st.raise_for_status()
            out = (st.json() or {}).get("output") or {}
            status = str(out.get("task_status") or "").upper()
            if status in ("SUCCEEDED", "SUCCESS"):
                video_url = str(out.get("video_url") or "").strip()
                if not video_url:
                    return "none"
                v = client.get(video_url)
                v.raise_for_status()
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(v.content)
                return "ai" if (dest.is_file() and dest.stat().st_size > 1000) else "none"
            if status in ("FAILED", "CANCELED", "UNKNOWN"):
                return "none"
        return "none"

    try:
        with httpx.Client(timeout=120.0, follow_redirects=True) as client:
            # 1) 尝试首帧图生视频（上传 scene 取 URL）
            scene_url = _dashscope_upload_public_url(str(scene), client)
            if scene_url:
                first_frame_body = {
                    "model": omni_model,
                    "input": {
                        "prompt": prompt,
                        "media": [{"type": "first_frame", "url": scene_url}],
                    },
                    "parameters": {
                        "mode": "std",
                        "duration": duration,
                        "audio": False,
                        "watermark": True,
                    },
                }
                result = _submit_and_fetch(client, first_frame_body)
                if result == "ai":
                    return "ai"

            # 2) 回退纯文生视频
            t2v_body = {
                "model": t2v_model,
                "input": {"prompt": prompt},
                "parameters": {
                    "mode": "std",
                    "aspect_ratio": "9:16",
                    "duration": duration,
                    "audio": False,
                    "watermark": True,
                },
            }
            return _submit_and_fetch(client, t2v_body)
    except Exception:
        return "none"


register("i2v", "pollinations", _pollinations)
register("i2v", "wanx-video", _dashscope_i2v)
register("i2v", "dashscope-i2v", _dashscope_i2v)
register("i2v", "kling-video", _kling_video)
register("i2v", "kling-maas", _kling_video)
register("i2v", "none", _fail)
register("i2v", "off", _fail)
register("i2v", "l0", _mock)
