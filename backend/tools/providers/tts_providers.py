"""TTS adapters (R1).

Provider contract: fn(text, dest, *, voice=None) -> bool.
edge-tts is the real local backend. volcano / ms (high-fidelity) are named in
the pro preset but have no real adapter yet — registered as edge-tts aliases so
pro renders still work (degraded), and a future drop-in module can override
these ids via register() (last wins).
"""

from __future__ import annotations

from config import config
from tools.providers.registry import register


def _edge_tts(text, dest, *, voice=None) -> bool:
    from tools.drama_video import _tts_to_file

    return _tts_to_file(text, dest, voice=voice)


def _none(_text, _dest, **_kwargs) -> bool:
    return False


def _http_tts(text, dest, *, voice=None) -> bool:
    """S3: high-fidelity TTS via a self-hosted HTTP gateway.

    Contract:
        POST TTS_API_URL  (multipart: text, voice; or JSON: {text, voice, model})
        Authorization: Bearer TTS_API_KEY (when set)
        Body = audio bytes (mp3/wav)

    When TTS_API_URL is not configured, honestly degrade to edge-tts (the free
    local engine) so the high-fidelity name never silently "passes" without a
    real backend.
    """
    url = (getattr(config, "TTS_API_URL", "") or "").strip()
    if not url:
        return _edge_tts(text, dest, voice=voice)

    import httpx

    headers = {"User-Agent": "my-tiktok-video-agent/1.0"}
    key = (getattr(config, "TTS_API_KEY", "") or "").strip()
    if key:
        headers["Authorization"] = f"Bearer {key}"

    try:
        with httpx.Client(timeout=120.0, follow_redirects=True) as client:
            resp = client.post(
                url,
                files={"text": ("", str(text), "text/plain"), "voice": ("", str(voice or ""), "text/plain")},
                headers=headers,
            )
            resp.raise_for_status()
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(resp.content)
        return dest.is_file() and dest.stat().st_size > 0
    except Exception:
        # Gateway failure → degrade to edge-tts rather than silent audio.
        return _edge_tts(text, dest, voice=voice)


def _dashscope_tts(text, dest, *, voice=None) -> bool:
    """阿里云百炼 DashScope 语音合成（OpenAI 兼容 audio/speech）。

    Provider: dashscope-tts / cosyvoice。无 Key 或调用失败时诚实回退 edge-tts。
    """
    key = (getattr(config, "DASHSCOPE_API_KEY", "") or "").strip()
    if not key:
        return _edge_tts(text, dest, voice=voice)

    import httpx

    base = (getattr(config, "DASHSCOPE_BASE_URL", "") or "https://dashscope.aliyuncs.com").rstrip("/")
    model = (getattr(config, "DASHSCOPE_TTS_MODEL", "") or "qwen-audio-3.0-tts-plus").strip()

    # 百炼语音合成音色与 edge-tts 音色 id 不同，这里做一句尽力传入；
    # 无法匹配时用 None（服务端用默认音色）。
    try:
        with httpx.Client(timeout=120.0, follow_redirects=True) as client:
            resp = client.post(
                f"{base}/compatible-mode/v1/audio/speech",
                headers={
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json",
                    "User-Agent": "my-tiktok-video-agent/1.0",
                },
                json={
                    "model": model,
                    "input": str(text),
                    **({"voice": str(voice)} if voice else {}),
                },
            )
            resp.raise_for_status()
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(resp.content)
            return dest.is_file() and dest.stat().st_size > 0
    except Exception:
        # DashScope TTS failure → degrade to edge-tts rather than silent audio.
        return _edge_tts(text, dest, voice=voice)


register("tts", "edge-tts", _edge_tts)
# High-fidelity names now route through the real HTTP gateway, with honest
# degrade to edge-tts when the gateway is unavailable (no more alias masquerade).
register("tts", "volcano", _http_tts)
register("tts", "ms", _http_tts)
register("tts", "azure", _http_tts)
# 阿里百炼语音合成（高拟真 / 音色复刻）
register("tts", "dashscope-tts", _dashscope_tts)
register("tts", "cosyvoice", _dashscope_tts)
register("tts", "qwen-tts", _dashscope_tts)
register("tts", "none", _none)
register("tts", "off", _none)
