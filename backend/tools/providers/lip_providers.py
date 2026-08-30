"""Lip-sync adapters — quality-first cascade.

Provider contract: fn(video_or_scene, voice, dest, shot, duration) ->
source tag string, or "fallback".

Best-effort order (see drama_lip.try_generate_lip):
  1. latentsync  — ByteDance LatentSync via Replicate (highest fidelity)
  2. pixverse    — PixVerse lipsync on DashScope MaaS (production CN)
  3. musetalk / http — self-hosted gateway at LIP_API_URL
  4. mock        — only if LIP_ALLOW_MOCK=1 (waveform overlay; not real lips)
"""

from __future__ import annotations

import os
import shutil
import time
from pathlib import Path
from typing import Any

from config import config
from tools.providers.registry import register

# Sources that mean a real lip-synced video was produced (clip encode may burn in).
REAL_LIP_SOURCES = frozenset(
    {
        "latentsync",
        "pixverse",
        "pixverse-lipsync",
        "musetalk",
        "wav2lip",
        "http",
        "ai",
        "mock",  # degraded but still a lip layer file
    }
)


def _ffmpeg_bin() -> str:
    return os.getenv("FFMPEG_BIN", "ffmpeg")


def _mock(scene, voice, dest, shot, duration) -> str:
    from tools.drama_lip import _mock_lip

    if not shutil.which(_ffmpeg_bin()):
        return "fallback"
    return "mock" if _mock_lip(Path(scene), Path(voice), Path(dest), float(duration or 3)) else "fallback"


def _http(scene, voice, dest, shot, duration) -> str:
    from tools.drama_lip import _http_lip

    return "http" if _http_lip(Path(scene), Path(voice), Path(dest), shot, float(duration or 3)) else "fallback"


def _fallback(_scene, _voice, _dest, _shot, _duration) -> str:
    return "fallback"


def _as_path(value: Any) -> Path:
    return value if isinstance(value, Path) else Path(str(value))


def _upload_public_url(path: Path, client, *, mime: str | None = None) -> str:
    """Upload a local media file; return a public HTTPS URL.

    Prefer direct DashScope multipart upload (works for mp4/mp3). Fall back to
    workspace-relative helper. Retries file-URL lookup — audio often needs longer.
    """
    from tools.workspace import workspace_root

    path = _as_path(path)
    if not path.is_file():
        return ""
    if not mime:
        mime = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".mp4": "video/mp4",
            ".mov": "video/quicktime",
            ".webm": "video/webm",
            ".mp3": "audio/mpeg",
            ".wav": "audio/wav",
            ".m4a": "audio/mp4",
            ".aac": "audio/aac",
        }.get(path.suffix.lower(), "application/octet-stream")

    key = (getattr(config, "DASHSCOPE_API_KEY", "") or "").strip()
    dbase = (getattr(config, "DASHSCOPE_BASE_URL", "") or "https://dashscope.aliyuncs.com").rstrip("/")
    if not key:
        return ""

    headers = {"Authorization": f"Bearer {key}"}

    def _wait_file_url(fid: str) -> str:
        for _ in range(10):
            time.sleep(1.0)
            info = client.get(f"{dbase}/api/v1/files/{fid}", headers=headers)
            if info.status_code == 200:
                url = str(((info.json() or {}).get("data") or {}).get("url") or "").strip()
                if url:
                    return url
            elif info.status_code == 429:
                time.sleep(2.0)
        return ""

    # 1) Direct upload (proven for video + audio in lip debug)
    try:
        with path.open("rb") as f:
            data = f.read()
        upload = client.post(
            f"{dbase}/api/v1/files",
            headers=headers,
            files={"files": (path.name, data, mime)},
            data={"purpose": "chat-image-understanding"},
        )
        if upload.status_code == 200:
            uploaded = ((upload.json() or {}).get("data") or {}).get("uploaded_files") or []
            if uploaded:
                fid = str(uploaded[0].get("file_id") or "").strip()
                if fid:
                    url = _wait_file_url(fid)
                    if url:
                        return url
    except Exception:
        pass

    # 2) Workspace-relative helper
    try:
        from tools.providers.image_providers import _dashscope_upload_public_url

        rel = path.resolve().relative_to(workspace_root())
        url = _dashscope_upload_public_url(str(rel).replace("\\", "/"), client, mime=mime)
        if url:
            return url
    except Exception:
        pass

    return ""


