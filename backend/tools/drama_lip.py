"""Dialogue lip sync — quality-first (LatentSync / PixVerse / self-host).

Pipeline:
  1. Gate: dialogue|reaction CU/MCU/ECU with speaker + dialogue VO
  2. Ensure face **video** base (motion I2V → still-to-video)
  3. Cascade providers for best fidelity (never prefer mock unless allowed)
  4. Score with LSE proxy; clip encode burns subtitles afterwards

Multi-speaker (DialogueTrack mode=multi / lip_strategy=per_turn):
  Production path (locks speaker, avoids rectangular seams):
    1) Lock cast→L/R once on an early plate frame (no mid-shot reflip)
    2) Crop speaker head → lip provider (face fills input → correct person)
    3) Poisson-seamlessClone **mouth ellipse only** onto original full frame
    4) Concatenate turns
  Fallback: full-frame per-turn lip if crop/clone fails (may lock wrong face on WS).
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
# Face crop fed to lip models. Square + uniform scale keeps the crop→lip→paste
# chain invertible (no aspect-ratio squash → no mouth drift / seams / flicker).
LIP_CROP_SIZE = 512

# PixVerse first (product decision 2026-09); LatentSync remains high-quality fallback.
QUALITY_CASCADE = (
    "pixverse",
    "pixverse-lipsync",
    "latentsync",
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
    # Product decision: PixVerse first; LatentSync when only Replicate is configured.
    if (getattr(config, "DASHSCOPE_MAAS_BASE_URL", "") or "").strip() and (
        getattr(config, "DASHSCOPE_API_KEY", "") or ""
    ).strip():
        return "pixverse"
    if (getattr(config, "REPLICATE_API_TOKEN", "") or os.getenv("REPLICATE_API_TOKEN") or "").strip():
        return "latentsync"
    if (getattr(config, "LIP_API_URL", "") or "").strip():
        return "musetalk"
    return "pixverse"


def _quality_max() -> bool:
    raw = (getattr(config, "LIP_QUALITY", "") or os.getenv("LIP_QUALITY") or "max").strip().lower()
    return raw in ("max", "best", "high", "1", "true", "yes")


def _allow_mock() -> bool:
    raw = (getattr(config, "LIP_ALLOW_MOCK", "") or os.getenv("LIP_ALLOW_MOCK") or "0").strip().lower()
    return raw in ("1", "true", "yes", "on")


def _lip_warn(shot: dict[str, Any] | None, message: str) -> None:
    """Record a degradation notice on the shot — degradation must never be silent."""
    if not isinstance(shot, dict):
        return
    warns = shot.get("lip_warnings")
    if not isinstance(warns, list):
        warns = []
        shot["lip_warnings"] = warns
    if message not in warns:
        warns.append(message)
    shot["lip_degraded"] = True


def _set_layout_source(shot: dict[str, Any] | None, source: str) -> None:
    """Tag which strategy locked cast→face (director / arcface / color / none)."""
    if isinstance(shot, dict):
        shot["lip_layout_source"] = source


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


def _ffmpeg_slice(
    src: Path,
    dest: Path,
    *,
    start: float,
    end: float,
    audio_only: bool = False,
) -> bool:
    from tools.drama_video import _run_ffmpeg

    dur = max(0.08, float(end) - float(start))
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        if audio_only:
            _run_ffmpeg(
                [
                    "-y",
                    "-ss",
                    f"{start:.3f}",
                    "-t",
                    f"{dur:.3f}",
                    "-i",
                    str(src),
                    "-vn",
                    "-acodec",
                    "libmp3lame",
                    "-q:a",
                    "2",
                    str(dest),
                ],
                timeout=120,
            )
        else:
            _run_ffmpeg(
                [
                    "-y",
                    "-ss",
                    f"{start:.3f}",
                    "-t",
                    f"{dur:.3f}",
                    "-i",
                    str(src),
                    "-an",
                    "-c:v",
                    "libx264",
                    "-pix_fmt",
                    "yuv420p",
                    "-movflags",
                    "+faststart",
                    str(dest),
                ],
                timeout=120,
            )
    except RuntimeError:
        return False
    return dest.is_file() and dest.stat().st_size > 200


def _concat_video_parts(parts: list[Path], dest: Path) -> bool:
    from tools.drama_video import _run_ffmpeg

    existing = [p for p in parts if p.is_file() and p.stat().st_size > 200]
    if not existing:
        return False
    if len(existing) == 1:
        try:
            shutil.copy2(existing[0], dest)
            return dest.is_file()
        except OSError:
            return False
    list_file = dest.parent / f"_lip_concat_{dest.stem}.txt"
    try:
        lines = []
        for p in existing:
            # ffmpeg concat demuxer needs escaped paths on Windows
            esc = str(p.resolve()).replace("\\", "/").replace("'", "'\\''")
            lines.append(f"file '{esc}'")
        list_file.write_text("\n".join(lines), encoding="utf-8")
        _run_ffmpeg(
            [
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(list_file),
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-an",
                "-movflags",
                "+faststart",
                str(dest),
            ],
            timeout=240,
        )
    except (RuntimeError, OSError):
        return False
    finally:
        try:
            list_file.unlink(missing_ok=True)
        except OSError:
            pass
    return dest.is_file() and dest.stat().st_size > 1000


def _sample_frame(video: Path, t: float, dest: Path) -> bool:
    from tools.drama_video import _run_ffmpeg

    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        _run_ffmpeg(
            [
                "-y",
                "-ss",
                f"{max(0.0, t):.3f}",
                "-i",
                str(video),
                "-frames:v",
                "1",
                "-q:v",
                "2",
                str(dest),
            ],
            timeout=60,
        )
    except RuntimeError:
        return False
    return dest.is_file() and dest.stat().st_size > 100


def _hist_vec_from_rgb(img_arr) -> list[float] | None:
    """Compact RGB histogram vector for region / template matching."""
    try:
        import numpy as np
    except Exception:
        return None
    arr = np.asarray(img_arr)
    if arr.size < 32:
        return None
    if arr.ndim == 2:
        arr = np.stack([arr, arr, arr], axis=-1)
    vec: list[float] = []
    for c in range(3):
        hist, _ = np.histogram(arr[:, :, c].ravel(), bins=16, range=(0, 256), density=True)
        vec.extend(float(x) for x in hist)
    return vec


def _normalize_box(x0: float, y0: float, x1: float, y1: float, w: int, h: int) -> tuple[float, float, float, float]:
    x0 = max(0.0, min(float(w - 1), x0))
    y0 = max(0.0, min(float(h - 1), y0))
    x1 = max(x0 + 1.0, min(float(w), x1))
    y1 = max(y0 + 1.0, min(float(h), y1))
    return (x0 / w, y0 / h, (x1 - x0) / w, (y1 - y0) / h)


def _square_box(w: int, h: int, box: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
    """Expand a normalized box to a pixel-square region centered on it, clamped to frame.

    Crop (ffmpeg) and paste-back (Poisson) must share this exact square region, so
    the mouth lands where it belongs — no aspect-ratio squash → no 裂痕/波动.
    """
    x, y, bw, bh = box
    cw = max(1, int(round(bw * w)))
    ch = max(1, int(round(bh * h)))
    side = min(max(cw, ch), w, h)
    cx = int(round((x + bw / 2.0) * w))
    cy = int(round((y + bh / 2.0) * h))
    x0 = max(0, min(w - side, cx - side // 2))
    y0 = max(0, min(h - side, cy - side // 2))
    return (x0 / w, y0 / h, side / w, side / h)


def _probe_video_size(path: Path) -> tuple[int, int]:
    try:
        import cv2

        cap = cv2.VideoCapture(str(path))
        if not cap.isOpened():
            return (0, 0)
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        cap.release()
        return (w, h)
    except Exception:
        return (0, 0)


def _arcface_embed_bgr(img_bgr) -> tuple[list[float] | None, str]:
    """ArcFace embedding from a BGR image (consistent channel order for identity)."""
    try:
        import insightface.app  # type: ignore  # noqa: F401
    except ImportError:
        return None, "no_insightface"
    try:
        from tools.drama_qc import _arcface_singleton

        app = _arcface_singleton()
        faces = app.get(img_bgr)
        if not faces:
            return None, "no_face"
        emb = getattr(faces[0], "normed_embedding", None) or getattr(faces[0], "embedding", None)
        if emb is None:
            return None, "no_embedding"
        return [float(x) for x in list(emb)], "arcface"
    except Exception:
        return None, "arcface_error"


def _ref_embedding(ref_path: Path) -> tuple[list[float] | None, str]:
    try:
        import cv2
    except Exception:
        return None, "no_cv2"
    img = cv2.imread(str(ref_path))
    if img is None:
        return None, "no_image"
    return _arcface_embed_bgr(img)


def _square_face_box_from_bbox(
    w: int, h: int, bbox: tuple[float, float, float, float]
) -> tuple[float, float, float, float]:
    """Tight square head crop from a face bbox (matches _speaker_face_crop_box)."""
    x1, y1, x2, y2 = [float(v) for v in bbox]
    cx = (x1 + x2) / 2.0
    cy = (y1 + y2) / 2.0
    side = max(x2 - x1, y2 - y1, 1.0) * 2.4
    half = side / 2.0
    x0 = max(0.0, cx - half)
    y0 = max(0.0, cy - half * 0.85)
    x1b = min(float(w), x0 + side)
    y1b = min(float(h), y0 + side)
    x0 = max(0.0, x1b - side)
    y0 = max(0.0, y1b - side)
    return (x0 / w, y0 / h, (x1b - x0) / w, (y1b - y0) / h)


def _char_ref_file(slug: str, cid: str, face_ref: str = "") -> Path | None:
    """Resolve a character's locked 定妆图 for identity matching."""
    if face_ref:
        try:
            p = resolve_safe(str(face_ref))
            if p.is_file() and p.stat().st_size > 32:
                return p
        except ValueError:
            pass
    if not cid:
        return None
    try:
        from tools.drama_characters import find_character, load_characters, ref_exists, ref_rel

        char = find_character(load_characters(slug), cid)
        if char and ref_exists(slug, char):
            rel = str(char.get("ref") or ref_rel(slug, cid))
            p = resolve_safe(rel)
            if p.is_file() and p.stat().st_size > 32:
                return p
    except Exception:
        return None
    return None


