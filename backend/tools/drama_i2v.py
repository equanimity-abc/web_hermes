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


def should_try_i2v(shot: dict[str, Any], *, slug: str | None = None) -> bool:
    mode = normalize_i2v_mode(shot.get("i2v"))
    if mode == "off":
        return False
    from tools.drama_models import i2v_run_ladder

    ladder = i2v_run_ladder(shot, slug=slug or str(shot.get("_slug") or "") or None)
    if ladder == "L0":
        return False
    if ladder == "L4":
        return True
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
    slug = str(shot.get("_slug") or "")
    look = ""
    if slug:
        from tools.drama_characters import (
            character_prompt_clause,
            load_characters,
            resolve_shot_characters,
        )

        cast = resolve_shot_characters(shot, load_characters(slug))
        look = character_prompt_clause(cast, slug=slug)
    bits = [
        "cinematic subtle motion",
        camera,
        "vertical 9:16",
        scene or "character portrait",
    ]
    if look:
        bits.append(look)
    bits.extend(["gentle movement", "no text", "same face as locked character reference"])
    return ", ".join(bits)


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
        files: dict[str, tuple[str, bytes, str]] = {
            "image": (scene.name, scene.read_bytes(), "image/png"),
        }
        slug = str(shot.get("_slug") or "")
        if slug:
            from tools.drama_qc import locked_ref_path

            ref = locked_ref_path(slug, shot)
            if ref is not None:
                files["ref"] = (ref.name, ref.read_bytes(), "image/png")
        with httpx.Client(timeout=120.0, follow_redirects=True) as client:
            resp = client.post(
                url,
                files=files,
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


def _concat_motion(first: Path, second: Path, dest: Path) -> bool:
    from tools.drama_video import _probe_duration, _run_ffmpeg

    dest.parent.mkdir(parents=True, exist_ok=True)
    d0 = float(_probe_duration(first) or 1.5)
    offset = max(0.15, d0 - 0.2)
    tmp = dest.with_suffix(".l3.tmp.mp4")
    try:
        _run_ffmpeg(
            [
                "-y",
                "-i",
                str(first),
                "-i",
                str(second),
                "-filter_complex",
                f"[0:v][1:v]xfade=transition=fade:duration=0.18:offset={offset:.2f},format=yuv420p[v]",
                "-map",
                "[v]",
                "-an",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-movflags",
                "+faststart",
                str(tmp),
            ],
            timeout=90,
        )
        tmp.replace(dest)
        return dest.is_file() and dest.stat().st_size > 500
    except RuntimeError:
        list_file = dest.parent / "_l3_concat.txt"
        try:
            list_file.write_text(
                f"file '{first.name}'\nfile '{second.name}'\n",
                encoding="utf-8",
            )
            _run_ffmpeg(
                [
                    "-y",
                    "-f",
                    "concat",
                    "-safe",
                    "0",
                    "-i",
                    str(list_file.name),
                    "-c",
                    "copy",
                    str(dest),
                ],
                timeout=90,
                cwd=dest.parent,
            )
            return dest.is_file() and dest.stat().st_size > 500
        except RuntimeError:
            return False
        finally:
            if list_file.exists():
                try:
                    list_file.unlink()
                except OSError:
                    pass
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


def _key_image(shot: dict[str, Any], index: int, fallback: Path) -> Path:
    keys = shot.get("keys") if isinstance(shot.get("keys"), list) else []
    if index < len(keys) and isinstance(keys[index], dict):
        rel = str(keys[index].get("file") or keys[index].get("path") or "").replace("\\", "/")
        if rel:
            try:
                path = resolve_safe(rel)
            except ValueError:
                path = None
            if path and path.is_file():
                return path
    return fallback


def _provider_l3_mock(scene: Path, dest: Path, shot: dict[str, Any], seconds: float) -> bool:
    """Dual-phase Ken Burns as degraded L3 (start pose → end pose)."""
    half = max(MIN_SECONDS, min(seconds / 2.0, MAX_SECONDS))
    start = _key_image(shot, 0, scene)
    end = _key_image(shot, 1, scene)
    tmp1 = dest.with_suffix(".k1.mp4")
    tmp2 = dest.with_suffix(".k2.mp4")
    try:
        _kenburns_motion_mp4(start, tmp1, {**shot, "camera": shot.get("camera") or "punch_in"}, half)
        _kenburns_motion_mp4(end, tmp2, {**shot, "camera": "pull_out"}, half)
        ok = _concat_motion(tmp1, tmp2, dest)
        return ok
    finally:
        for tmp in (tmp1, tmp2):
            if tmp.exists():
                try:
                    tmp.unlink()
                except OSError:
                    pass


def _resolved_i2v_provider(shot: dict[str, Any]) -> str:
    slug = str(shot.get("_slug") or "")
    if slug:
        from tools.drama_models import estimate_i2v

        est = estimate_i2v(slug, shot)
        if est.get("expensive"):
            from tools.drama_models import MAX_EXPENSIVE_I2V
            from tools.drama_shots import load_doc

            episode = int(shot.get("_episode") or 0)
            used = 0
            if episode:
                doc = load_doc(slug, episode)
                for other in (doc or {}).get("shots") or []:
                    if int(other.get("n") or 0) == int(shot.get("n") or 0):
                        continue
                    if other.get("i2v_source") == "ai" and other.get("i2v_expensive"):
                        used += 1
            if used >= MAX_EXPENSIVE_I2V:
                shot["i2v_deferred"] = True
                return "mock"
        return str(est.get("provider") or "mock")
    return _provider() or "mock"


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

    from tools.drama_models import effective_motion_ladder

    sec = i2v_seconds(shot) if seconds is None else max(MIN_SECONDS, min(float(seconds), MAX_SECONDS))
    planned = effective_motion_ladder(shot, slug=str(shot.get("_slug") or "") or None)
    provider = _resolved_i2v_provider(shot)
    ok = False
    if planned == "L4":
        from tools.drama_keys import compose_keys_motion

        if compose_keys_motion(scene, dest, shot, max(sec, 3.0)):
            shot["i2v_ladder"] = "L4"
            return "keys"
    if planned == "L3":
        ok = _provider_l3_mock(scene, dest, shot, max(sec, 3.0))
        if ok:
            shot["i2v_ladder"] = "L3"
    if not ok:
        from tools.providers import registry

        ok = registry.dispatch("i2v", provider, scene, dest, shot, sec) == "ai"
        # Unknown providers: try http then degraded local motion.
        if not ok and provider not in ("mock", "mock_ai", "l0", "fail", "http", "api", "kling", "hailuo", "pollinations", "none", "off", ""):
            ok = bool(_provider_http(scene, dest, shot, sec) or _provider_mock_ai(scene, dest, shot, sec))

    if ok:
        rel = str(shot.get("assets", {}).get("motion") or "")
        if rel:
            shot["assets"]["motion"] = rel
        if provider in ("kling", "hailuo") and not shot.get("i2v_deferred"):
            shot["i2v_expensive"] = True
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
    shot["_slug"] = slug
    shot["_episode"] = episode
    if not force and not should_try_i2v(shot, slug=slug):
        return {"tried": False, "i2v_source": str(shot.get("i2v_source") or "none"), "reason": "i2v_off"}
    rel = motion_rel(slug, episode, int(shot.get("n") or 0))
    assets = shot.setdefault("assets", {})
    assets["motion"] = rel
    scene = resolve_safe(str(assets.get("scene") or ""))
    dest = resolve_safe(rel)
    source = try_generate_i2v(scene, dest, shot)
    shot["i2v_source"] = source
    shot.pop("_slug", None)
    # keep _episode? pop it
    shot.pop("_episode", None)
    if source in ("ai", "keys"):
        return {
            "tried": True,
            "i2v_source": source,
            "motion": rel,
            "seconds": i2v_seconds(shot),
            "ladder": shot.get("i2v_ladder") or ("L4" if source == "keys" else "L1"),
            "deferred": bool(shot.get("i2v_deferred")),
        }
    return {"tried": True, "i2v_source": "none", "motion": None, "fallback": "still_zoompan"}