def _pixverse_lip(scene, voice, dest, shot, duration) -> str:
    """PixVerse 对口型（DashScope MaaS）— 官方 media[] 协议.

    输入必须是含人脸的 **视频** + 配音音频。静图会由 drama_lip 先做成 lip_base。
    """
    import httpx

    from tools.drama_video import ffmpeg_available

    key = (getattr(config, "DASHSCOPE_API_KEY", "") or "").strip()
    maas = (getattr(config, "DASHSCOPE_MAAS_BASE_URL", "") or "").strip()
    if not key or not maas:
        return "fallback"

    model = (getattr(config, "PIXVERSE_LIP_MODEL", "") or "pixverse/pixverse-lipsync").strip()
    base = maas.rstrip("/")
    video = _as_path(scene)
    audio = _as_path(voice)
    dest = _as_path(dest)

    if not video.is_file() or video.suffix.lower() not in (".mp4", ".mov", ".webm"):
        if isinstance(shot, dict):
            shot["lip_error"] = f"pixverse: need face video, got {video}"
        return "fallback"
    if not audio.is_file():
        if isinstance(shot, dict):
            shot["lip_error"] = f"pixverse: missing audio {audio}"
        return "fallback"

    submit_headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "X-DashScope-Async": "enable",
    }
    query_headers = {"Authorization": f"Bearer {key}"}

    try:
        with httpx.Client(timeout=180.0, follow_redirects=True) as client:
            video_url = _upload_public_url(video, client, mime="video/mp4")
            if not video_url:
                if isinstance(shot, dict):
                    shot["lip_error"] = "pixverse: video upload failed (DashScope files API)"
                return "fallback"
            audio_mime = {
                ".mp3": "audio/mpeg",
                ".wav": "audio/wav",
                ".m4a": "audio/mp4",
                ".aac": "audio/aac",
            }.get(audio.suffix.lower(), "audio/mpeg")
            audio_url = _upload_public_url(audio, client, mime=audio_mime)
            # mp3 有时拿不到公网 URL：转 wav 再传（PixVerse 支持 wav）
            if not audio_url and audio.suffix.lower() == ".mp3":
                wav = audio.with_suffix(".lipupload.wav")
                try:
                    from tools.drama_video import _run_ffmpeg

                    _run_ffmpeg(
                        ["-y", "-i", str(audio), "-ac", "1", "-ar", "24000", str(wav)],
                        timeout=60,
                    )
                    if wav.is_file() and wav.stat().st_size > 80:
                        audio_url = _upload_public_url(wav, client, mime="audio/wav")
                except Exception:
                    audio_url = ""
                finally:
                    try:
                        if wav.exists():
                            wav.unlink()
                    except OSError:
                        pass
            if not audio_url:
                if isinstance(shot, dict):
                    shot["lip_error"] = "pixverse: audio upload failed (DashScope files API)"
                return "fallback"

            # 官方契约：media 为 [{type, url}, ...]；无 watermark 以保成片干净
            body = {
                "model": model,
                "input": {
                    "media": [
                        {"type": "video_url", "url": video_url},
                        {"type": "audio_url", "url": audio_url},
                    ]
                },
                "parameters": {"watermark": False},
            }
            r = client.post(
                f"{base}/api/v1/services/aigc/video-generation/video-synthesis",
                headers=submit_headers,
                json=body,
            )
            r.raise_for_status()
            tid = str(((r.json() or {}).get("output") or {}).get("task_id") or "").strip()
            if not tid:
                if isinstance(shot, dict):
                    shot["lip_error"] = f"pixverse: no task_id · {r.text[:300]}"
                return "fallback"

            # 口型任务常需数分钟；给足轮询时间
            deadline = time.monotonic() + float(getattr(config, "LIP_POLL_TIMEOUT", 480) or 480)
            while time.monotonic() < deadline:
                time.sleep(8.0)
                st = client.get(f"{base}/api/v1/tasks/{tid}", headers=query_headers)
                st.raise_for_status()
                out = (st.json() or {}).get("output") or {}
                status = str(out.get("task_status") or "").upper()
                if status in ("SUCCEEDED", "SUCCESS"):
                    out_url = str(out.get("video_url") or "").strip()
                    if not out_url:
                        if isinstance(shot, dict):
                            shot["lip_error"] = "pixverse: succeeded but empty video_url"
                        return "fallback"
                    v = client.get(out_url)
                    v.raise_for_status()
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_bytes(v.content)
                    if isinstance(shot, dict):
                        shot.pop("lip_error", None)
                    return "pixverse" if (dest.is_file() and dest.stat().st_size > 1000) else "fallback"
                if status in ("FAILED", "CANCELED", "UNKNOWN"):
                    if isinstance(shot, dict):
                        shot["lip_error"] = (
                            f"pixverse: {status} · {out.get('code') or ''} {out.get('message') or ''}"
                        ).strip()
                    return "fallback"
            if isinstance(shot, dict):
                shot["lip_error"] = "pixverse: poll timeout"
            return "fallback"
    except Exception as e:
        # Keep the last error on the shot for UI/debug (silent fallback was hiding root cause).
        try:
            if isinstance(shot, dict):
                shot["lip_error"] = f"pixverse: {type(e).__name__}: {e}"
        except Exception:
            pass
        if ffmpeg_available() and (getattr(config, "LIP_API_URL", "") or "").strip():
            return _http(scene, voice, dest, shot, duration)
        return "fallback"


def _replicate_file_uri(path: Path, client, token: str) -> str:
    """Upload local file to Replicate Files API; return serving URL."""
    path = _as_path(path)
    with path.open("rb") as f:
        resp = client.post(
            "https://api.replicate.com/v1/files",
            headers={"Authorization": f"Bearer {token}"},
            files={"content": (path.name, f)},
        )
    resp.raise_for_status()
    data = resp.json() or {}
    urls = data.get("urls") if isinstance(data.get("urls"), dict) else {}
    return str(urls.get("get") or data.get("url") or "").strip()


