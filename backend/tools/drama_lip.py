"""Dialogue lip sync — quality-first (LatentSync / PixVerse / self-host).

Pipeline:
  1. Gate: dialogue|reaction CU/MCU/ECU with speaker + dialogue VO
  2. Ensure face **video** base (motion I2V → still-to-video)
  3. Cascade providers for best fidelity (never prefer mock unless allowed)
  4. Score with LSE proxy; clip encode burns subtitles afterwards
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

from config import config
from tools.drama_lse import score_lip
from tools.drama_models import infer_kind, infer_size, infer_speaker, load_models, resolve_provider
from tools.drama_shots import shot_stem
from tools.workspace import resolve_safe

LIP_KINDS = frozenset({"dialogue", "reaction"})
# WS/MS 也可做口型：底视频会做人脸区放大后再送 PixVerse
LIP_SIZES = frozenset({"CU", "MCU", "ECU", "MS", "WS"})
BLOCKED_KINDS = frozenset({"establishing", "crowd", "action", "title", "insert"})

# Prefer highest visual fidelity first when LIP_QUALITY=max (default).
QUALITY_CASCADE = (
    "latentsync",
    "pixverse",
    "pixverse-lipsync",
    "musetalk",
    "wav2lip",
    "http",
)


def lip_rel(slug: str, episode: int, n: int) -> str:
    return f"dramas/{slug}/videos/ep{int(episode):02d}/{shot_stem(n)}_lip.mp4"


def lip_base_rel(slug: str, episode: int, n: int) -> str:
    return f"dramas/{slug}/videos/ep{int(episode):02d}/{shot_stem(n)}_lip_base.mp4"


def lip_eligible(shot: dict[str, Any], *, models: dict[str, Any] | None = None) -> dict[str, Any]:
    kind = infer_kind(shot)
    size = infer_size(shot)
    speaker = infer_speaker(shot)
    roles = shot.get("角色") or []
    role_n = len(roles) if isinstance(roles, list) else len([x for x in str(roles).split(",") if x.strip()])
    dialogue = str(shot.get("字幕") or shot.get("对白") or "").strip()
    lip_cfg = (models or {}).get("lip") if isinstance((models or {}).get("lip"), dict) else {}
    if "enabled" in lip_cfg and not bool(lip_cfg.get("enabled")):
        return {"ok": False, "reason": "口型已在节点配置中关闭"}
    only_kinds = list(lip_cfg.get("only_kinds") or list(LIP_KINDS))
    if kind in BLOCKED_KINDS or (only_kinds and kind not in only_kinds):
        return {"ok": False, "reason": f"{kind} 镜不开口型"}
    if kind not in LIP_KINDS:
        return {"ok": False, "reason": "仅 dialogue/reaction 镜可生成口型"}
    only_sizes = list(lip_cfg.get("only_sizes") or list(LIP_SIZES))
    if only_sizes and size not in only_sizes:
        return {"ok": False, "reason": f"{size} 景别不开口型（需要特写/中景对话）"}
    if size not in LIP_SIZES:
        return {"ok": False, "reason": f"{size} 景别不开口型（需要 CU/MCU/ECU/MS/WS）"}
    if not speaker:
        return {"ok": False, "reason": "没有 speaker，不准接口型"}
    if role_n > 1 and not speaker:
        return {"ok": False, "reason": "多角色同框未指定 speaker"}
    if not dialogue:
        return {"ok": False, "reason": "没有字幕台词"}
    return {"ok": True, "reason": "", "kind": kind, "size": size, "speaker": speaker}


def estimate_lip(slug: str, shot: dict[str, Any], *, models: dict[str, Any] | None = None) -> dict[str, Any]:
    models = models or load_models(slug)
    gate = lip_eligible(shot, models=models)
    currency = str(models.get("currency") or "CNY")
    wanted = str((models.get("lip") or {}).get("provider") or _default_provider())
    provider = resolve_provider(models, wanted)
    card = (models.get("providers") or {}).get(provider) or {}
    cost = 0.0
    try:
        cost = float(card.get("cost_per_shot") or 0)
    except (TypeError, ValueError):
        cost = 0.0
    return {
        **gate,
        "provider": provider,
        "wanted_provider": wanted,
        "cost_per_shot": round(cost if gate["ok"] else 0.0, 4),
        "currency": currency,
        "will_run": bool(gate["ok"]),
        "lip_source": str(shot.get("lip_source") or ""),
        "score": shot.get("lip_score") or None,
    }


def estimate_episode_lip(slug: str, shots: list[dict[str, Any]]) -> dict[str, Any]:
    models = load_models(slug)
    total = 0.0
    n = 0
    for shot in shots:
        info = estimate_lip(slug, shot, models=models)
        if info.get("will_run"):
            total += float(info.get("cost_per_shot") or 0)
            n += 1
    return {
        "currency": str(models.get("currency") or "CNY"),
        "lip_estimate": round(total, 4),
        "lip_shots": n,
    }


def _ffmpeg_bin() -> str:
    return os.getenv("FFMPEG_BIN", "ffmpeg")


def _provider() -> str:
    return (os.getenv("LIP_PROVIDER") or getattr(config, "LIP_PROVIDER", "") or _default_provider()).strip().lower()


def _default_provider() -> str:
    # Prefer LatentSync when Replicate is configured; else PixVerse MaaS; else gateway.
    if (getattr(config, "REPLICATE_API_TOKEN", "") or os.getenv("REPLICATE_API_TOKEN") or "").strip():
        return "latentsync"
    if (getattr(config, "DASHSCOPE_MAAS_BASE_URL", "") or "").strip() and (
        getattr(config, "DASHSCOPE_API_KEY", "") or ""
    ).strip():
        return "pixverse"
    if (getattr(config, "LIP_API_URL", "") or "").strip():
        return "musetalk"
    return "pixverse"


def _quality_max() -> bool:
    raw = (getattr(config, "LIP_QUALITY", "") or os.getenv("LIP_QUALITY") or "max").strip().lower()
    return raw in ("max", "best", "high", "1", "true", "yes")


def _allow_mock() -> bool:
    raw = (getattr(config, "LIP_ALLOW_MOCK", "") or os.getenv("LIP_ALLOW_MOCK") or "0").strip().lower()
    return raw in ("1", "true", "yes", "on")


def _provider_ready(pid: str) -> bool:
    pid = str(pid or "").strip().lower()
    if pid in ("latentsync", "latent-sync", "replicate-lip"):
        return bool((getattr(config, "REPLICATE_API_TOKEN", "") or os.getenv("REPLICATE_API_TOKEN") or "").strip())
    if pid in ("pixverse", "pixverse-lipsync"):
        return bool(
            (getattr(config, "DASHSCOPE_API_KEY", "") or "").strip()
            and (getattr(config, "DASHSCOPE_MAAS_BASE_URL", "") or "").strip()
        )
    if pid in ("musetalk", "wav2lip", "http", "api"):
        return bool((getattr(config, "LIP_API_URL", "") or os.getenv("LIP_API_URL") or "").strip())
    if pid == "mock":
        return _allow_mock() or not _quality_max()
    return False


def lip_provider_cascade(wanted: str | None = None) -> list[str]:
    """Ordered list of runnable lip providers (best first)."""
    wanted = str(wanted or _provider() or "").strip().lower()
    ordered: list[str] = []
    seen: set[str] = set()

    def push(pid: str) -> None:
        pid = str(pid or "").strip().lower()
        if not pid or pid in seen:
            return
        if pid in ("none", "off", "fail", "l0"):
            return
        seen.add(pid)
        ordered.append(pid)

    if wanted:
        push(wanted)
    if _quality_max():
        for pid in QUALITY_CASCADE:
            push(pid)
    else:
        for pid in ("pixverse", "latentsync", "musetalk", "http"):
            push(pid)

    ready = [p for p in ordered if _provider_ready(p)]
    if not ready and _allow_mock():
        ready = ["mock"]
    elif not ready and not _quality_max():
        ready = ["mock"]
    return ready


def _still_to_face_video(
    scene: Path,
    dest: Path,
    duration: float,
    *,
    size: str = "MCU",
) -> bool:
    """Synthesize a short face-bearing video from a still — required by PixVerse/LatentSync.

    Keep the same 9:16 framing as the locked scene (no aggressive punch-in).
    Strong WS crop was cutting faces out of frame on the voice preview.
    """
    from tools.drama_video import FPS, HEIGHT, WIDTH, _run_ffmpeg

    dest.parent.mkdir(parents=True, exist_ok=True)
    t = max(float(duration or 3), 1.0)
    frames = max(int(round(t * FPS)), FPS)
    # 全景也保持原构图，仅极轻微呼吸感；避免把脸推到画外
    _ = size
    z_expr = "min(1.04,1+0.00025*on)"
    y_expr = "ih/2-(ih/zoom/2)"
    vf = (
        f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase,"
        f"crop={WIDTH}:{HEIGHT},"
        f"zoompan=z='{z_expr}':x='iw/2-(iw/zoom/2)':y='{y_expr}'"
        f":d={frames}:s={WIDTH}x{HEIGHT}:fps={FPS},format=yuv420p"
    )
    try:
        _run_ffmpeg(
            [
                "-y",
                "-loop",
                "1",
                "-framerate",
                str(FPS),
                "-i",
                str(scene),
                "-vf",
                vf,
                "-t",
                f"{t:.2f}",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-an",
                "-movflags",
                "+faststart",
                str(dest),
            ],
            timeout=120,
        )
        return dest.is_file() and dest.stat().st_size > 1000
    except RuntimeError:
        return False


def ensure_lip_video_base(
    slug: str,
    episode: int,
    shot: dict[str, Any],
    scene: Path,
    *,
    duration: float,
) -> Path | None:
    """Return face video for lip models — always chain from video-page motion when present.

    Pipeline contract: motion (上一步输出) is the visual master. Later steps may
    add lip/voice on top but must not substitute a different picture that drops
    camera / I2V performance. lip_base is only when there is no motion file.
    """
    assets = shot.setdefault("assets", {})
    n = int(shot.get("n") or 0)
    shot["lip_base_used"] = False

    def _motion_path() -> Path | None:
        for key in ("motion", "i2v"):
            rel = str(assets.get(key) or "").strip()
            if not rel:
                continue
            try:
                path = resolve_safe(rel)
            except ValueError:
                continue
            if (
                path.is_file()
                and path.suffix.lower() in (".mp4", ".mov", ".webm")
                and path.stat().st_size > 1000
            ):
                return path
        return None

    # 1) Video-page output first (ai / keys / fallback Ken Burns — all keep 运镜)
    existing = _motion_path()
    if existing is not None:
        return existing

    # 2) No motion yet → dedicated lip_base from still (does not invent a rival master)
    if not scene.is_file():
        return None
    rel = lip_base_rel(slug, episode, n)
    assets["lip_base"] = rel
    dest = resolve_safe(rel)
    size = infer_size(shot)
    if dest.is_file():
        try:
            dest.unlink()
        except OSError:
            pass
    if _still_to_face_video(scene, dest, duration, size=size):
        shot["lip_base_used"] = True
        return dest
    return None


def _mock_lip(scene: Path, voice: Path, dest: Path, duration: float) -> bool:
    from tools.drama_video import FPS, HEIGHT, WIDTH, _run_ffmpeg

    dest.parent.mkdir(parents=True, exist_ok=True)
    vf = (
        f"[0:v]scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase,"
        f"crop={WIDTH}:{HEIGHT},setsar=1,fps={FPS}[base];"
        f"[1:a]showwaves=s=280x90:mode=cline:rate={FPS}:colors=black:scale=sqrt[wave];"
        f"[wave]format=rgba,colorchannelmixer=aa=0.88[mouth];"
        f"[base][mouth]overlay=(W-w)/2:H*0.62:shortest=1,format=yuv420p[vout]"
    )
    try:
        _run_ffmpeg(
            [
                "-y",
                "-loop",
                "1",
                "-framerate",
                str(FPS),
                "-i",
                str(scene),
                "-i",
                str(voice),
                "-filter_complex",
                vf,
                "-map",
                "[vout]",
                "-map",
                "1:a",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-shortest",
                "-t",
                f"{max(duration, 0.8):.2f}",
                "-movflags",
                "+faststart",
                str(dest),
            ],
            timeout=120,
        )
        return dest.is_file() and dest.stat().st_size > 500
    except RuntimeError:
        return False


def _http_lip(scene: Path, voice: Path, dest: Path, shot: dict[str, Any], duration: float) -> bool:
    """Self-hosted MuseTalk / LatentSync gateway.

    Accepts image **or** video as visual input (prefer video when available).
    """
    url = (getattr(config, "LIP_API_URL", "") or os.getenv("LIP_API_URL") or "").strip()
    if not url:
        return False
    try:
        import httpx

        headers = {"User-Agent": "my-tiktok-video-agent/1.0"}
        key = (getattr(config, "LIP_API_KEY", "") or os.getenv("LIP_API_KEY") or "").strip()
        if key:
            headers["Authorization"] = f"Bearer {key}"
        visual = scene
        is_video = visual.suffix.lower() in (".mp4", ".mov", ".webm")
        mime = "video/mp4" if is_video else "image/png"
        field = "video" if is_video else "image"
        with httpx.Client(timeout=300.0, follow_redirects=True) as client:
            with visual.open("rb") as img, voice.open("rb") as aud:
                files = {
                    field: (visual.name, img, mime),
                    "audio": (voice.name, aud, "audio/mpeg"),
                }
                # Also send "image" alias for gateways that only accept stills
                if is_video:
                    # some gateways want both names
                    pass
                resp = client.post(
                    url,
                    files=files,
                    data={
                        "duration": str(duration),
                        "speaker": str(shot.get("speaker") or ""),
                        "quality": "max",
                        "inference_steps": str(getattr(config, "LIP_INFERENCE_STEPS", 30) or 30),
                    },
                    headers=headers,
                )
            resp.raise_for_status()
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(resp.content)
        return dest.is_file() and dest.stat().st_size > 1000
    except Exception:
        return False


def try_generate_lip(
    scene: Path,
    voice: Path,
    dest: Path,
    shot: dict[str, Any],
    *,
    duration: float,
    provider: str | None = None,
    video_base: Path | None = None,
) -> str:
    """Run lip cascade. `scene` may be still; `video_base` is preferred face video."""
    if not voice.is_file() or voice.stat().st_size < 80:
        return "fallback"
    if not shutil.which(_ffmpeg_bin()):
        return "fallback"

    visual = video_base if (video_base and video_base.is_file()) else scene
    if not visual.is_file():
        return "fallback"

    from tools.drama_retry import retry_call
    from tools.providers import registry

    cascade = lip_provider_cascade(provider)
    last = "fallback"
    for pid in cascade:
        if pid in ("fail", "none", "off", ""):
            continue
        if registry.has("lip", pid):
            # Video-first models need mp4; fall through if still-only
            needs_video = pid in (
                "latentsync",
                "latent-sync",
                "replicate-lip",
                "pixverse",
                "pixverse-lipsync",
            )
            inp = visual
            if needs_video and inp.suffix.lower() not in (".mp4", ".mov", ".webm"):
                continue
            source = retry_call(
                registry.dispatch,
                "lip",
                pid,
                inp,
                voice,
                dest,
                shot,
                duration,
                attempts=1,
                ok=lambda r: r not in ("fallback", "", None),
            )
            if source and source != "fallback":
                return str(source)
            last = "fallback"
            continue
        # Unknown: try http then mock
        if _http_lip(visual, voice, dest, shot, duration):
            return "http"
    if _allow_mock() or not _quality_max():
        # Mock can use still
        still = scene if scene.is_file() else visual
        if still.is_file() and _mock_lip(still, voice, dest, duration):
            return "mock"
    return last


def generate_shot_lip(
    slug: str,
    episode: int,
    shot: dict[str, Any],
    *,
    force: bool = False,
) -> dict[str, Any]:
    from tools.drama_models import models_with_overrides, resolve_provider

    models = models_with_overrides(slug, shot=shot, episode=episode)
    gate = lip_eligible(shot, models=models)
    if not gate["ok"] and not force:
        shot["lip_source"] = "blocked"
        return {"tried": False, "lip_source": "blocked", "reason": gate["reason"]}
    assets = shot.setdefault("assets", {})
    rel = lip_rel(slug, episode, int(shot.get("n") or 0))
    assets["lip"] = rel
    scene = resolve_safe(str(assets.get("scene") or ""))
    voice = resolve_safe(str(assets.get("voice") or ""))
    dest = resolve_safe(rel)
    duration = float(shot.get("duration") or 3)
    # Pad duration to voice length when longer (lip models need full VO coverage)
    if voice.is_file():
        try:
            from tools.drama_video import _probe_duration

            vd = float(_probe_duration(voice) or 0)
            if vd > duration:
                duration = vd
        except Exception:
            pass

    video_base = ensure_lip_video_base(slug, episode, shot, scene, duration=duration)
    wanted = str(((models or {}).get("lip") or {}).get("provider") or _default_provider()).strip()
    provider = resolve_provider(models, wanted)
    # If resolve fell through to mock but we have real providers, prefer cascade head
    if provider in ("mock", "l0") and _quality_max():
        cascade = lip_provider_cascade(wanted)
        provider = cascade[0] if cascade else provider

    source = try_generate_lip(
        scene,
        voice,
        dest,
        shot,
        duration=duration,
        provider=provider,
        video_base=video_base,
    )
    shot["lip_source"] = source
    score = None
    if source != "fallback" and dest.is_file():
        score = score_lip(dest, voice if voice.is_file() else None)
        shot["lip_score"] = score
        return {
            "tried": True,
            "lip_source": source,
            "lip": rel,
            "video_base": str((shot.get("assets") or {}).get("motion") or (shot.get("assets") or {}).get("lip_base") or ""),
            "provider": provider,
            "score": score,
            "reason": "",
        }
    if dest.exists():
        try:
            dest.unlink()
        except OSError:
            pass
    reason = "口型失败，回退闭口静图"
    if shot.get("lip_error"):
        reason = str(shot.get("lip_error"))
    elif _quality_max() and not lip_provider_cascade(wanted):
        reason = (
            "未配置可用口型模型：请设置 DASHSCOPE_MAAS_BASE_URL+DASHSCOPE_API_KEY（PixVerse）"
            " 或 REPLICATE_API_TOKEN（LatentSync）"
            " 或 LIP_API_URL（自建）"
        )
    shot["lip_score"] = {"status": "skipped", "reason": "fallback", "method": "proxy"}
    return {
        "tried": True,
        "lip_source": "fallback",
        "lip": None,
        "fallback": "still_l0_l1",
        "reason": reason,
        "score": shot["lip_score"],
    }