def _identity_layout_lock(
    frame_arr,
    w: int,
    h: int,
    ids: list[str],
    face_refs: dict[str, str],
    slug: str,
) -> dict[str, tuple[float, float, float, float]]:
    """Lock character→face-box by ArcFace identity (robust to lighting/clothing).

    Returns {} when ArcFace or reference images are unavailable — the caller then
    falls back to the color heuristic. This is the production fix for 口型错位.
    """
    try:
        from tools.drama_qc import _arcface_singleton, _cosine
    except Exception:
        return {}

    ref_embs: dict[str, list[float]] = {}
    for cid in ids:
        ref_path = _char_ref_file(slug, cid, face_refs.get(cid) or "")
        if ref_path is None:
            continue
        emb, method = _ref_embedding(ref_path)
        if emb is not None and method == "arcface":
            ref_embs[cid] = emb
    if len(ref_embs) < 2:
        return {}

    try:
        app = _arcface_singleton()
        faces = app.get(frame_arr)
    except Exception:
        return {}
    if not faces:
        return {}

    detected: list[dict[str, Any]] = []
    for face in faces:
        emb = getattr(face, "normed_embedding", None) or getattr(face, "embedding", None)
        bbox = getattr(face, "bbox", None)
        if emb is None or bbox is None:
            continue
        detected.append({"bbox": bbox, "emb": [float(x) for x in list(emb)]})
    if len(detected) < 2:
        return {}

    pairs: list[tuple[float, str, int]] = []
    for cid, ref in ref_embs.items():
        for fi, det in enumerate(detected):
            pairs.append((float(_cosine(ref, det["emb"])), cid, fi))
    pairs.sort(reverse=True)

    layout: dict[str, tuple[float, float, float, float]] = {}
    used_faces: set[int] = set()
    used_cids: set[str] = set()
    min_cosine = 0.25
    for score, cid, fi in pairs:
        if score < min_cosine:
            continue
        if cid in used_cids or fi in used_faces:
            continue
        layout[cid] = _square_face_box_from_bbox(w, h, detected[fi]["bbox"])
        used_cids.add(cid)
        used_faces.add(fi)

    if len(ids) == 2 and len(layout) != 2:
        return {}
    if len(layout) < 2:
        return {}
    return layout