def _latentsync_lip(scene, voice, dest, shot, duration) -> str:
    """ByteDance LatentSync via Replicate — best open-source fidelity (512-class).

    Needs REPLICATE_API_TOKEN. Uses high inference_steps for max quality.
    Input must be video + audio (same as PixVerse).
    """
    import httpx

    token = (getattr(config, "REPLICATE_API_TOKEN", "") or os.getenv("REPLICATE_API_TOKEN") or "").strip()
    if not token:
        return "fallback"

    video = _as_path(scene)
    audio = _as_path(voice)
    dest = _as_path(dest)
    if not video.is_file() or video.suffix.lower() not in (".mp4", ".mov", ".webm"):
        return "fallback"
    if not audio.is_file():
        return "fallback"

    model = (getattr(config, "REPLICATE_LIP_MODEL", "") or "bytedance/latentsync").strip()
    # Quality knobs — user asked for best; bias toward fidelity over speed.
    try:
        steps = int(getattr(config, "LIP_INFERENCE_STEPS", 30) or 30)
    except (TypeError, ValueError):
        steps = 30
    steps = max(20, min(50, steps))
    try:
        guidance = float(getattr(config, "LIP_GUIDANCE_SCALE", 1.5) or 1.5)
    except (TypeError, ValueError):
        guidance = 1.5

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Prefer": "wait",
    }

    try:
        with httpx.Client(timeout=600.0, follow_redirects=True) as client:
            # Prefer public URLs (DashScope) when available — faster than Replicate upload.
            video_url = _upload_public_url(video, client, mime="video/mp4")
            audio_url = _upload_public_url(
                audio,
                client,
                mime="audio/mpeg" if audio.suffix.lower() == ".mp3" else "audio/wav",
            )
            if not video_url:
                video_url = _replicate_file_uri(video, client, token)
            if not audio_url:
                audio_url = _replicate_file_uri(audio, client, token)
            if not video_url or not audio_url:
                return "fallback"

            # Official models.create-style endpoint
            create = client.post(
                f"https://api.replicate.com/v1/models/{model}/predictions",
                headers=headers,
                json={
                    "input": {
                        "video": video_url,
                        "audio": audio_url,
                        "guidance_scale": guidance,
                        "inference_steps": steps,
                        "seed": int(shot.get("n") or 0) or 1247,
                    }
                },
            )
            # Some accounts need versioned predictions — fall back
            if create.status_code >= 400:
                create = client.post(
                    "https://api.replicate.com/v1/predictions",
                    headers={**headers, "Prefer": "wait"},
                    json={
                        "version": (getattr(config, "REPLICATE_LIP_VERSION", "") or "").strip() or None,
                        "input": {
                            "video": video_url,
                            "audio": audio_url,
                            "guidance_scale": guidance,
                            "inference_steps": steps,
                            "seed": int(shot.get("n") or 0) or 1247,
                        },
                    },
                )
                # Drop null version key
                if create.status_code >= 400 and not (getattr(config, "REPLICATE_LIP_VERSION", "") or "").strip():
                    return "fallback"

            create.raise_for_status()
            pred = create.json() or {}
            # Prefer wait response; otherwise poll
            deadline = time.monotonic() + float(getattr(config, "LIP_POLL_TIMEOUT", 600) or 600)
            while time.monotonic() < deadline:
                status = str(pred.get("status") or "").lower()
                if status == "succeeded":
                    out = pred.get("output")
                    out_url = out if isinstance(out, str) else (out[0] if isinstance(out, list) and out else "")
                    out_url = str(out_url or "").strip()
                    if not out_url:
                        return "fallback"
                    v = client.get(out_url)
                    v.raise_for_status()
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_bytes(v.content)
                    return "latentsync" if (dest.is_file() and dest.stat().st_size > 1000) else "fallback"
                if status in ("failed", "canceled", "cancelled"):
                    return "fallback"
                time.sleep(5.0)
                get_url = str((pred.get("urls") or {}).get("get") or "")
                if not get_url:
                    pid = str(pred.get("id") or "").strip()
                    if not pid:
                        return "fallback"
                    get_url = f"https://api.replicate.com/v1/predictions/{pid}"
                st = client.get(get_url, headers={"Authorization": f"Bearer {token}"})
                st.raise_for_status()
                pred = st.json() or {}
            return "fallback"
    except Exception:
        return "fallback"


# Register adapters
for pid in ("http", "api", "musetalk", "wav2lip"):
    register("lip", pid, _http)
for pid in ("pixverse", "pixverse-lipsync"):
    register("lip", pid, _pixverse_lip)
for pid in ("latentsync", "latent-sync", "replicate-lip"):
    register("lip", pid, _latentsync_lip)
for pid in ("none", "off", "fail"):
    register("lip", pid, _fallback)
register("lip", "mock", _mock)
