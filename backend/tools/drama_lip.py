"""Dialogue-only lip sync (Q2, degraded: mock + http + fallback).

Only `dialogue` CU/MCU with a speaker and VO. Far/crowd/action never run.
Output is shotNN_lip.mp4; clip encode burns subtitles afterwards.
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

LIP_KINDS = frozenset({"dialogue"})
LIP_SIZES = frozenset({"CU", "MCU", "ECU"})
BLOCKED_KINDS = frozenset({"establishing", "crowd", "action", "title", "insert"})


def lip_rel(slug: str, episode: int, n: int) -> str:
    return f"dramas/{slug}/videos/ep{int(episode):02d}/{shot_stem(n)}_lip.mp4"


def lip_eligible(shot: dict[str, Any], *, models: dict[str, Any] | None = None) -> dict[str, Any]:
    kind = infer_kind(shot)
    size = infer_size(shot)
    speaker = infer_speaker(shot)
    roles = shot.get("角色") or []
    role_n = len(roles) if isinstance(roles, list) else len([x for x in str(roles).split(",") if x.strip()])
    dialogue = str(shot.get("对白") or "").strip()
    only_kinds = list(((models or {}).get("lip") or {}).get("only_kinds") or list(LIP_KINDS))
    if kind in BLOCKED_KINDS or (only_kinds and kind not in only_kinds):
        return {"ok": False, "reason": f"{kind} 镜不开口型"}
    if kind not in LIP_KINDS:
        return {"ok": False, "reason": "仅 dialogue 镜可生成口型"}
    if size not in LIP_SIZES:
        return {"ok": False, "reason": f"{size} 景别不开口型（需要 CU/MCU）"}
    if not speaker:
        return {"ok": False, "reason": "没有 speaker，不准接口型"}
    if role_n > 1 and not speaker:
        return {"ok": False, "reason": "多角色同框未指定 speaker"}
    if not dialogue:
        return {"ok": False, "reason": "没有对白"}
    return {"ok": True, "reason": "", "kind": kind, "size": size, "speaker": speaker}


def estimate_lip(slug: str, shot: dict[str, Any], *, models: dict[str, Any] | None = None) -> dict[str, Any]:
    models = models or load_models(slug)
    gate = lip_eligible(shot, models=models)
    currency = str(models.get("currency") or "CNY")
    wanted = str((models.get("lip") or {}).get("provider") or "musetalk")
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
    return (os.getenv("LIP_PROVIDER") or getattr(config, "LIP_PROVIDER", "") or "mock").strip().lower()


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
    url = (getattr(config, "LIP_API_URL", "") or os.getenv("LIP_API_URL") or "").strip()
    if not url:
        return False
    try:
        import httpx

        with httpx.Client(timeout=180.0, follow_redirects=True) as client:
            with scene.open("rb") as img, voice.open("rb") as aud:
                resp = client.post(
                    url,
                    files={
                        "image": (scene.name, img, "image/png"),
                        "audio": (voice.name, aud, "audio/mpeg"),
                    },
                    data={
                        "duration": str(duration),
                        "speaker": str(shot.get("speaker") or ""),
                    },
                    headers={"User-Agent": "my-tiktok-video-agent/0.8"},
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
) -> str:
    if not scene.is_file():
        return "fallback"
    if not voice.is_file() or voice.stat().st_size < 80:
        return "fallback"
    if not shutil.which(_ffmpeg_bin()):
        return "fallback"
    provider = _provider()
    from tools.providers import registry

    if provider in ("fail", "none", "off"):
        return "fallback"
    if registry.has("lip", provider):
        return registry.dispatch("lip", provider, scene, voice, dest, shot, duration)
    # Unknown provider: try http adapter, then local mock.
    if _http_lip(scene, voice, dest, shot, duration):
        return "http"
    return "mock" if _mock_lip(scene, voice, dest, duration) else "fallback"


def generate_shot_lip(
    slug: str,
    episode: int,
    shot: dict[str, Any],
    *,
    force: bool = False,
) -> dict[str, Any]:
    models = load_models(slug)
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
    source = try_generate_lip(scene, voice, dest, shot, duration=duration)
    shot["lip_source"] = source
    score = None
    if source != "fallback" and dest.is_file():
        score = score_lip(dest, voice if voice.is_file() else None)
        shot["lip_score"] = score
        return {
            "tried": True,
            "lip_source": source,
            "lip": rel,
            "score": score,
            "reason": "",
        }
    if dest.exists():
        try:
            dest.unlink()
        except OSError:
            pass
    shot["lip_score"] = {"status": "skipped", "reason": "fallback", "method": "proxy"}
    return {
        "tried": True,
        "lip_source": "fallback",
        "lip": None,
        "fallback": "still_l0_l1",
        "reason": "口型失败，回退闭口静图",
        "score": shot["lip_score"],
    }
