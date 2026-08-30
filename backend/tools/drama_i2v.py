"""Image-to-video motion for locked keyframes (D8).

Tries a configured I2V provider for ~2–3s motion from scene.png. On failure,
the caller falls back to Ken Burns zoompan on the still (see drama_video).
"""

from __future__ import annotations

import os
import shutil
import subprocess
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
    from tools.drama_models import i2v_run_ladder, models_with_overrides

    effective_slug = slug or str(shot.get("_slug") or "") or None
    models = None
    if effective_slug:
        episode = int(shot.get("_episode") or 0) or None
        models = models_with_overrides(effective_slug, shot=shot, episode=episode)
    ladder = i2v_run_ladder(shot, slug=effective_slug, models=models)
    if ladder == "L0":
        return False
    if ladder == "L4":
        return True
    if mode == "on":
        return True
    locked = set(shot.get("locked") or [])
    return "scene" in locked or "shot" in locked


def i2v_seconds(shot: dict[str, Any] | None = None) -> float:
    """Provider I2V clip length (capped). Real APIs usually max ~4s; longer VO loops in encode."""
    raw = os.getenv("I2V_SECONDS")
    if shot and shot.get("i2v_seconds") is not None:
        raw = str(shot.get("i2v_seconds"))
    try:
        sec = float(raw if raw is not None else DEFAULT_SECONDS)
    except (TypeError, ValueError):
        sec = DEFAULT_SECONDS
    return max(MIN_SECONDS, min(sec, MAX_SECONDS))


KEN_BURNS_MAX_SECONDS = 30.0


def motion_seconds(shot: dict[str, Any] | None = None) -> float:
    """Ken Burns / fallback motion length: prefer script shot.duration."""
    base = i2v_seconds(shot)
    if not shot:
        return base
    try:
        dur = float(shot.get("duration") or 0)
    except (TypeError, ValueError):
        dur = 0.0
    if dur > base:
        return max(MIN_SECONDS, min(dur, KEN_BURNS_MAX_SECONDS))
    return base


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
        "电影感细微运动",
        camera,
        "竖屏9:16",
        scene or "人物肖像",
    ]
    if look:
        bits.append(look)
    bits.extend(["轻微动态", "无文字", "与锁定的角色参考图五官一致"])
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
    """S2: real I2V via a self-hosted gateway (async submit → poll → download).

    Submit contract (multipart/form-data):
        image    = locked keyframe PNG
        ref      = locked character reference PNG (optional)
        prompt   = motion prompt
        duration = seconds (str)
        model    = provider model id (e.g. kling-i2v)

    Response:
        - video/* content                → written directly (synchronous gateway)
        - JSON {job_id, poll_url?}       → poll until done, then download video
        - JSON {status: done, video_url} → download the mp4

    Never claims "ai" unless a real video was written; any failure/timeout returns
    False so the caller falls back to Ken Burns still motion.
    """
    import time

    import httpx

    url = (config.I2V_API_URL or os.getenv("I2V_API_URL") or "").strip()
    if not url:
        return False

    prompt = _motion_prompt(shot)
    headers = {"User-Agent": "my-tiktok-video-agent/1.0"}
    auth = (getattr(config, "I2V_API_KEY", "") or os.getenv("I2V_API_KEY") or "").strip()
    if auth:
        headers["Authorization"] = f"Bearer {auth}"

    files: dict[str, tuple[str, bytes, str]] = {
        "image": (scene.name, scene.read_bytes(), "image/png"),
    }
    slug = str(shot.get("_slug") or "")
    if slug:
        from tools.drama_qc import locked_ref_path

        ref = locked_ref_path(slug, shot)
        if ref is not None:
            files["ref"] = (ref.name, ref.read_bytes(), "image/png")

    data = {
        "prompt": prompt,
        "duration": str(seconds),
        "model": config.I2V_MODEL or "default",
    }

    interval = max(0.5, float(getattr(config, "I2V_POLL_INTERVAL", 2.0)))
    timeout = max(interval, float(getattr(config, "I2V_POLL_TIMEOUT", 300.0)))

    def _write_video(content: bytes) -> bool:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(content)
        return dest.is_file() and dest.stat().st_size > 1000

    try:
        with httpx.Client(timeout=120.0, follow_redirects=True) as client:
            resp = client.post(url, headers=headers, files=files, data=data)
            resp.raise_for_status()
            ctype = str(resp.headers.get("content-type") or "").lower()

            # Synchronous gateway: body is the video directly.
            if "video" in ctype:
                return _write_video(resp.content)

            # Async gateway: body is a job descriptor JSON.
            try:
                payload = resp.json()
            except Exception:
                payload = {}

            job_id = str(payload.get("job_id") or payload.get("id") or "").strip()
            if not job_id:
                return False

            poll_url = str(payload.get("poll_url") or "").strip()
            if not poll_url:
                poll_url = url.rstrip("/") + f"/{job_id}"

            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                time.sleep(interval)
                st = client.get(poll_url, headers=headers)
                st.raise_for_status()
                stype = str(st.headers.get("content-type") or "").lower()
                if "video" in stype:
                    return _write_video(st.content)
                try:
                    info = st.json()
                except Exception:
                    info = {}
                status = str(info.get("status") or "").lower()
                if status in ("done", "completed", "success", "succeeded"):
                    video_url = str(
                        info.get("video_url") or info.get("url") or info.get("result_url") or ""
                    ).strip()
                    if not video_url:
                        return False
                    v = client.get(video_url, headers=headers)
                    v.raise_for_status()
                    return _write_video(v.content)
                if status in ("failed", "error", "cancelled"):
                    return False
            return False
    except Exception:
        return False


