"""Dialogue lip sync — quality-first (LatentSync / PixVerse / self-host).

Pipeline:
  1. Gate: dialogue|reaction CU/MCU/ECU with speaker + dialogue VO
  2. Ensure face **video** base (motion I2V → still-to-video)
  3. Cascade providers for best fidelity (never prefer mock unless allowed)
  4. Score with LSE proxy; clip encode burns subtitles afterwards

Multi-speaker (DialogueTrack mode=multi / lip_strategy=per_turn):
  Run lip **per turn** on the active speaker's face crop, then concat.
  A single master-VO pass locks onto one face and leaves the other speaker's
  mouth wrong — that is the global root cause for two-hander shots.
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
    """
    if not frame.is_file():
        return None
    try:
        from tools.drama_characters import find_character, load_characters, ref_exists, ref_rel
        from tools.drama_qc import _arcface_embedding, _arcface_singleton, _cosine
    except Exception:
        return None

    ref_path: Path | None = None
    if face_ref:
        try:
            cand = resolve_safe(str(face_ref))
            if cand.is_file() and cand.stat().st_size > 32:
                ref_path = cand
        except ValueError:
            ref_path = None
    if ref_path is None and character_id:
        cards = load_characters(slug)
        char = find_character(cards, character_id)
        if char and ref_exists(slug, char):
            try:
                ref_path = resolve_safe(str(char.get("ref") or ref_rel(slug, character_id)))
            except ValueError:
                ref_path = None
    if ref_path is None or not ref_path.is_file():
        return None
    ref_emb, method = _arcface_embedding(ref_path)
    if ref_emb is None or method != "arcface":
        return None
    try:
        import numpy as np
        from PIL import Image

        app = _arcface_singleton()
        img = np.array(Image.open(frame).convert("RGB"))
        h, w = img.shape[:2]
        faces = app.get(img)
        if not faces:
            return None
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
        if best is None or best_score < 0.25:
            return None
        bbox = getattr(best, "bbox", None)
        if bbox is None:
            return None
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
        return None


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
    """Crop video to normalized box and scale back to 9:16 master size."""
    from tools.drama_video import FPS, HEIGHT, WIDTH, _run_ffmpeg

    x, y, bw, bh = box
    dest.parent.mkdir(parents=True, exist_ok=True)
    # Use relative crop expressions
    crop = (
        f"crop=iw*{bw:.4f}:ih*{bh:.4f}:iw*{x:.4f}:ih*{y:.4f},"
        f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase,"
        f"crop={WIDTH}:{HEIGHT},setsar=1,fps={FPS},format=yuv420p"
    )
    try:
        _run_ffmpeg(
            ["-y", "-i", str(video), "-vf", crop, "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(dest)],
            timeout=180,
        )
    except RuntimeError:
        return False
    return dest.is_file() and dest.stat().st_size > 1000


def _overlay_lip_face(
    base_seg: Path,
    lip_face: Path,
    box: tuple[float, float, float, float],
    dest: Path,
) -> bool:
    """Paste lip-synced face crop back onto the original segment framing."""
    from tools.drama_video import _run_ffmpeg

    x, y, bw, bh = box
    dest.parent.mkdir(parents=True, exist_ok=True)
    # Scale lip face to the box size then overlay onto original framing
    filt = (
        f"[1:v][0:v]scale2ref=w=main_w*{bw:.4f}:h=main_h*{bh:.4f}[face][base];"
        f"[base][face]overlay=x=main_w*{x:.4f}:y=main_h*{y:.4f}:shortest=1,format=yuv420p[vout]"
    )
    try:
        _run_ffmpeg(
            [
                "-y",
                "-i",
                str(base_seg),
                "-i",
                str(lip_face),
                "-filter_complex",
                filt,
                "-map",
                "[vout]",
                "-an",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                str(dest),
            ],
            timeout=180,
        )
    except RuntimeError:
        return False
    return dest.is_file() and dest.stat().st_size > 1000


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
    """Multi-speaker lip: each DialogueTrack turn syncs the matched character face.

    Works for 2, 3, or more speakers. Each turn carries character_id + face_ref from
    the character card; ArcFace locks the crop to that 定妆图 before lip sync.
    """
    turns = _timed_turns_for_lip(shot, voice_path=voice, slug=slug)
    if len(turns) < 2:
        return "fallback"

    tmp = dest.parent / f"_lip_turns_{shot.get('n') or 0}"
    tmp.mkdir(parents=True, exist_ok=True)
    parts: list[Path] = []
    sources: list[str] = []
    try:
        for i, turn in enumerate(turns):
            start = float(turn.get("start") or 0)
            end = float(turn.get("end") or 0)
            if end <= start + 0.05:
                continue
            seg_v = tmp / f"v{i:02d}.mp4"
            seg_a = tmp / f"a{i:02d}.mp3"
            seg_lip = tmp / f"lip{i:02d}.mp4"
            if not _ffmpeg_slice(video_base, seg_v, start=start, end=end):
                return "fallback"
            if not _ffmpeg_slice(voice, seg_a, start=start, end=end, audio_only=True):
                return "fallback"

            lip_input = seg_v
            box = None
            cid = ""
            face_ref = ""
            cid, face_ref = _resolve_turn_face(slug, turn)
            face_in = tmp / f"face_in{i:02d}.mp4"
            face_out = tmp / f"face_out{i:02d}.mp4"
            composed = tmp / f"comp{i:02d}.mp4"
            if cid or face_ref:
                frame = tmp / f"f{i:02d}.jpg"
                mid = (start + end) / 2
                if _sample_frame(video_base, mid, frame):
                    box = _speaker_face_crop_box(frame, slug, cid, face_ref=face_ref)
            if box and _crop_video_box(seg_v, box, face_in):
                lip_input = face_in

            turn_shot = {
                **shot,
                "speaker": turn.get("character_name") or turn.get("speaker") or shot.get("speaker"),
                "n": shot.get("n"),
            }
            src = try_generate_lip(
                scene,
                seg_a,
                face_out if lip_input is face_in else seg_lip,
                turn_shot,
                duration=end - start,
                provider=provider,
                video_base=lip_input,
            )
            if src in ("fallback", "", None):
                return "fallback"
            sources.append(str(src))

            if lip_input is face_in and box:
                lip_face = face_out if face_out.is_file() else seg_lip
                if not _overlay_lip_face(seg_v, lip_face, box, composed):
                    # Face paste failed — use full-frame lip on segment
                    src2 = try_generate_lip(
                        scene,
                        seg_a,
                        seg_lip,
                        turn_shot,
                        duration=end - start,
                        provider=provider,
                        video_base=seg_v,
                    )
                    if src2 in ("fallback", "", None) or not seg_lip.is_file():
                        return "fallback"
                    parts.append(seg_lip)
                else:
                    parts.append(composed)
            else:
                if not seg_lip.is_file():
                    return "fallback"
                parts.append(seg_lip)

        if not _concat_video_parts(parts, dest):
            return "fallback"
        # Prefer last successful provider label; mark as per-turn
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
    """Persist dialogue_track + voice_turns when lip runs but voice metadata was lost."""
    from tools.drama_characters import load_characters
    from tools.drama_dialogue import (
        build_dialogue_track,
        infer_turn_timings_from_voice,
        normalize_dialogue_track,
        track_to_voice_turns,
    )

    track = normalize_dialogue_track(shot.get("dialogue_track"))
    turns = list(track.get("turns") or [])
    has_timings = any(float(t.get("end") or 0) > float(t.get("start") or 0) for t in turns)
    if len(turns) >= 2 and has_timings and shot.get("voice_turns"):
        return

    cards = load_characters(slug)
    track = build_dialogue_track(shot, cards, slug=slug)
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
    from tools.drama_dialogue import normalize_dialogue_track
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
    track = normalize_dialogue_track(shot.get("dialogue_track"))
    use_per_turn = (
        str(track.get("lip_strategy") or "") == "per_turn"
        or str(track.get("mode") or "") == "multi"
        or len(_timed_turns_for_lip(shot, voice_path=voice, slug=slug)) >= 2
    )
    source = "fallback"
    if use_per_turn and video_base and video_base.is_file() and voice.is_file():
        source = try_generate_lip_per_turn(
            slug,
            shot,
            scene=scene,
            voice=voice,
            video_base=video_base,
            dest=dest,
            provider=provider,
        )
    if source in ("fallback", "", None):
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
            "lip_strategy": "per_turn" if "per_turn" in str(source) else "master",
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
