"""Built-in BGM catalog — royalty-free procedural loops for drama assemble."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any
from urllib.parse import quote

from tools.workspace import resolve_safe, workspace_root

SHARED_CATALOG_REL = "shared/audio/catalog.json"
SHARED_BGM_DIR_REL = "shared/audio/bgm"

_TRACK_SPECS: list[dict[str, Any]] = [
    {
        "id": "suspense_dark",
        "title": "暗涌·悬疑紧张",
        "mood": "悬疑",
        "notes": "宫徵低音铺底，适合反转、对峙、暗流涌动",
        "license": "catalog:suspense_dark",
        "filename": "suspense_dark.mp3",
        "lavfi": "aevalsrc=(0.22*sin(2*PI*65.41*t)+0.16*sin(2*PI*98*t)+0.1*sin(2*PI*130.81*t))*(1+0.2*sin(2*PI*0.35*t)):s=44100:d=90",
        "af": "lowpass=f=700,volume=1.4,afade=t=in:st=0:d=2,afade=t=out:st=86:d=4",
    },
    {
        "id": "rebirth_resolve",
        "title": "重生·决意",
        "mood": "励志",
        "notes": "宫角徵和弦，温和上升，适合重生觉醒",
        "license": "catalog:rebirth_resolve",
        "filename": "rebirth_resolve.mp3",
        "lavfi": "aevalsrc=(0.18*sin(2*PI*261.63*t)+0.14*sin(2*PI*329.63*t)+0.12*sin(2*PI*392*t)+0.1*sin(2*PI*523.25*t))*(1+0.15*sin(2*PI*0.5*t)):s=44100:d=90",
        "af": "volume=1.4,aecho=0.6:1.0:120:0.3,afade=t=in:st=0:d=2,afade=t=out:st=86:d=4",
    },
    {
        "id": "sisters_rivalry",
        "title": "姐妹·暗战",
        "mood": "对峙",
        "notes": "商羽五度，紧凑脉冲，适合双女主交锋",
        "license": "catalog:sisters_rivalry",
        "filename": "sisters_rivalry.mp3",
        "lavfi": "aevalsrc=(0.2*sin(2*PI*293.66*t)+0.16*sin(2*PI*440*t))*(1+0.5*sin(2*PI*3*t)):s=44100:d=90",
        "af": "volume=1.4,afade=t=in:st=0:d=1.5,afade=t=out:st=86:d=4",
    },
    {
        "id": "luxury_oppress",
        "title": "豪门·压抑",
        "mood": "压抑",
        "notes": "角羽低音，深沉空间，适合豪宅权谋",
        "license": "catalog:luxury_oppress",
        "filename": "luxury_oppress.mp3",
        "lavfi": "aevalsrc=(0.2*sin(2*PI*82.41*t)+0.14*sin(2*PI*110*t)+0.1*sin(2*PI*164.81*t))*(1+0.15*sin(2*PI*0.25*t)):s=44100:d=90",
        "af": "lowpass=f=900,volume=1.4,aecho=0.5:1.0:200:0.35,afade=t=in:st=0:d=2,afade=t=out:st=86:d=4",
    },
    {
        "id": "sweet_daily",
        "title": "轻甜·日常",
        "mood": "轻快",
        "notes": "宫商角徵高音，明亮轻快，适合日常",
        "license": "catalog:sweet_daily",
        "filename": "sweet_daily.mp3",
        "lavfi": "aevalsrc=(0.16*sin(2*PI*523.25*t)+0.12*sin(2*PI*587.33*t)+0.12*sin(2*PI*659.26*t)+0.08*sin(2*PI*783.99*t))*(1+0.2*sin(2*PI*1.2*t)):s=44100:d=90",
        "af": "volume=1.4,aecho=0.5:1.0:60:0.2,afade=t=in:st=0:d=1,afade=t=out:st=86:d=4",
    },
    {
        "id": "revenge_climax",
        "title": "终局·复仇",
        "mood": "高潮",
        "notes": "徵商低音，强力脉冲，适合复仇高潮",
        "license": "catalog:revenge_climax",
        "filename": "revenge_climax.mp3",
        "lavfi": "aevalsrc=(0.2*sin(2*PI*98*t)+0.16*sin(2*PI*146.83*t))*(1+0.6*sin(2*PI*4*t)):s=44100:d=90",
        "af": "volume=1.4,lowpass=f=600,afade=t=in:st=0:d=1,afade=t=out:st=86:d=4",
    },
]


def _ffmpeg_bin() -> str:
    return os.getenv("FFMPEG_BIN", "ffmpeg")


def _track_public_row(spec: dict[str, Any], *, rel_path: str) -> dict[str, Any]:
    rel = rel_path.replace("\\", "/")
    return {
        "id": spec["id"],
        "title": spec["title"],
        "mood": spec.get("mood") or "",
        "notes": spec.get("notes") or "",
        "path": rel,
        "license": spec["license"],
        "preview_url": f"/api/workspace/file?path={quote(rel, safe='/')}",
    }


def _generate_track(dest: Path, spec: dict[str, Any]) -> bool:
    if dest.is_file() and dest.stat().st_size > 2000:
        return True
    if not shutil.which(_ffmpeg_bin()):
        return False
    from tools.drama_video import _run_ffmpeg

    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        _run_ffmpeg(
            [
                "-y",
                "-f",
                "lavfi",
                "-i",
                str(spec["lavfi"]),
                "-af",
                str(spec["af"]),
                "-c:a",
                "libmp3lame",
                "-b:a",
                "128k",
                str(dest),
            ],
            timeout=120,
        )
    except RuntimeError:
        return False
    return dest.is_file() and dest.stat().st_size > 500


def ensure_shared_bgm_catalog() -> dict[str, Any]:
    bgm_dir = workspace_root() / SHARED_BGM_DIR_REL.replace("/", os.sep)
    bgm_dir.mkdir(parents=True, exist_ok=True)
    tracks: list[dict[str, Any]] = []
    for spec in _TRACK_SPECS:
        rel = f"{SHARED_BGM_DIR_REL}/{spec['filename']}"
        dest = bgm_dir / spec["filename"]
        _generate_track(dest, spec)
        if dest.is_file() and dest.stat().st_size > 500:
            tracks.append(_track_public_row(spec, rel_path=rel))
    catalog = {"tracks": tracks, "version": 1}
    cat_path = workspace_root() / SHARED_CATALOG_REL.replace("/", os.sep)
    cat_path.parent.mkdir(parents=True, exist_ok=True)
    cat_path.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return catalog


def load_shared_catalog() -> list[dict[str, Any]]:
    path = resolve_safe(SHARED_CATALOG_REL)
    if not path.is_file():
        try:
            return list(ensure_shared_bgm_catalog().get("tracks") or [])
        except Exception:
            return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    tracks = raw.get("tracks") if isinstance(raw, dict) else []
    out: list[dict[str, Any]] = []
    if isinstance(tracks, list):
        for item in tracks:
            if not isinstance(item, dict):
                continue
            tid = str(item.get("id") or "").strip()
            path_rel = str(item.get("path") or "").replace("\\", "/")
            if not tid or not path_rel:
                continue
            row = {
                "id": tid,
                "title": str(item.get("title") or tid),
                "mood": str(item.get("mood") or ""),
                "notes": str(item.get("notes") or ""),
                "path": path_rel,
                "license": str(item.get("license") or f"catalog:{tid}"),
                "preview_url": f"/api/workspace/file?path={quote(path_rel, safe='/')}",
            }
            out.append(row)
    return out