def _provider_pollinations(scene: Path, dest: Path, shot: dict[str, Any], seconds: float) -> bool:
    """S2: pollinations is IMAGE generation, not I2V — never claim ai video output."""
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


def ensure_motion_seconds(path: Path, target: float) -> bool:
    """Pad a short motion mp4 up to script duration by freezing the last frame.

    Avoids stream_loop so performance masters are not polluted with a restart seam.
    """
    from tools.drama_video import FPS, _probe_duration, _run_ffmpeg

    target = float(target or 0)
    if target <= 0.1 or not path.is_file():
        return False
    cur = float(_probe_duration(path) or 0)
    if cur <= 0.05 or cur + 0.12 >= target:
        return cur + 0.12 >= target
    hold = max(0.0, target - cur)
    tmp = path.with_suffix(".pad.tmp.mp4")
    try:
        _run_ffmpeg(
            [
                "-y",
                "-i",
                str(path),
                "-vf",
                f"tpad=stop_mode=clone:stop_duration={hold:.3f},fps={FPS}",
                "-an",
                "-t",
                f"{target:.2f}",
                "-r",
                str(FPS),
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-movflags",
                "+faststart",
                str(tmp),
            ],
            timeout=180,
        )
        if not tmp.is_file() or tmp.stat().st_size < 500:
            return False
        tmp.replace(path)
        return float(_probe_duration(path) or 0) + 0.12 >= target
    except RuntimeError:
        return False
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
        from tools.drama_models import estimate_i2v, models_with_overrides

        episode = int(shot.get("_episode") or 0) or None
        models = models_with_overrides(slug, shot=shot, episode=episode)
        est = estimate_i2v(slug, shot, models=models)
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


_UNKNOWN_I2V_PROVIDERS = (
    "mock",
    "mock_ai",
    "l0",
    "fail",
    "http",
    "api",
    "kling",
    "hailuo",
    "pollinations",
    "none",
    "off",
    "",
)


def _run_i2v_provider(provider: str, scene: Path, dest: Path, shot: dict[str, Any], sec: float) -> bool:
    """Dispatch one I2V adapter with retry; returns True only on real 'ai' output.

    失败时不再偷偷用 mock 冒充 ai；由上层决定是否写 Ken Burns fallback。
    """
    from tools.drama_retry import retry_call
    from tools.providers import registry

    result = retry_call(
        registry.dispatch,
        "i2v",
        provider,
        scene,
        dest,
        shot,
        sec,
        ok=lambda r: r == "ai",
    )
    return result == "ai"


