"""Image-to-video motion for locked keyframes (D8).

Tries a configured I2V provider for ~2–3s motion from scene.png. On failure,
the caller falls back to Ken Burns zoompan on the still (see drama_video).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import urllib.parse
from pathlib import Path
from typing import Any

from config import config
from tools.drama_shots import normalize_i2v_mode, shot_stem
from tools.workspace import resolve_safe

I2V_MODES = ("off", "auto", "on")
DEFAULT_SECONDS = 2.5
MIN_SECONDS = 1.5
MAX_SECONDS = 4.0


def motion_rel(slug: str, episode: int, n: int) -> str:
    return f"dramas/{slug}/videos/ep{episode:02d}/{shot_stem(n)}_motion.mp4"


def should_try_i2v(shot: dict[str, Any]) -> bool:
    mode = normalize_i2v_mode(shot.get("i2v"))
    if mode == "off":
        return False
    if mode == "on":
        return True
    locked = set(shot.get("locked") or [])
    return "scene" in locked or "shot" in locked


def i2v_seconds(shot: dict[str, Any] | None = None) -> float:
    raw = os.getenv("I2V_SECONDS")
    if shot and shot.get("i2v_seconds") is not None:
        raw = str(shot.get("i2v_seconds"))
    try:
        sec = float(raw if raw is not None else DEFAULT_SECONDS)
    except (TypeError, ValueError):
        sec = DEFAULT_SECONDS
    return max(MIN_SECONDS, min(sec, MAX_SECONDS))


def _ffmpeg_bin() -> str:
    return os.getenv("FFMPEG_BIN", "ffmpeg")


def _provider() -> str:
    return (config.I2V_PROVIDER or os.getenv("I2V_PROVIDER") or "none").strip().lower()


def _motion_prompt(shot: dict[str, Any]) -> str:
    scene = str(shot.get("画面") or "").strip()
    camera = str(shot.get("camera") or "punch_in")
    return (
        f"cinematic subtle motion, {camera}, vertical 9:16, "
        f"{scene or 'character portrait'}, gentle movement, no text"
    )


def _kenburns_motion_mp4(scene: Path, dest: Path, shot: dict[str, Any], seconds: float) -> None:
    """Local motion clip via zoompan — used as provider output or encode fallback reference."""
    from tools.drama_video import FPS, HEIGHT, WIDTH, ZOOM_H, ZOOM_W, _look_filters, _motion_expr

    frames = max(int(round(seconds * FPS)), FPS)
    motion = _motion_expr(shot, frames)
    look = _look_filters(shot)
    vf = (
        f"[0:v]scale={ZOOM_W}:{ZOOM_H}:force_original_aspect_ratio=increase,"
        f"crop={ZOOM_W}:{ZOOM_H},{motion},{look},fps={FPS},"
        f"scale={WIDTH}:{HEIGHT},format=yuv420p[vout]"
    )
    dest.parent.mkdir(parents=True, exist_ok=True)
    args = [
        _ffmpeg_bin(),
        "-y",
        "-framerate",
        str(FPS),
        "-loop",
        "1",
        "-i",
        str(scene),
        "-filter_complex",
        vf,
        "-map",
        "[vout]",
        "-t",
        f"{seconds:.2f}",
        "-r",
        str(FPS),
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        str(dest),
    ]
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    proc = subprocess.run(args, capture_output=True, text=True, timeout=180, creationflags=creationflags)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr or proc.stdout or "ffmpeg kenburns motion failed")
    if not dest.is_file() or dest.stat().st_size < 500:
        raise RuntimeError("motion mp4 未生成")


def _provider_mock_ai(scene: Path, dest: Path, shot: dict[str, Any], seconds: float) -> bool:
    _kenburns_motion_mp4(scene, dest, shot, seconds)
    return dest.is_file() and dest.stat().st_size > 500


def _provider_fail(_scene: Path, _dest: Path, _shot: dict[str, Any], _seconds: float) -> bool:
    return False


def _provider_http(scene: Path, dest: Path, shot: dict[str, Any], seconds: float) -> bool:
    url = (config.I2V_API_URL or os.getenv("I2V_API_URL") or "").strip()
    if not url:
        return False
    try:
        import httpx

        prompt = _motion_prompt(shot)
        with httpx.Client(timeout=120.0, follow_redirects=True) as client:
            with scene.open("rb") as fh:
                resp = client.post(
                    url,
                    files={"image": (scene.name, fh, "image/png")},
                    data={
                        "prompt": prompt,
                        "duration": str(seconds),
                        "model": config.I2V_MODEL or "default",
                    },
                    headers={"User-Agent": "my-tiktok-video-agent/0.8"},
                )
            resp.raise_for_status()
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(resp.content)
        return dest.is_file() and dest.stat().st_size > 1000
    except Exception:
        return False


def _provider_pollinations(scene: Path, dest: Path, shot: dict[str, Any], seconds: float) -> bool:
    """Best-effort remote I2V; returns False so caller uses still fallback when unavailable."""
    try:
        import httpx

        prompt = urllib.parse.quote(_motion_prompt(shot))
        seed = int(shot.get("n") or 1) * 131
        url = (
            "https://image.pollinations.ai/prompt/"
            f"{prompt}?width=768&height=1344&nologo=true&seed={seed}"
        )
        with httpx.Client(timeout=90.0, follow_redirects=True) as client:
            resp = client.get(url, headers={"User-Agent": "my-tiktok-video-agent/0.8"})
            resp.raise_for_status()
            if "image" not in str(resp.headers.get("content-type") or "").lower():
                return False
            tmp = dest.with_suffix(".png")
            tmp.write_bytes(resp.content)
            _kenburns_motion_mp4(tmp, dest, shot, seconds)
            try:
                tmp.unlink()
            except OSError:
                pass
        return dest.is_file() and dest.stat().st_size > 500
    except Exception:
        return False


def try_generate_i2v(
    scene: Path,
    dest: Path,
    shot: dict[str, Any],
    *,
    seconds: float | None = None,
) -> str:
    """Return i2v_source: ai | none (caller should still-image zoompan when none)."""
    if not scene.is_file():
        raise FileNotFoundError(f"缺少画面：{scene}")
    if not shutil.which(_ffmpeg_bin()):
        return "none"

    sec = i2v_seconds(shot) if seconds is None else max(MIN_SECONDS, min(float(seconds), MAX_SECONDS))
    provider = _provider()
    ok = False
    if provider in ("mock", "mock_ai"):
        ok = _provider_mock_ai(scene, dest, shot, sec)
    elif provider == "fail":
        ok = _provider_fail(scene, dest, shot, sec)
    elif provider in ("http", "api"):
        ok = _provider_http(scene, dest, shot, sec)
    elif provider == "pollinations":
        ok = _provider_pollinations(scene, dest, shot, sec)
    elif provider not in ("none", "off", ""):
        ok = _provider_http(scene, dest, shot, sec)

    if ok:
        rel = str(shot.get("assets", {}).get("motion") or "")
        if rel:
            shot["assets"]["motion"] = rel
        return "ai"
    return "none"


def generate_shot_i2v(
    slug: str,
    episode: int,
    shot: dict[str, Any],
    *,
    force: bool = False,
) -> dict[str, Any]:
    """Try I2V when enabled; rebuild motion asset. Returns status dict."""
    if not force and not should_try_i2v(shot):
        return {"tried": False, "i2v_source": str(shot.get("i2v_source") or "none"), "reason": "i2v_off"}
    rel = motion_rel(slug, episode, int(shot.get("n") or 0))
    assets = shot.setdefault("assets", {})
    assets["motion"] = rel
    scene = resolve_safe(str(assets.get("scene") or ""))
    dest = resolve_safe(rel)
    source = try_generate_i2v(scene, dest, shot)
    shot["i2v_source"] = source
    if source == "ai":
        return {"tried": True, "i2v_source": "ai", "motion": rel, "seconds": i2v_seconds(shot)}
    return {"tried": True, "i2v_source": "none", "motion": None, "fallback": "still_zoompan"}