def _dual_speaker_candidate_boxes(w: int, h: int) -> list[tuple[float, float, float, float]]:
    """Left / right **head** zones for 2-shot WS/MS when ArcFace is unavailable.

    Must stay head-sized. Half-frame L/R crops paste back as a visible vertical
    seam down the middle of the shot (user-visible 「分割线」).
    """
    box_w, box_h = 0.34, 0.30
    y0 = 0.10
    left = _normalize_box(w * 0.08, h * y0, w * (0.08 + box_w), h * (y0 + box_h), w, h)
    right = _normalize_box(w * 0.58, h * y0, w * (0.58 + box_w), h * (y0 + box_h), w, h)
    return [left, right]


def _ref_head_patch(ref_path: Path):
    """Upper torso/head crop from a character 定妆图 for color matching."""
    try:
        from PIL import Image
        import numpy as np
    except Exception:
        return None
    try:
        img = np.array(Image.open(ref_path).convert("RGB"))
    except Exception:
        return None
    h, w = img.shape[:2]
    if h < 16 or w < 16:
        return None
    # Character cards are often a front/side/back strip — take the leftmost third, upper 40%.
    x0, x1 = 0, max(16, w // 3)
    y0, y1 = 0, max(16, int(h * 0.40))
    return img[y0:y1, x0:x1]


def _box_hist_match_score(frame_arr, box: tuple[float, float, float, float], ref_vec: list[float]) -> float:
    from tools.drama_qc import _cosine

    h, w = frame_arr.shape[:2]
    x, y, bw, bh = box
    x0, y0 = int(x * w), int(y * h)
    x1, y1 = int((x + bw) * w), int((y + bh) * h)
    patch = frame_arr[y0:y1, x0:x1]
    vec = _hist_vec_from_rgb(patch)
    if vec is None:
        return -1.0
    return float(_cosine(ref_vec, vec))


def _parse_hex_colors(raw: str) -> list[tuple[int, int, int]]:
    import re

    out: list[tuple[int, int, int]] = []
    for m in re.finditer(r"#([0-9A-Fa-f]{6})", str(raw or "")):
        hx = m.group(1)
        out.append((int(hx[0:2], 16), int(hx[2:4], 16), int(hx[4:6], 16)))
    return out


def _box_color_affinity(frame_arr, box: tuple[float, float, float, float], colors: list[tuple[int, int, int]]) -> float:
    """How strongly a frame zone matches character palette colors (0–1)."""
    if not colors:
        return 0.0
    try:
        import numpy as np
    except Exception:
        return 0.0
    h, w = frame_arr.shape[:2]
    x, y, bw, bh = box
    x0, y0 = int(x * w), int(y * h)
    x1, y1 = max(x0 + 1, int((x + bw) * w)), max(y0 + 1, int((y + bh) * h))
    patch = frame_arr[y0:y1, x0:x1]
    if patch.size < 32:
        return 0.0
    ph, pw = patch.shape[:2]
    step = max(1, int((ph * pw) ** 0.5 // 48) or 1)
    best_frac = 0.0
    for cr, cg, cb in colors:
        mx, mn = max(cr, cg, cb), min(cr, cg, cb)
        chroma = mx - mn
        # Near-white: only mid band (clothing), avoid floor milk / background glow
        if mx >= 220 and chroma < 35:
            band = patch[int(ph * 0.30) : int(ph * 0.75) : step, ::step]
        # Near-black: only upper band (hair)
        elif mx <= 45 and chroma < 30:
            band = patch[0 : max(1, int(ph * 0.35)) : step, ::step]
        # Saturated accents (pink dress, chestnut hair, etc.)
        elif chroma >= 35:
            band = patch[::step, ::step]
        else:
            band = patch[::step, ::step]
        if band.size < 8:
            continue
        pix = band.reshape(-1, 3).astype("float32")
        dist = ((pix[:, 0] - cr) ** 2 + (pix[:, 1] - cg) ** 2 + (pix[:, 2] - cb) ** 2) ** 0.5
        thr = 55.0 if chroma >= 35 else 40.0
        frac = float((dist < thr).mean())
        # Boost saturated hits — they discriminate characters better than neutrals
        weight = 1.35 if chroma >= 35 else 1.0
        best_frac = max(best_frac, frac * weight)
    return best_frac


def _character_palette(slug: str, character_id: str, face_ref: str = "") -> list[tuple[int, int, int]]:
    colors: list[tuple[int, int, int]] = []
    try:
        from tools.drama_characters import find_character, load_characters
    except Exception:
        find_character = load_characters = None  # type: ignore
    if load_characters and find_character and character_id:
        char = find_character(load_characters(slug), character_id)
        if char:
            colors.extend(_parse_hex_colors(str(char.get("colors") or "")))
            # Hair/clothing cues from look text are weak; rely on colors field.
    # Always include a few pixels sampled from the 定妆图 head as extra anchors.
    if face_ref:
        try:
            head = _ref_head_patch(resolve_safe(face_ref))
        except Exception:
            head = None
        if head is not None:
            try:
                import numpy as np

                h, w = head.shape[:2]
                for y, x in ((h // 4, w // 2), (h // 2, w // 2), (h // 3, w // 3)):
                    r, g, b = [int(v) for v in head[min(h - 1, y), min(w - 1, x)][:3]]
                    colors.append((r, g, b))
            except Exception:
                pass
    return colors


def _palette_wants_warm_accent(colors: list[tuple[int, int, int]]) -> bool:
    """True when card palette has pink/warm dress accents (vs cool/dark leads)."""
    for r, g, b in colors:
        if r >= 170 and (r - g) >= 20 and (r - b) >= 15:
            return True
    return False


def _box_pink_frac(frame_arr, box: tuple[float, float, float, float]) -> float:
    try:
        import numpy as np
    except Exception:
        return 0.0
    h, w = frame_arr.shape[:2]
    x, y, bw, bh = box
    patch = frame_arr[int(y * h) : int((y + bh) * h), int(x * w) : int((x + bw) * w)]
    if patch.size < 32:
        return 0.0
    pix = patch.reshape(-1, 3).astype("float32")
    r, g, b = pix[:, 0], pix[:, 1], pix[:, 2]
    mask = (r > 150) & ((r - g) > 20) & ((r - b) > 15) & (g > 60)
    return float(mask.mean())


def _speaker_face_crop_box_fallback(
    frame: Path,
    ref_path: Path,
    *,
    slug: str = "",
    character_id: str = "",
) -> tuple[float, float, float, float] | None:
    """When InsightFace/ArcFace is missing, pick L/R face zone for the speaker.

    Dual-hander heuristic: pink/warm-accent characters take the pinker side;
    the other speaker takes the opposite side. This matches typical sister
    rivalry framing (粉裙 vs 白衣) without needing ArcFace on anime faces.
    """
    try:
        from PIL import Image
        import numpy as np
    except Exception:
        return None
    if not frame.is_file() or not ref_path.is_file():
        return None
    try:
        frame_arr = np.array(Image.open(frame).convert("RGB"))
    except Exception:
        return None
    h, w = frame_arr.shape[:2]
    left, right = _dual_speaker_candidate_boxes(w, h)
    # Prefer colors declared on the card; ignore noisy 定妆图 pixel samples for
    # side picking (triptych cards pollute histograms).
    palette: list[tuple[int, int, int]] = []
    try:
        from tools.drama_characters import find_character, load_characters

        char = find_character(load_characters(slug), character_id) if character_id else None
        if char:
            palette = _parse_hex_colors(str(char.get("colors") or ""))
    except Exception:
        palette = []

    pink_l = _box_pink_frac(frame_arr, left)
    pink_r = _box_pink_frac(frame_arr, right)
    # Always use relative pink (even tiny margins). Absolute gate was flipping
    # 白若琳/白若曦 on low-chroma motion frames.
    if palette and _palette_wants_warm_accent(palette):
        return left if pink_l >= pink_r else right
    if palette and not _palette_wants_warm_accent(palette):
        return right if pink_l >= pink_r else left

    left_a = _box_color_affinity(frame_arr, left, palette) if palette else -1.0
    right_a = _box_color_affinity(frame_arr, right, palette) if palette else -1.0
    if abs(left_a - right_a) >= 0.02:
        return left if left_a > right_a else right

    head = _ref_head_patch(ref_path)
    if head is not None:
        ref_vec = _hist_vec_from_rgb(head)
        if ref_vec is not None:
            left_s = _box_hist_match_score(frame_arr, left, ref_vec)
            right_s = _box_hist_match_score(frame_arr, right, ref_vec)
            if abs(left_s - right_s) >= 0.01:
                return left if left_s > right_s else right
    return left if pink_l >= pink_r else right


def _speaker_face_crop_box(
    frame: Path,
    slug: str,
    character_id: str,
    *,
    face_ref: str = "",
) -> tuple[float, float, float, float] | None:
    """Return normalized crop (x,y,w,h) around the speaking character's face, or None.

    Matches frame faces against the character card 定妆图 (face_ref or card.ref).
    Works for any N speakers as long as each turn has character_id / face_ref.
    Falls back to L/R color zones when InsightFace is not installed (common on
    Windows) — otherwise WS multi lip silently runs full-frame and mouths freeze.
    """
    if not frame.is_file():
        return None

    ref_path: Path | None = None
    try:
        from tools.drama_characters import find_character, load_characters, ref_exists, ref_rel
    except Exception:
        find_character = load_characters = ref_exists = ref_rel = None  # type: ignore

    if face_ref:
        try:
            cand = resolve_safe(str(face_ref))
            if cand.is_file() and cand.stat().st_size > 32:
                ref_path = cand
        except ValueError:
            ref_path = None
    if ref_path is None and character_id and load_characters and find_character and ref_exists and ref_rel:
        cards = load_characters(slug)
        char = find_character(cards, character_id)
        if char and ref_exists(slug, char):
            try:
                ref_path = resolve_safe(str(char.get("ref") or ref_rel(slug, character_id)))
            except ValueError:
                ref_path = None
    if ref_path is None or not ref_path.is_file():
        return None

    # --- Preferred: ArcFace identity match ---
    try:
        from tools.drama_qc import _arcface_embedding, _arcface_singleton, _cosine
        import numpy as np
        from PIL import Image

        ref_emb, method = _arcface_embedding(ref_path)
        if ref_emb is not None and method == "arcface":
            app = _arcface_singleton()
            img = np.array(Image.open(frame).convert("RGB"))
            h, w = img.shape[:2]
            faces = app.get(img)
            if faces:
                best = None
                best_score = -1.0
                for face in faces:
                    emb = getattr(face, "normed_embedding", None) or getattr(face, "embedding", None)
                    if emb is None:
                        continue
                    score = _cosine(ref_emb, [float(x) for x in list(emb)])
                    if score > best_score:
                        best_score = score
                        best = face
                if best is not None and best_score >= 0.25:
                    bbox = getattr(best, "bbox", None)
                    if bbox is not None:
                        x1, y1, x2, y2 = [float(v) for v in bbox]
                        cx = (x1 + x2) / 2
                        cy = (y1 + y2) / 2
                        bw = max(x2 - x1, 1.0)
                        bh = max(y2 - y1, 1.0)
                        side = max(bw, bh) * 2.4
                        half = side / 2
                        x0 = max(0.0, cx - half)
                        y0 = max(0.0, cy - half * 0.85)
                        x1b = min(float(w), x0 + side)
                        y1b = min(float(h), y0 + side)
                        x0 = max(0.0, x1b - side)
                        y0 = max(0.0, y1b - side)
                        return (x0 / w, y0 / h, (x1b - x0) / w, (y1b - y0) / h)
    except Exception:
        pass

    # --- Fallback: color zone match (no InsightFace) ---
    return _speaker_face_crop_box_fallback(
        frame, ref_path, slug=slug, character_id=character_id
    )


def _resolve_turn_face(slug: str, turn: dict[str, Any]) -> tuple[str, str]:
    """Return (character_id, face_ref) for a dialogue turn, resolving name if needed."""
    cid = str(turn.get("character_id") or "").strip()
    face_ref = str(turn.get("face_ref") or "").strip()
    if cid and face_ref:
        return cid, face_ref
    try:
        from tools.drama_characters import load_characters
        from tools.drama_dialogue import resolve_speaker_binding
    except Exception:
        return cid, face_ref
    cards = load_characters(slug)
    token = cid or str(turn.get("character_name") or turn.get("speaker") or "")
    if not token:
        return cid, face_ref
    bind = resolve_speaker_binding(token, cards, slug=slug)
    return (
        cid or str(bind.get("character_id") or ""),
        face_ref or str(bind.get("face_ref") or ""),
    )


def _crop_video_box(video: Path, box: tuple[float, float, float, float], dest: Path) -> bool:
    """Crop a video to a **square** head region and scale uniformly to LIP_CROP_SIZE.

    Square + uniform scale keeps the crop→lip→paste chain invertible: the lip model
    sees the same head it will be composited back over, so the mouth does not drift
    (previous 9:16 re-scale squashed the mouth and caused 裂痕/波动).
    """
    from tools.drama_video import FPS, _run_ffmpeg

    w, h = _probe_video_size(video)
    if w < 8 or h < 8:
        w, h = 1080, 1920
    x, y, bw, bh = _square_box(w, h, box)
    x0 = int(round(x * w))
    y0 = int(round(y * h))
    side = max(2, min(int(round(bw * w)), w - x0, h - y0))
    dest.parent.mkdir(parents=True, exist_ok=True)
    vf = (
        f"crop={side}:{side}:{x0}:{y0},"
        f"scale={LIP_CROP_SIZE}:{LIP_CROP_SIZE}:flags=lanczos,"
        f"setsar=1,fps={FPS},format=yuv420p"
    )
    try:
        _run_ffmpeg(
            ["-y", "-i", str(video), "-vf", vf, "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(dest)],
            timeout=180,
        )
    except RuntimeError:
        return False
    return dest.is_file() and dest.stat().st_size > 1000


def _mouth_center_in_box(frame_bgr, box: tuple[float, float, float, float]) -> tuple[float, float]:
    """Normalized mouth center within a square box, from ArcFace 5-point landmarks.

    Falls back to (0.5, 0.72) when landmarks are unavailable. A stable, correctly
    positioned ellipse is what keeps Poisson paste-back free of 裂痕/波动.
    """
    h, w = frame_bgr.shape[:2]
    x, y, bw, _ = _square_box(w, h, box)
    x0 = int(round(x * w))
    y0 = int(round(y * h))
    side = int(round(bw * w))
    if side < 8:
        return (0.5, 0.72)
    try:
        from tools.drama_qc import _arcface_singleton

        app = _arcface_singleton()
        faces = app.get(frame_bgr)
        best = None
        best_iou = 0.0
        for face in faces:
            bbox = getattr(face, "bbox", None)
            if bbox is None:
                continue
            fx1, fy1, fx2, fy2 = [float(v) for v in bbox]
            ix1 = max(float(x0), fx1)
            iy1 = max(float(y0), fy1)
            ix2 = min(float(x0 + side), fx2)
            iy2 = min(float(y0 + side), fy2)
            if ix2 <= ix1 or iy2 <= iy1:
                continue
            inter = (ix2 - ix1) * (iy2 - iy1)
            union = max(1.0, (fx2 - fx1) * (fy2 - fy1))
            iou = inter / union
            if iou > best_iou:
                best_iou = iou
                best = face
        if best is not None:
            kps = getattr(best, "kps", None)
            if kps is not None and len(kps) >= 5:
                mx = (float(kps[3][0]) + float(kps[4][0])) / 2.0
                my = (float(kps[3][1]) + float(kps[4][1])) / 2.0
                return (
                    max(0.0, min(1.0, (mx - x0) / side)),
                    max(0.0, min(1.0, (my - y0) / side)),
                )
    except Exception:
        pass
    return (0.5, 0.72)


def _overlay_lip_mouth(
    base_seg: Path,
    lip_face: Path,
    box: tuple[float, float, float, float],
    dest: Path,
) -> bool:
    """Poisson mouth composite with identity-locked, invertible geometry.

    Crop and paste-back share the same square box, and the mouth ellipse follows
    the real mouth (landmarks) instead of a fixed guess — this removes both
    口型错位 and the 裂痕/波动 caused by a squashed, misaligned patch.
    """
    import cv2
    import numpy as np

    from tools.drama_video import FPS, _run_ffmpeg

    if not base_seg.is_file() or not lip_face.is_file():
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)

    cap_b = cv2.VideoCapture(str(base_seg))
    cap_f = cv2.VideoCapture(str(lip_face))
    if not cap_b.isOpened() or not cap_f.isOpened():
        cap_b.release()
        cap_f.release()
        return False

    fps = float(cap_b.get(cv2.CAP_PROP_FPS) or FPS or 25) or 25.0
    width = int(cap_b.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    height = int(cap_b.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    if width < 8 or height < 8:
        cap_b.release()
        cap_f.release()
        return False

    # Same square region _crop_video_box used — invertible geometry.
    x, y, bw, _ = _square_box(width, height, box)
    x0 = max(0, min(width - 2, int(round(x * width))))
    y0 = max(0, min(height - 2, int(round(y * height))))
    side = max(16, min(width - x0, height - y0, int(round(bw * width))))
    fw = fh = side

    raw = dest.with_suffix(".poisson.tmp.mp4")
    writer = cv2.VideoWriter(str(raw), cv2.VideoWriter_fourcc(*"mp4v"), fps, (width, height))
    if not writer.isOpened():
        cap_b.release()
        cap_f.release()
        return False

    patch_center = (
        min(width - 1, max(0, x0 + fw // 2)),
        min(height - 1, max(0, y0 + fh // 2)),
    )
    axes = (max(6, int(fw * 0.40)), max(6, int(fh * 0.28)))
    mouth_mask = None
    alpha_patch = None

    ok_frames = 0
    try:
        while True:
            ok_b, base = cap_b.read()
            if not ok_b:
                break
            if mouth_mask is None:
                mc = _mouth_center_in_box(base, box)
                cx = max(1, min(fw - 2, int(mc[0] * fw)))
                cy = max(1, min(fh - 2, int(mc[1] * fh)))
                hard = np.zeros((fh, fw), dtype=np.uint8)
                cv2.ellipse(hard, (cx, cy), axes, 0, 0, 360, 255, -1)
                # Keep mask fully inside patch so seamlessClone never samples outside src.
                cv2.rectangle(hard, (0, 0), (fw - 1, fh - 1), 0, 1)
                mouth_mask = hard
                # Feathered alpha for a soft edge → no seam / crack.
                alpha_patch = cv2.GaussianBlur(hard, (15, 15), 0).astype(np.float32) / 255.0
                alpha_patch = alpha_patch[..., None]

            ok_f, face = cap_f.read()
            if not ok_f or face is None:
                writer.write(base)
                ok_frames += 1
                continue
            face_r = cv2.resize(face, (fw, fh), interpolation=cv2.INTER_AREA)
            try:
                clone = cv2.seamlessClone(face_r, base, mouth_mask, patch_center, cv2.NORMAL_CLONE)
                patch = base[y0 : y0 + fh, x0 : x0 + fw].astype(np.float32)
                cp = clone[y0 : y0 + fh, x0 : x0 + fw].astype(np.float32)
                blended = patch * (1.0 - alpha_patch) + cp * alpha_patch
                out = base.copy()
                out[y0 : y0 + fh, x0 : x0 + fw] = blended.astype(np.uint8)
            except cv2.error:
                out = base
            writer.write(out)
            ok_frames += 1
    finally:
        writer.release()
        cap_b.release()
        cap_f.release()

    if ok_frames < 2 or not raw.is_file() or raw.stat().st_size < 1000:
        try:
            raw.unlink(missing_ok=True)
        except OSError:
            pass
        return False

    try:
        _run_ffmpeg(
            [
                "-y",
                "-i",
                str(raw),
                "-an",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-movflags",
                "+faststart",
                str(dest),
            ],
            timeout=180,
        )
    except RuntimeError:
        try:
            raw.unlink(missing_ok=True)
        except OSError:
            pass
        return False
    try:
        raw.unlink(missing_ok=True)
    except OSError:
        pass
    return dest.is_file() and dest.stat().st_size > 1000


def _overlay_lip_face(
    base_seg: Path,
    lip_face: Path,
    box: tuple[float, float, float, float],
    dest: Path,
) -> bool:
    """Back-compat alias → Poisson mouth composite."""
    return _overlay_lip_mouth(base_seg, lip_face, box, dest)


def _coerce_box(raw: Any, w: int, h: int) -> tuple[float, float, float, float] | None:
    if isinstance(raw, (list, tuple)) and len(raw) == 4:
        try:
            x, y, bw, bh = (float(v) for v in raw)
            return (x, y, bw, bh)
        except (TypeError, ValueError):
            return None
    if isinstance(raw, dict):
        try:
            x = float(raw.get("x") or 0)
            y = float(raw.get("y") or 0)
            bw = float(raw.get("w") or raw.get("width") or 0)
            bh = float(raw.get("h") or raw.get("height") or 0)
            if bw > 0 and bh > 0:
                return (x, y, bw, bh)
        except (TypeError, ValueError):
            return None
    return None


def _side_box(side: Any, w: int, h: int) -> tuple[float, float, float, float] | None:
    left, right = _dual_speaker_candidate_boxes(w, h)
    s = str(side or "").strip().lower()
    if s in ("left", "l", "左"):
        return left
    if s in ("right", "r", "右"):
        return right
    return None


def _explicit_layout(
    slug: str,
    shot: dict[str, Any] | None,
    turns: list[dict[str, Any]],
    ids: list[str],
    w: int,
    h: int,
) -> dict[str, tuple[float, float, float, float]]:
    """Human/director override: shot.lip_layout or per-turn side/box. Deterministic."""
    layout: dict[str, tuple[float, float, float, float]] = {}
    raw = (shot or {}).get("lip_layout")
    if isinstance(raw, dict):
        # {"left": cid, "right": cid}
        for key, val in raw.items():
            box = _side_box(key, w, h)
            if box is not None and isinstance(val, str) and val in ids:
                layout.setdefault(val, box)
        # {"cid": "left"|"right"} or {"cid": {x,y,w,h}} or {"cid": [x,y,w,h]}
        for cid, val in raw.items():
            if cid not in ids:
                continue
            if isinstance(val, str):
                box = _side_box(val, w, h)
                if box is not None:
                    layout[cid] = box
            else:
                box = _coerce_box(val, w, h)
                if box is not None:
                    layout[cid] = box
    for turn in turns:
        cid, _ = _resolve_turn_face(slug, turn)
        if cid not in ids:
            continue
        box = _side_box(turn.get("side"), w, h)
        if box is not None:
            layout.setdefault(cid, box)
        box = _coerce_box(turn.get("box"), w, h)
        if box is not None:
            layout.setdefault(cid, box)
    return layout


def _lock_dual_speaker_layout(
    slug: str,
    video_base: Path,
    turns: list[dict[str, Any]],
    *,
    tmp: Path,
    shot: dict[str, Any] | None = None,
) -> dict[str, tuple[float, float, float, float]]:
    """Map each speaker to a fixed head box for the whole shot.

    Priority (industry order):
      1. Explicit director layout (shot.lip_layout / turn.side / turn.box).
      2. ArcFace identity lock against each character's locked 定妆图.
      3. Color heuristic (pink vs cool) — last resort, still locked once.
    """
    ids: list[str] = []
    faces: dict[str, str] = {}
    for turn in turns:
        cid, face_ref = _resolve_turn_face(slug, turn)
        if not cid:
            continue
        if cid not in ids:
            ids.append(cid)
            faces[cid] = face_ref
    if len(ids) < 2:
        return {}

    t0 = float(turns[0].get("start") or 0.0) if turns else 0.0
    frame = tmp / "layout_lock.jpg"
    if not _sample_frame(video_base, t0, frame):
        if not _sample_frame(video_base, max(0.0, t0 + 0.12), frame):
            return {}

    try:
        from PIL import Image
        import numpy as np
    except Exception:
        return {}
    try:
        frame_arr = np.array(Image.open(frame).convert("RGB"))
    except Exception:
        return {}
    h, w = frame_arr.shape[:2]

    # 1) Explicit director override — deterministic, no heuristics.
    layout = _explicit_layout(slug, shot, turns, ids, w, h)
    if len(layout) >= 2:
        _set_layout_source(shot, "director")
        return layout

    # 2) Identity lock via ArcFace (robust to lighting/clothing chroma flips).
    #    InsightFace expects BGR; the color heuristic below wants RGB, so convert.
    try:
        frame_bgr = frame_arr[:, :, ::-1]
        layout = _identity_layout_lock(frame_bgr, w, h, ids, faces, slug)
        if len(layout) >= 2:
            _set_layout_source(shot, "arcface")
            return layout
    except Exception:
        pass

    # 3) Color heuristic fallback (no ArcFace). Decide once on the early plate frame.
    _lip_warn(shot, "多人口型：ArcFace 身份锁不可用，已降级为颜色启发式定位（可能锁错脸）")
    left, right = _dual_speaker_candidate_boxes(w, h)
    pink_l = _box_pink_frac(frame_arr, left)
    pink_r = _box_pink_frac(frame_arr, right)
    pink_side, cool_side = (left, right) if pink_l >= pink_r else (right, left)

    warm: list[str] = []
    cool: list[str] = []
    palettes: dict[str, list[tuple[int, int, int]]] = {}
    try:
        from tools.drama_characters import find_character, load_characters

        cards = load_characters(slug)
    except Exception:
        cards = []
        find_character = None  # type: ignore

    for cid in ids:
        palette: list[tuple[int, int, int]] = []
        if find_character and cards:
            char = find_character(cards, cid)
            if char:
                palette = _parse_hex_colors(str(char.get("colors") or ""))
        palettes[cid] = palette
        if palette and _palette_wants_warm_accent(palette):
            warm.append(cid)
        else:
            cool.append(cid)

    layout: dict[str, tuple[float, float, float, float]] = {}
    # Classic 2-hander: one warm (粉裙) + one cool (白衣/墨发) → pink / other.
    if len(ids) == 2 and len(warm) == 1 and len(cool) == 1:
        layout[warm[0]] = pink_side
        layout[cool[0]] = cool_side
        _set_layout_source(shot, "color")
        return layout

    # Same-class or 3+: affinity rank against L/R, greedy unique assignment.
    unused = [left, right]
    scored: list[tuple[float, str]] = []
    for cid in ids:
        pal = palettes.get(cid) or []
        if not pal:
            scored.append((-1.0, cid))
            continue
        a_l = _box_color_affinity(frame_arr, left, pal)
        a_r = _box_color_affinity(frame_arr, right, pal)
        scored.append((max(a_l, a_r), cid))
    scored.sort(reverse=True)
    for _, cid in scored:
        if not unused:
            break
        pal = palettes.get(cid) or []
        if pal:
            best = max(unused, key=lambda b: _box_color_affinity(frame_arr, b, pal))
        elif cid in warm:
            best = pink_side if pink_side in unused else unused[0]
        else:
            best = cool_side if cool_side in unused else unused[0]
        layout[cid] = best
        unused = [b for b in unused if b is not best and b != best]
    if len(layout) >= 2:
        _set_layout_source(shot, "color")
    else:
        _lip_warn(shot, "多人口型：颜色启发式未能定位出两张脸")
    return layout


def _find_turn_face_box(
    slug: str,
    video_base: Path,
    turn: dict[str, Any],
    *,
    start: float,
    end: float,
    tmp: Path,
    turn_index: int,
    layout: dict[str, tuple[float, float, float, float]] | None = None,
) -> tuple[float, float, float, float] | None:
    """Return the speaker head box — prefer shot-locked layout over per-frame guess."""
    cid, face_ref = _resolve_turn_face(slug, turn)
    if layout and cid and cid in layout:
        return layout[cid]
    if not (cid or face_ref):
        return None
    span = max(end - start, 0.1)
    sample_offsets = (
        0.0,
        0.04,
        0.08,
        0.12,
        min(0.35, span * 0.15),
        span * 0.35,
        span * 0.55,
    )
    for off in sample_offsets:
        t = start + off
        if t >= end:
            continue
        frame = tmp / f"f{turn_index:02d}_{int(off * 100):03d}.jpg"
        if not _sample_frame(video_base, t, frame):
            continue
        box = _speaker_face_crop_box(frame, slug, cid, face_ref=face_ref)
        if box:
            return box
    return None


def _timed_turns_for_lip(
    shot: dict[str, Any], *, voice_path=None, slug: str = ""
) -> list[dict[str, Any]]:
    from tools.drama_dialogue import (
        build_dialogue_track,
        infer_turn_timings_from_voice,
        normalize_dialogue_track,
    )

    track = normalize_dialogue_track(shot.get("dialogue_track"))
    turns = list(track.get("turns") or [])
    has_timings = any(float(t.get("end") or 0) > float(t.get("start") or 0) for t in turns)
    if len(turns) >= 2 and has_timings:
        return turns

    raw = list(shot.get("voice_turns") or [])
    if len(raw) >= 2 and any(float(r.get("end") or 0) > float(r.get("start") or 0) for r in raw):
        return [
            {
                "index": i,
                "speaker": r.get("speaker") or "",
                "character_id": r.get("character_id") or "",
                "character_name": r.get("character_name") or r.get("speaker") or "",
                "start": float(r.get("start") or 0),
                "end": float(r.get("end") or 0),
            }
            for i, r in enumerate(raw)
            if isinstance(r, dict)
        ]

    # Rebuild track from script + recover timings from master voice duration
    if len(turns) < 2:
        slug = str(slug or shot.get("_slug") or "")
        if slug:
            from tools.drama_characters import load_characters

            cards = load_characters(slug)
            track = build_dialogue_track(shot, cards, slug=slug)
            turns = list(track.get("turns") or [])

    if len(turns) >= 2 and voice_path is not None:
        from pathlib import Path

        vp = Path(voice_path)
        if vp.is_file():
            from tools.drama_video import _probe_duration

            dur = float(_probe_duration(vp) or 0)
            if dur > 0:
                track = infer_turn_timings_from_voice(track, dur)
                return list(track.get("turns") or [])
    return []


def try_generate_lip_per_turn(
    slug: str,
    shot: dict[str, Any],
    *,
    scene: Path,
    voice: Path,
    video_base: Path,
    dest: Path,
    provider: str | None,
) -> str:
    """Multi-speaker lip — crop for lock, Poisson mouth blend for seamless plate.

    Why this is the production default for 2+ speakers on WS/MS:
      Full-frame lip often animates the wrong face (e.g. 白若曦 while 白若琳 speaks).
      Rectangular paste-back leaves seams. Industry compromise:
        head-crop → lip model → seamlessClone mouth only onto original motion.
    """
    turns = _timed_turns_for_lip(shot, voice_path=voice, slug=slug)
    if len(turns) < 2:
        return "fallback"

    tmp = dest.parent / f"_lip_turns_{shot.get('n') or 0}"
    tmp.mkdir(parents=True, exist_ok=True)
    parts: list[Path] = []
    sources: list[str] = []
    try:
        # Lock cast→face once for the shot — never re-score per turn mid-dialogue.
        layout = _lock_dual_speaker_layout(slug, video_base, turns, tmp=tmp, shot=shot)
        if not layout or len(layout) < 2:
            _set_layout_source(shot, "none")
            _lip_warn(shot, "多人口型：无法锁定角色方位，逐 turn 检测（可能锁错脸）")
        for i, turn in enumerate(turns):
            start = float(turn.get("start") or 0)
            end = float(turn.get("end") or 0)
            if end <= start + 0.05:
                continue
            seg_v = tmp / f"v{i:02d}.mp4"
            seg_a = tmp / f"a{i:02d}.mp3"
            seg_lip = tmp / f"lip{i:02d}.mp4"
            face_in = tmp / f"face_in{i:02d}.mp4"
            face_out = tmp / f"face_out{i:02d}.mp4"
            composed = tmp / f"comp{i:02d}.mp4"
            if not _ffmpeg_slice(video_base, seg_v, start=start, end=end):
                return "fallback"
            if not _ffmpeg_slice(voice, seg_a, start=start, end=end, audio_only=True):
                return "fallback"

            cid, face_ref = _resolve_turn_face(slug, turn)
            turn_shot = {
                **shot,
                "speaker": turn.get("character_name") or turn.get("speaker") or shot.get("speaker"),
                "n": shot.get("n"),
                "_lip_turn_character_id": cid,
                "_lip_turn_face_ref": face_ref,
            }
            box = _find_turn_face_box(
                slug,
                video_base,
                turn,
                start=start,
                end=end,
                tmp=tmp,
                turn_index=i,
                layout=layout,
            )
            used = False
            if box and _crop_video_box(seg_v, box, face_in):
                src = try_generate_lip(
                    scene,
                    seg_a,
                    face_out,
                    turn_shot,
                    duration=end - start,
                    provider=provider,
                    video_base=face_in,
                )
                if src not in ("fallback", "", None) and face_out.is_file():
                    if _overlay_lip_mouth(seg_v, face_out, box, composed):
                        parts.append(composed)
                        sources.append(str(src))
                        used = True

            if not used:
                # Last resort only — may lock the wrong WS face.
                _lip_warn(shot, f"第 {i + 1} 段口型：人脸裁剪/合成失败，回退全帧逐段口型（可能锁错脸）")
                src = try_generate_lip(
                    scene,
                    seg_a,
                    seg_lip,
                    turn_shot,
                    duration=end - start,
                    provider=provider,
                    video_base=seg_v,
                )
                if src in ("fallback", "", None) or not seg_lip.is_file():
                    return "fallback"
                parts.append(seg_lip)
                sources.append(str(src))

        if not _concat_video_parts(parts, dest):
            return "fallback"
        base = sources[-1] if sources else "latentsync"
        return f"{base}+per_turn" if "+" not in base else base
    finally:
        try:
            for p in tmp.glob("*"):
                try:
                    p.unlink(missing_ok=True)
                except OSError:
                    pass
            tmp.rmdir()
        except OSError:
            pass


def _ensure_dialogue_track_on_shot(slug: str, shot: dict[str, Any], voice: Path) -> None:
    """Persist dialogue_track + voice_turns when lip runs but voice metadata was lost.

    Never invent text-weight timings when ``voice_turns`` already carry real TTS
    segment bounds — those must stay aligned with the master VO file.
    """
    from tools.drama_characters import load_characters
    from tools.drama_dialogue import (
        build_dialogue_track,
        infer_turn_timings_from_voice,
        normalize_dialogue_track,
        track_to_voice_turns,
    )

    stored_turns = list(shot.get("voice_turns") or [])
    stored_ok = (
        len(stored_turns) >= 2
        and any(float(r.get("end") or 0) > float(r.get("start") or 0) for r in stored_turns if isinstance(r, dict))
    )
    track = normalize_dialogue_track(shot.get("dialogue_track"))
    turns = list(track.get("turns") or [])
    has_timings = any(float(t.get("end") or 0) > float(t.get("start") or 0) for t in turns)
    if len(turns) >= 2 and has_timings and stored_ok:
        return

    cards = load_characters(slug)
    track = build_dialogue_track(shot, cards, slug=slug)
    # Prefer existing TTS timings when speaker texts still match the rebuilt track.
    if stored_ok and len(stored_turns) == len(track.get("turns") or []):
        rebuilt = list(track.get("turns") or [])
        texts_match = all(
            str(stored_turns[i].get("text") or "").strip() == str(rebuilt[i].get("text") or "").strip()
            and str(stored_turns[i].get("character_id") or stored_turns[i].get("speaker") or "")
            for i in range(len(rebuilt))
        )
        if texts_match:
            from tools.drama_dialogue import apply_turn_timings

            timed = [
                {
                    "start": float(r.get("start") or 0),
                    "end": float(r.get("end") or 0),
                    "voice": r.get("voice") or "",
                }
                for r in stored_turns
            ]
            track = apply_turn_timings(track, timed)
            shot["dialogue_track"] = track
            shot["voice_turns"] = track_to_voice_turns(track)
            return

    if voice.is_file() and len(track.get("turns") or []) >= 2:
        try:
            from tools.drama_video import _probe_duration

            dur = float(_probe_duration(voice) or 0)
            if dur > 0:
                track = infer_turn_timings_from_voice(track, dur)
        except Exception:
            pass
    shot["dialogue_track"] = track
    shot["voice_turns"] = track_to_voice_turns(track)


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

    if voice.is_file():
        _ensure_dialogue_track_on_shot(slug, shot, voice)

    # 多人口型改为「整镜全帧」单次对口型：不分割（不裁脸/不逐段拼接）、不羽化
    # （不 Poisson 合成）。口型模型直接吃整镜视频 + 完整配音，避免 per-turn 拼接与
    # 合成带来的画面跳动；代价是可能只动一张脸（已记录告警告知导演）。
    if len(_timed_turns_for_lip(shot, voice_path=voice, slug=slug)) >= 2:
        _lip_warn(shot, "多人口型：采用整镜全帧对口型（未按说话人拆分，可能只动一张脸）")
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
            "lip_strategy": "master",
            "lip_layout_source": str(shot.get("lip_layout_source") or ""),
            "lip_warnings": list(shot.get("lip_warnings") or []),
            "lip_degraded": bool(shot.get("lip_degraded")),
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
    _lip_warn(shot, reason)
    shot["lip_score"] = {"status": "skipped", "reason": "fallback", "method": "proxy"}
    return {
        "tried": True,
        "lip_source": "fallback",
        "lip": None,
        "fallback": "still_l0_l1",
        "reason": reason,
        "score": shot["lip_score"],
        "lip_layout_source": str(shot.get("lip_layout_source") or ""),
        "lip_warnings": list(shot.get("lip_warnings") or []),
        "lip_degraded": bool(shot.get("lip_degraded")),
    }