def try_generate_i2v(
    scene: Path,
    dest: Path,
    shot: dict[str, Any],
    *,
    seconds: float | None = None,
) -> str:
    """Return i2v_source: ai | keys | fallback | none."""
    if not scene.is_file():
        raise FileNotFoundError(f"缺少画面：{scene}")
    if not shutil.which(_ffmpeg_bin()):
        return "none"

    from tools.drama_models import effective_motion_ladder, models_with_overrides

    # Provider I2V stays capped (~4s APIs); Ken Burns / keys / final motion follow script duration.
    provider_sec = i2v_seconds(shot) if seconds is None else max(MIN_SECONDS, min(float(seconds), MAX_SECONDS))
    ken_sec = motion_seconds(shot) if seconds is None else max(provider_sec, float(seconds))
    ken_sec = max(MIN_SECONDS, min(ken_sec, KEN_BURNS_MAX_SECONDS))
    sec = provider_sec
    # Local mock generators should already render full script length (not the API cap).
    local_mock = {"mock", "mock_ai", "l0"}
    slug = str(shot.get("_slug") or "") or None
    episode = int(shot.get("_episode") or 0) or None
    models = models_with_overrides(slug, shot=shot, episode=episode) if slug else None
    planned = effective_motion_ladder(shot, slug=slug, models=models)
    provider = _resolved_i2v_provider(shot)
    shot["i2v_provider"] = provider
    run_sec = ken_sec if provider in local_mock else sec

    def _finish(source: str) -> str:
        if source in ("ai", "keys", "fallback") and dest.is_file():
            ensure_motion_seconds(dest, ken_sec)
        return source

    if planned == "L4":
        from tools.drama_keys import compose_keys_motion

        if compose_keys_motion(scene, dest, shot, max(ken_sec, 3.0)):
            shot["i2v_ladder"] = "L4"
            return _finish("keys")

    if planned == "L3":
        ok = _run_i2v_provider(provider, scene, dest, shot, max(run_sec, 3.0))
        if not ok:
            ok = _provider_l3_mock(scene, dest, shot, max(ken_sec, 3.0))
            if ok:
                shot["i2v_ladder"] = "L3"
                return _finish("fallback")
        if ok:
            shot["i2v_ladder"] = "L3"
            return _finish("ai")
        return "none"

    if planned == "L0" or provider in ("l0", "none", "off", ""):
        try:
            _provider_mock_ai(scene, dest, shot, max(ken_sec, 2.5))
            return _finish("fallback")
        except Exception:
            return "none"

    if _run_i2v_provider(provider, scene, dest, shot, run_sec):
        return _finish("ai")

    # 真 I2V 失败 → 明显 Ken Burns，标记 fallback（不要伪装成 ai）
    try:
        _provider_mock_ai(scene, dest, shot, max(ken_sec, 2.5))
        return _finish("fallback")
    except Exception:
        return "none"


def generate_shot_i2v(
    slug: str,
    episode: int,
    shot: dict[str, Any],
    *,
    force: bool = False,
    allow_locked: bool = False,
) -> dict[str, Any]:
    """Try I2V when enabled; rebuild motion asset. Returns status dict.

    Motion is the performance master. Locked motion is not overwritten unless
    the caller is an explicit video-page regenerate (force + allow_locked).
    Successful ai/keys runs auto-lock the motion layer.
    """
    from tools.drama_shots import set_shot_locks

    shot["_slug"] = slug
    shot["_episode"] = episode
    locked = set(shot.get("locked") or [])
    motion_locked = "motion" in locked or "shot" in locked
    rel = motion_rel(slug, episode, int(shot.get("n") or 0))
    assets = shot.setdefault("assets", {})
    assets["motion"] = rel
    dest = resolve_safe(rel)

    if motion_locked and not (force and allow_locked):
        src = str(shot.get("i2v_source") or "none")
        exists = dest.is_file() and dest.stat().st_size > 500
        shot.pop("_slug", None)
        shot.pop("_episode", None)
        return {
            "tried": False,
            "i2v_source": src if exists else "none",
            "motion": rel if exists else None,
            "reason": "motion_locked",
            "locked": True,
        }

    if not force and not should_try_i2v(shot, slug=slug):
        shot.pop("_slug", None)
        shot.pop("_episode", None)
        return {"tried": False, "i2v_source": str(shot.get("i2v_source") or "none"), "reason": "i2v_off"}

    scene = resolve_safe(str(assets.get("scene") or ""))
    source = try_generate_i2v(scene, dest, shot)
    shot["i2v_source"] = source
    if source == "ai" and str(shot.get("i2v_provider") or "") in ("kling", "kling-video", "kling-maas", "hailuo"):
        if not shot.get("i2v_deferred"):
            shot["i2v_expensive"] = True
    shot.pop("_slug", None)
    shot.pop("_episode", None)
    if source in ("ai", "keys", "fallback") and dest.is_file() and dest.stat().st_size > 500:
        # Auto-lock real performance masters so voice/lip cannot pollute them.
        if source in ("ai", "keys") and "motion" not in (shot.get("locked") or []) and "shot" not in (
            shot.get("locked") or []
        ):
            try:
                set_shot_locks(shot, lock=["motion"])
            except Exception:
                locked_list = list(shot.get("locked") or [])
                if "motion" not in locked_list:
                    locked_list.append("motion")
                    shot["locked"] = locked_list
        return {
            "tried": True,
            "i2v_source": source,
            "motion": rel,
            "seconds": motion_seconds(shot),
            "ladder": shot.get("i2v_ladder") or ("L4" if source == "keys" else "L1"),
            "deferred": bool(shot.get("i2v_deferred")),
            "provider": shot.get("i2v_provider") or "",
        }
    return {"tried": True, "i2v_source": "none", "motion": None, "fallback": "still_zoompan"}
