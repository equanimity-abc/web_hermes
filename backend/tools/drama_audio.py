"""Episode audio bus (Q1): BGM stems, license gate, duck, mix at assemble only.

BGM is never burned into per-shot clip.mp4. Changing the track remixes
epNN.mp4 from the VO stem without touching source clips.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any
from urllib.parse import quote

from tools.workspace import resolve_safe

LICENSE_USER = "user_upload"
DEFAULT_DUCK_DB = -12.0
DEFAULT_BGM_VOLUME = 0.22
DEFAULT_FADE_IN = 0.35
DEFAULT_FADE_OUT = 0.7
AUDIO_SUFFIXES = {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac"}
MAX_BGM_BYTES = 20 * 1024 * 1024


def mix_rel(slug: str, episode: int) -> str:
    return f"dramas/{slug}/videos/ep{int(episode):02d}/mix.json"


def bgm_rel(slug: str, episode: int) -> str:
    return f"dramas/{slug}/videos/ep{int(episode):02d}/ep_bgm.mp3"


def vo_stem_rel(slug: str, episode: int) -> str:
    return f"dramas/{slug}/videos/ep{int(episode):02d}_vo.mp4"


def catalog_rel(slug: str) -> str:
    return f"dramas/{slug}/audio/catalog.json"


def empty_mix() -> dict[str, Any]:
    return {
        "bgm": {
            "id": "",
            "path": "",
            "title": "",
            "license": "",
            "license_ok": False,
            "volume": DEFAULT_BGM_VOLUME,
            "duck_db": DEFAULT_DUCK_DB,
            "fade_in": DEFAULT_FADE_IN,
            "fade_out": DEFAULT_FADE_OUT,
            "start": 0.0,
        },
        "sfx": [],
    }


def _clip(val: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, val))


def normalize_mix(raw: Any) -> dict[str, Any]:
    base = empty_mix()
    data = raw if isinstance(raw, dict) else {}
    bg = data.get("bgm") if isinstance(data.get("bgm"), dict) else {}
    license_raw = str(bg.get("license") or "").strip()
    volume = DEFAULT_BGM_VOLUME
    duck = DEFAULT_DUCK_DB
    try:
        volume = float(bg.get("volume") if bg.get("volume") is not None else DEFAULT_BGM_VOLUME)
    except (TypeError, ValueError):
        pass
    try:
        duck = float(bg.get("duck_db") if bg.get("duck_db") is not None else DEFAULT_DUCK_DB)
    except (TypeError, ValueError):
        pass
    fade_in = DEFAULT_FADE_IN
    fade_out = DEFAULT_FADE_OUT
    try:
        fade_in = float(bg.get("fade_in") if bg.get("fade_in") is not None else DEFAULT_FADE_IN)
    except (TypeError, ValueError):
        pass
    try:
        fade_out = float(bg.get("fade_out") if bg.get("fade_out") is not None else DEFAULT_FADE_OUT)
    except (TypeError, ValueError):
        pass
    start = 0.0
    try:
        start = float(bg.get("start") or 0)
    except (TypeError, ValueError):
        start = 0.0
    license_ok = bool(bg.get("license_ok"))
    if license_raw.startswith("catalog:"):
        license_ok = True
    base["bgm"] = {
        "id": str(bg.get("id") or "").strip(),
        "path": str(bg.get("path") or "").replace("\\", "/").strip(),
        "title": str(bg.get("title") or "").strip(),
        "license": license_raw,
        "license_ok": license_ok,
        "volume": round(_clip(volume, 0.0, 1.0), 3),
        "duck_db": round(_clip(duck, -24.0, 0.0), 1),
        "fade_in": round(_clip(fade_in, 0.0, 4.0), 2),
        "fade_out": round(_clip(fade_out, 0.0, 6.0), 2),
        "start": round(_clip(start, 0.0, 600.0), 3),
    }
    sfx_in = data.get("sfx") if isinstance(data.get("sfx"), list) else []
    sfx: list[dict[str, Any]] = []
    for item in sfx_in:
        if not isinstance(item, dict):
            continue
        path = str(item.get("path") or "").replace("\\", "/").strip()
        if not path:
            continue
        t = 0.0
        try:
            t = float(item.get("t") or 0)
        except (TypeError, ValueError):
            t = 0.0
        sfx.append(
            {
                "id": str(item.get("id") or "").strip(),
                "path": path,
                "t": round(max(0.0, t), 3),
                "volume": round(_clip(float(item.get("volume") or 1.0), 0.0, 2.0), 3),
            }
        )
    base["sfx"] = sfx
    return base


def load_mix(slug: str, episode: int) -> dict[str, Any]:
    path = resolve_safe(mix_rel(slug, episode))
    if not path.is_file():
        return empty_mix()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raw = {}
    return normalize_mix(raw)


def save_mix(slug: str, episode: int, mix: dict[str, Any]) -> dict[str, Any]:
    doc = normalize_mix(mix)
    path = resolve_safe(mix_rel(slug, episode))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return doc


def load_catalog(slug: str) -> dict[str, Any]:
    path = resolve_safe(catalog_rel(slug))
    if not path.is_file():
        return {"tracks": []}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"tracks": []}
    tracks = raw.get("tracks") if isinstance(raw, dict) else []
    out: list[dict[str, Any]] = []
    if isinstance(tracks, list):
        for item in tracks:
            if not isinstance(item, dict):
                continue
            tid = str(item.get("id") or "").strip()
            if not tid:
                continue
            out.append(
                {
                    "id": tid,
                    "title": str(item.get("title") or tid),
                    "path": str(item.get("path") or "").replace("\\", "/"),
                    "license": str(item.get("license") or f"catalog:{tid}"),
                    "notes": str(item.get("notes") or ""),
                }
            )
    return {"tracks": out}


def has_bgm(mix: dict[str, Any]) -> bool:
    path = str((mix.get("bgm") or {}).get("path") or "")
    if not path:
        return False
    try:
        p = resolve_safe(path)
    except ValueError:
        return False
    return p.is_file() and p.stat().st_size > 0


def license_status(slug: str, mix: dict[str, Any]) -> dict[str, Any]:
    """Return ok/reason. No BGM is always ok (export without music)."""
    bgm = mix.get("bgm") or {}
    path = str(bgm.get("path") or "").strip()
    if not path:
        return {"ok": True, "licensed": False, "reason": "no_bgm", "license": ""}
    lic = str(bgm.get("license") or "").strip()
    if not lic:
        return {"ok": False, "licensed": False, "reason": "没有 license 的曲子禁止导出", "license": ""}
    if lic == LICENSE_USER:
        if bgm.get("license_ok") is True:
            return {"ok": True, "licensed": True, "reason": "user_upload", "license": lic}
        return {"ok": False, "licensed": False, "reason": "上传 BGM 需要勾选「我有商用权」", "license": lic}
    if lic.startswith("catalog:"):
        cid = lic.split(":", 1)[1].strip()
        tracks = load_catalog(slug).get("tracks") or []
        hit = next((t for t in tracks if t.get("id") == cid or t.get("license") == lic), None)
        if hit and str(hit.get("license") or "").startswith("catalog:"):
            return {"ok": True, "licensed": True, "reason": "catalog", "license": lic}
        return {"ok": False, "licensed": False, "reason": f"曲库没有条目：{cid or lic}", "license": lic}
    return {"ok": False, "licensed": False, "reason": f"未知 license：{lic}", "license": lic}


def assert_export_licensed(slug: str, mix: dict[str, Any]) -> None:
    if not has_bgm(mix):
        return
    status = license_status(slug, mix)
    if not status["ok"]:
        raise ValueError(status["reason"])


def public_mix(slug: str, episode: int) -> dict[str, Any]:
    mix = load_mix(slug, episode)
    status = license_status(slug, mix)
    bgm = dict(mix["bgm"])
    bgm_path = str(bgm.get("path") or "")
    file_meta: dict[str, Any] = {"path": bgm_path, "exists": False, "bytes": 0, "url": None}
    if bgm_path:
        try:
            p = resolve_safe(bgm_path)
            if p.is_file():
                file_meta = {
                    "path": bgm_path,
                    "exists": True,
                    "bytes": p.stat().st_size,
                    "url": f"/api/workspace/file?path={quote(bgm_path, safe='/')}",
                }
        except ValueError:
            pass
    return {
        "bgm": bgm,
        "sfx": mix.get("sfx") or [],
        "license": status,
        "file": file_meta,
        "has_bgm": has_bgm(mix),
        "catalog": load_catalog(slug).get("tracks") or [],
        "mix_path": mix_rel(slug, episode),
        "vo_stem": vo_stem_rel(slug, episode),
    }


def patch_mix(slug: str, episode: int, patch: dict[str, Any]) -> dict[str, Any]:
    mix = load_mix(slug, episode)
    bgm = mix["bgm"]
    src = patch.get("bgm") if isinstance(patch.get("bgm"), dict) else patch
    for key in ("id", "path", "title", "license"):
        if key in src and src[key] is not None:
            bgm[key] = src[key]
    if "license_ok" in src:
        bgm["license_ok"] = bool(src["license_ok"])
    for key in ("volume", "duck_db", "fade_in", "fade_out", "start"):
        if key in src and src[key] is not None:
            bgm[key] = src[key]
    if "clear" in patch and patch["clear"]:
        mix["bgm"] = empty_mix()["bgm"]
    if "sfx" in patch and isinstance(patch["sfx"], list):
        mix["sfx"] = patch["sfx"]
    catalog_id = str(patch.get("catalog_id") or src.get("catalog_id") or "").strip()
    if catalog_id:
        tracks = load_catalog(slug).get("tracks") or []
        hit = next((t for t in tracks if t.get("id") == catalog_id), None)
        if hit is None:
            raise ValueError(f"曲库没有条目：{catalog_id}")
        mix["bgm"]["id"] = hit["id"]
        mix["bgm"]["path"] = hit["path"]
        mix["bgm"]["title"] = hit.get("title") or hit["id"]
        mix["bgm"]["license"] = hit.get("license") or f"catalog:{hit['id']}"
        mix["bgm"]["license_ok"] = True
    return save_mix(slug, episode, mix)


def save_uploaded_bgm(
    slug: str,
    episode: int,
    data: bytes,
    *,
    filename: str = "bgm.mp3",
    license_ok: bool = False,
    title: str = "",
) -> dict[str, Any]:
    if not data:
        raise ValueError("空文件")
    if len(data) > MAX_BGM_BYTES:
        raise ValueError("BGM 超过 20MB")
    suffix = Path(filename or "bgm.mp3").suffix.lower() or ".mp3"
    if suffix not in AUDIO_SUFFIXES:
        raise ValueError(f"不支持的音频格式：{suffix}")
    dest_rel = bgm_rel(slug, episode)
    if suffix != ".mp3":
        dest_rel = dest_rel.rsplit(".", 1)[0] + suffix
    dest = resolve_safe(dest_rel)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    mix = load_mix(slug, episode)
    mix["bgm"]["id"] = "upload"
    mix["bgm"]["path"] = dest_rel
    mix["bgm"]["title"] = str(title or Path(filename).stem or "upload")
    mix["bgm"]["license"] = LICENSE_USER
    mix["bgm"]["license_ok"] = bool(license_ok)
    save_mix(slug, episode, mix)
    return load_mix(slug, episode)


def _copy_stem(stem: Path, dest: Path) -> str:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if stem.resolve() == dest.resolve():
        return "same"
    from tools.drama_video import _run_ffmpeg

    try:
        _run_ffmpeg(
            ["-y", "-i", str(stem), "-c", "copy", "-movflags", "+faststart", str(dest)],
            timeout=90,
        )
        return "copy"
    except RuntimeError:
        shutil.copyfile(stem, dest)
        return "copy-file"


def mix_assembled(
    slug: str,
    episode: int,
    *,
    stem: Path,
    dest: Path,
    duration: float | None = None,
) -> str:
    """Remix dest from VO stem + BGM. Does not touch per-shot clips."""
    mix = load_mix(slug, episode)
    if not has_bgm(mix):
        return _copy_stem(stem, dest)
    assert_export_licensed(slug, mix)
    from tools.drama_video import _probe_duration, _run_ffmpeg

    bgm = mix["bgm"]
    bgm_path = resolve_safe(str(bgm["path"]))
    dur = float(duration or _probe_duration(stem) or 1.0)
    vol = float(bgm.get("volume") or DEFAULT_BGM_VOLUME)
    fade_in = float(bgm.get("fade_in") or 0)
    fade_out = float(bgm.get("fade_out") or 0)
    fade_out_start = max(0.0, dur - fade_out)
    start = float(bgm.get("start") or 0)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".mix.tmp.mp4")

    fade_bits = ""
    if fade_in > 0.02:
        fade_bits += f",afade=t=in:st=0:d={fade_in:.2f}"
    if fade_out > 0.02 and fade_out_start > 0:
        fade_bits += f",afade=t=out:st={fade_out_start:.3f}:d={min(fade_out, dur):.2f}"

    duck_db = float(bgm.get("duck_db") if bgm.get("duck_db") is not None else DEFAULT_DUCK_DB)
    ratio = max(2.0, 1.0 + abs(duck_db) / 2.0)
    duck = (
        f"[1:a]aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo,"
        f"atrim=start={start:.3f},asetpts=PTS-STARTPTS,"
        f"aloop=loop=-1:size=2e+09,atrim=0:{dur:.3f},asetpts=PTS-STARTPTS,"
        f"volume={vol:.3f}{fade_bits}[bg];"
        f"[0:a]aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo,asplit=2[vo][sc];"
        f"[bg][sc]sidechaincompress=threshold=0.04:ratio={ratio:.1f}:attack=40:release=280:level_sc=1[ducked];"
        f"[vo][ducked]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[mixed];"
        f"[mixed]loudnorm=I=-14:TP=-1.5:LRA=11[aout]"
    )
    simple = (
        f"[1:a]aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo,"
        f"atrim=start={start:.3f},asetpts=PTS-STARTPTS,"
        f"aloop=loop=-1:size=2e+09,atrim=0:{dur:.3f},asetpts=PTS-STARTPTS,"
        f"volume={vol:.3f}{fade_bits}[bg];"
        f"[0:a]aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo[vo];"
        f"[vo][bg]amix=inputs=2:duration=first:dropout_transition=0:weights=1 0.8[aout]"
    )
    args_common = ["-y", "-i", str(stem), "-i", str(bgm_path)]
    try:
        try:
            _run_ffmpeg(
                [
                    *args_common,
                    "-filter_complex",
                    duck,
                    "-map",
                    "0:v",
                    "-map",
                    "[aout]",
                    "-c:v",
                    "copy",
                    "-c:a",
                    "aac",
                    "-b:a",
                    "160k",
                    "-shortest",
                    "-movflags",
                    "+faststart",
                    str(tmp),
                ],
                timeout=180,
            )
            mode = "duck"
        except RuntimeError:
            _run_ffmpeg(
                [
                    *args_common,
                    "-filter_complex",
                    simple,
                    "-map",
                    "0:v",
                    "-map",
                    "[aout]",
                    "-c:v",
                    "copy",
                    "-c:a",
                    "aac",
                    "-b:a",
                    "160k",
                    "-shortest",
                    "-movflags",
                    "+faststart",
                    str(tmp),
                ],
                timeout=180,
            )
            mode = "amix"
        tmp.replace(dest)
        return mode
    except Exception:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
        raise
