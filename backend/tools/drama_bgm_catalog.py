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


def _track_public_row(spec: dict[str, Any], *, rel_path: str, procedural: bool = True) -> dict[str, Any]:
    rel = rel_path.replace("\\", "/")
    return {
        "id": spec["id"],
        "title": spec["title"],
        "mood": spec.get("mood") or "",
        "notes": spec.get("notes") or "",
        "path": rel,
        "license": spec["license"],
        "source": "procedural" if procedural else "file",
        "procedural": bool(procedural),
        "preview_url": f"/api/workspace/file?path={quote(rel, safe='/')}",
    }


def _generate_track(dest: Path, spec: dict[str, Any]) -> bool:
    marker = dest.with_suffix(dest.suffix + ".procedural")
    if dest.is_file() and dest.stat().st_size > 2000 and not marker.is_file():
        # User-replaced real file (no procedural marker) — keep it.
        return True
    if dest.is_file() and dest.stat().st_size > 2000 and marker.is_file():
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
    ok = dest.is_file() and dest.stat().st_size > 500
    if ok:
        marker.write_text("lavfi\n", encoding="utf-8")
    return ok


def ensure_shared_bgm_catalog() -> dict[str, Any]:
    bgm_dir = workspace_root() / SHARED_BGM_DIR_REL.replace("/", os.sep)
    bgm_dir.mkdir(parents=True, exist_ok=True)
    tracks: list[dict[str, Any]] = []
    for spec in _TRACK_SPECS:
        rel = f"{SHARED_BGM_DIR_REL}/{spec['filename']}"
        dest = bgm_dir / spec["filename"]
        marker = dest.with_suffix(dest.suffix + ".procedural")
        _generate_track(dest, spec)
        if dest.is_file() and dest.stat().st_size > 500:
            tracks.append(
                _track_public_row(spec, rel_path=rel, procedural=marker.is_file())
            )
    catalog = {"tracks": tracks, "version": 2}
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
            procedural = bool(item.get("procedural"))
            if "procedural" not in item:
                # Infer from sibling marker when catalog is stale.
                try:
                    p = resolve_safe(path_rel)
                    procedural = p.with_suffix(p.suffix + ".procedural").is_file()
                except ValueError:
                    procedural = True
            row = {
                "id": tid,
                "title": str(item.get("title") or tid),
                "mood": str(item.get("mood") or ""),
                "notes": str(item.get("notes") or ""),
                "path": path_rel,
                "license": str(item.get("license") or f"catalog:{tid}"),
                "source": "procedural" if procedural else str(item.get("source") or "file"),
                "procedural": procedural,
                "preview_url": f"/api/workspace/file?path={quote(path_rel, safe='/')}",
            }
            out.append(row)
    return out


def match_bgm_by_intent(intent: str, tracks: list[dict[str, Any]] | None = None) -> str:
    """Pick catalog id by mood/keywords in script 配乐 intent. Prefer non-procedural."""
    text = str(intent or "").strip().lower()
    rows = list(tracks or load_shared_catalog())
    if not rows:
        return ""

    def _score_row(row: dict[str, Any]) -> tuple[int, int, str]:
        tid = str(row.get("id") or "").strip()
        if not tid:
            return (-1, 1, "")
        mood = str(row.get("mood") or "")
        blob = f"{mood} {row.get('title') or ''} {row.get('notes') or ''}".lower()
        score = 0
        if text:
            if mood and mood in text:
                score += 5
            for mood_name, keys in mood_aliases:
                if mood == mood_name or mood_name in blob:
                    score += sum(2 for k in keys if k in text)
        # Prefer real uploaded/replaced stems over lavfi procedural.
        real_bonus = 0 if bool(row.get("procedural")) else 1000
        return (score + real_bonus, 0 if not row.get("procedural") else 1, tid)

    mood_aliases: list[tuple[str, tuple[str, ...]]] = [
        ("悬疑", ("悬疑", "紧张", "暗", "神秘", "惊悚", "危险")),
        ("励志", ("励志", "决意", "觉醒", "希望", "重生", "温暖上升")),
        ("对峙", ("对峙", "交锋", "对抗", "冲突", "暗战")),
        ("压抑", ("压抑", "沉重", "权谋", "豪门", "阴冷")),
        ("轻快", ("轻快", "日常", "甜", "轻松", "明亮", "欢快")),
        ("高潮", ("高潮", "复仇", "终局", "爆发", "激昂")),
    ]
    ranked = [_score_row(row) for row in rows]
    ranked = [r for r in ranked if r[2]]
    if not ranked:
        return ""
    ranked.sort(key=lambda x: (-x[0], x[1], x[2]))
    # If intent scored nothing on real tracks, still prefer any real track over lavfi.
    best = ranked[0]
    if text and best[0] < 1000:
        real = [r for r in ranked if r[1] == 0]
        if real:
            return real[0][2]
    if not text:
        real = [r for r in ranked if r[1] == 0]
        if real:
            return real[0][2]
        return ranked[0][2]
    if best[0] % 1000 > 0 or best[0] >= 1000:
        return best[2]
    return ranked[0][2]
