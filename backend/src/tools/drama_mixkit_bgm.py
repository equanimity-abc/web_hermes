"""Fetch royalty-free BGM from Mixkit into the shared catalog.

No API key / sign-up. Mixkit Free Stock Music license allows commercial use
(YouTube / social / ads) without attribution. See https://mixkit.co/license/

CDN pattern discovered from mood listing pages:
  https://assets.mixkit.co/music/{id}/{id}.mp3
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any
from urllib.parse import quote

import httpx

from tools.drama_bgm_catalog import SHARED_BGM_DIR_REL, _TRACK_SPECS, ensure_shared_bgm_catalog
from tools.workspace import resolve_safe

log = logging.getLogger("tools.drama_mixkit")

USER_AGENT = "Mozilla/5.0 (compatible; DramaBGMBot/1.0; +local)"
MOOD_PAGES: dict[str, list[str]] = {
    # catalog_id -> Mixkit mood slug candidates (first page with tracks wins)
    "suspense_dark": ["mysterious", "dark", "dramatic"],
    "rebirth_resolve": ["calm", "inspirational", "happy"],
    "sisters_rivalry": ["dramatic", "dark", "mysterious"],
    "luxury_oppress": ["dark", "mysterious", "sad"],
    "sweet_daily": ["happy", "playful", "upbeat", "romantic"],
    "revenge_climax": ["epic", "dramatic", "dark"],
}

_MP3_RE = re.compile(r"https://assets\.mixkit\.co/music/(\d+)/\1\.mp3")
_CARD_RE = re.compile(
    r'data-audio-player-item-id-value="(?P<id>\d+)"[\s\S]{0,2500}?'
    r'class="item-grid-card__title"\s*>\s*(?P<title>[^<]+?)\s*<'
    r'(?:[\s\S]{0,400}?class="item-grid-music-preview__author"\s*>\s*(?P<author>[^<]+?)\s*<)?',
    re.IGNORECASE,
)

KNOWN_MOODS = (
    "dark",
    "happy",
    "epic",
    "calm",
    "dramatic",
    "romantic",
    "upbeat",
    "sad",
    "mysterious",
    "inspirational",
    "playful",
)
KNOWN_TAGS = (
    "cinematic",
    "ambient",
    "piano",
    "guitar",
    "drums",
    "electronic",
    "hip-hop",
    "pop",
    "rock",
    "jazz",
    "lo-fi",
    "corporate",
    "trap",
    "beats",
)


def _slugify(text: str) -> str:
    s = str(text or "").strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s


def _parse_music_page(html: str, *, page_url: str, kind: str, slug: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[int] = set()
    for m in _CARD_RE.finditer(html or ""):
        sid = int(m.group("id"))
        if sid in seen:
            continue
        seen.add(sid)
        title = str(m.group("title") or "").strip()
        author = str(m.group("author") or "").strip()
        if author.lower().startswith("by "):
            author = author[3:].strip()
        out.append(
            {
                "id": sid,
                "title": title or f"Mixkit #{sid}",
                "author": author,
                "kind": kind,
                "slug": slug,
                "download_url": f"https://assets.mixkit.co/music/{sid}/{sid}.mp3",
                "page_url": page_url,
                "license": "Mixkit Stock Music Free License",
                "license_url": "https://mixkit.co/license/#musicFree",
            }
        )
    if out:
        return out
    # Fallback: ids only (older markup)
    for sid_s in dict.fromkeys(_MP3_RE.findall(html or "")):
        sid = int(sid_s)
        out.append(
            {
                "id": sid,
                "title": f"Mixkit #{sid}",
                "author": "",
                "kind": kind,
                "slug": slug,
                "download_url": f"https://assets.mixkit.co/music/{sid}/{sid}.mp3",
                "page_url": page_url,
                "license": "Mixkit Stock Music Free License",
                "license_url": "https://mixkit.co/license/#musicFree",
            }
        )
    return out


def list_mixkit_page(kind: str, slug: str, *, limit: int = 24) -> list[dict[str, Any]]:
    """kind: mood | tag"""
    slug = _slugify(slug)
    if not slug:
        return []
    if kind == "tag":
        url = f"https://mixkit.co/free-stock-music/tag/{slug}/"
    else:
        url = f"https://mixkit.co/free-stock-music/mood/{slug}/"
        kind = "mood"
    with httpx.Client(timeout=45.0, follow_redirects=True, headers={"User-Agent": USER_AGENT}) as client:
        resp = client.get(url)
        if resp.status_code >= 400:
            return []
        rows = _parse_music_page(resp.text, page_url=url, kind=kind, slug=slug)
    return rows[: max(1, int(limit))]


def list_mixkit_mood_tracks(mood_slug: str, *, limit: int = 12) -> list[dict[str, Any]]:
    return list_mixkit_page("mood", mood_slug, limit=limit)


def search_mixkit(query: str, *, limit: int = 20) -> dict[str, Any]:
    """Realtime search via Mixkit mood/tag pages (site has no public search API).

    Strategy: exact mood → exact tag → keyword-mapped moods/tags → first hit list.
    """
    q = str(query or "").strip()
    if not q:
        return {"ok": False, "error": "query 不能为空", "results": [], "tried": []}
    slug = _slugify(q)
    tried: list[str] = []
    results: list[dict[str, Any]] = []

    def _try(kind: str, s: str) -> bool:
        nonlocal results
        key = f"{kind}:{s}"
        if key in tried or not s:
            return False
        tried.append(key)
        rows = list_mixkit_page(kind, s, limit=limit)
        if rows:
            results = rows
            return True
        return False

    # 1) Exact mood / tag
    if slug in KNOWN_MOODS and _try("mood", slug):
        return {"ok": True, "query": q, "matched": tried[-1], "tried": tried, "results": results[:limit]}
    if _try("tag", slug):
        return {"ok": True, "query": q, "matched": tried[-1], "tried": tried, "results": results[:limit]}
    if _try("mood", slug):
        return {"ok": True, "query": q, "matched": tried[-1], "tried": tried, "results": results[:limit]}

    # 2) Keyword → mood/tag candidates
    blob = f"{q} {slug}".lower()
    mood_hints = [
        ("mysterious", ("悬疑", "神秘", "暗", "dark", "mystery", "suspense")),
        ("dramatic", ("对峙", "戏剧", "dramatic", "conflict", "tense")),
        ("epic", ("高潮", "史诗", "epic", "climax", "revenge", "复仇")),
        ("calm", ("平静", "励志", "希望", "calm", "hope", "inspire", "ambient")),
        ("happy", ("轻快", "甜", "日常", "happy", "sweet", "upbeat", "playful")),
        ("sad", ("压抑", "悲伤", "sad", "melancholy", "oppress")),
        ("romantic", ("浪漫", "romantic", "love")),
        ("dark", ("黑暗", "dark", "horror")),
    ]
    tag_hints = [
        ("cinematic", ("电影", "cinematic", "film", "score")),
        ("ambient", ("氛围", "ambient", "drone", "pad")),
        ("piano", ("钢琴", "piano")),
        ("hip-hop", ("嘻哈", "hip-hop", "hiphop", "rap")),
        ("electronic", ("电子", "electronic", "edm")),
        ("lo-fi", ("lofi", "lo-fi", "lo fi")),
    ]
    for mood, keys in mood_hints:
        if any(k in blob for k in keys) and _try("mood", mood):
            return {"ok": True, "query": q, "matched": tried[-1], "tried": tried, "results": results[:limit]}
    for tag, keys in tag_hints:
        if any(k in blob for k in keys) and _try("tag", tag):
            return {"ok": True, "query": q, "matched": tried[-1], "tried": tried, "results": results[:limit]}

    # 3) Fallback browse popular moods
    for mood in ("mysterious", "dramatic", "happy", "calm", "epic"):
        if _try("mood", mood):
            return {
                "ok": True,
                "query": q,
                "matched": tried[-1],
                "tried": tried,
                "results": results[:limit],
                "hint": "未精确命中，已回退到相近情绪页",
            }
    return {"ok": False, "error": f"未找到：{q}", "query": q, "tried": tried, "results": []}


def download_by_id(
    mixkit_id: int,
    *,
    catalog_id: str = "",
    filename: str = "",
) -> dict[str, Any]:
    """Download one Mixkit track into shared catalog slot or custom filename under shared/audio/bgm/."""
    sid = int(mixkit_id)
    row = {
        "id": sid,
        "mood": "",
        "download_url": f"https://assets.mixkit.co/music/{sid}/{sid}.mp3",
        "page_url": f"https://mixkit.co/free-stock-music/",
        "license": "Mixkit Stock Music Free License",
        "license_url": "https://mixkit.co/license/#musicFree",
        "title": f"Mixkit #{sid}",
    }
    if catalog_id:
        return install_track(str(catalog_id), row)
    name = filename or f"mixkit_{sid}.mp3"
    if not name.lower().endswith(".mp3"):
        name += ".mp3"
    name = re.sub(r"[^\w.\-]+", "_", name)
    rel = f"{SHARED_BGM_DIR_REL}/{name}"
    dest = resolve_safe(rel)
    if not download_url(row["download_url"], dest):
        raise RuntimeError(f"下载失败：Mixkit #{sid}")
    marker = dest.with_suffix(dest.suffix + ".procedural")
    if marker.is_file():
        try:
            marker.unlink()
        except OSError:
            pass
    meta = {
        "source": "mixkit",
        "mixkit_id": sid,
        "download_url": row["download_url"],
        "license": row["license"],
        "license_url": row["license_url"],
    }
    dest.with_suffix(dest.suffix + ".mixkit.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    ensure_shared_bgm_catalog()
    return {
        "ok": True,
        "mixkit_id": sid,
        "path": rel.replace("\\", "/"),
        "preview_url": f"/api/workspace/file?path={quote(rel.replace(chr(92), '/'), safe='/')}",
        "license": row["license"],
    }


def pick_tracks_for_catalog(catalog_id: str) -> list[dict[str, Any]]:
    for mood in MOOD_PAGES.get(catalog_id) or ["dark"]:
        rows = list_mixkit_mood_tracks(mood, limit=10)
        if rows:
            return rows
    return []


def download_url(url: str, dest) -> bool:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with httpx.Client(timeout=120.0, follow_redirects=True, headers={"User-Agent": USER_AGENT}) as client:
        resp = client.get(url)
        if resp.status_code >= 400 or not resp.content or len(resp.content) < 8000:
            return False
        dest.write_bytes(resp.content)
    return dest.is_file() and dest.stat().st_size > 8000


def install_track(catalog_id: str, row: dict[str, Any]) -> dict[str, Any]:
    spec = next((s for s in _TRACK_SPECS if s["id"] == catalog_id), None)
    if not spec:
        raise ValueError(f"未知曲库 id：{catalog_id}")
    filename = str(spec["filename"])
    rel = f"{SHARED_BGM_DIR_REL}/{filename}"
    dest = resolve_safe(rel)
    url = str(row.get("download_url") or "")
    if not url or not download_url(url, dest):
        raise RuntimeError(f"下载失败：{url}")
    marker = dest.with_suffix(dest.suffix + ".procedural")
    if marker.is_file():
        try:
            marker.unlink()
        except OSError:
            pass
    meta = {
        "catalog_id": catalog_id,
        "source": "mixkit",
        "mixkit_id": row.get("id"),
        "title": row.get("title") or "",
        "author": row.get("author") or "",
        "mood": row.get("mood") or row.get("slug") or "",
        "download_url": url,
        "page_url": row.get("page_url"),
        "license": row.get("license"),
        "license_url": row.get("license_url"),
        "attribution": "Mixkit Free Stock Music — attribution appreciated but not required.",
    }
    side = dest.with_suffix(dest.suffix + ".mixkit.json")
    side.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "ok": True,
        "catalog_id": catalog_id,
        "path": rel.replace("\\", "/"),
        "mixkit_id": row.get("id"),
        "mood": row.get("mood"),
        "license": row.get("license"),
        "preview_url": f"/api/workspace/file?path={quote(rel.replace(chr(92), '/'), safe='/')}",
    }


def fetch_one_mood(catalog_id: str, *, force: bool = False) -> dict[str, Any]:
    spec = next((s for s in _TRACK_SPECS if s["id"] == catalog_id), None)
    if not spec:
        raise ValueError(f"未知曲库 id：{catalog_id}")
    dest = resolve_safe(f"{SHARED_BGM_DIR_REL}/{spec['filename']}")
    marker = dest.with_suffix(dest.suffix + ".procedural")
    if dest.is_file() and dest.stat().st_size > 8000 and not marker.is_file() and not force:
        return {
            "ok": True,
            "skipped": True,
            "catalog_id": catalog_id,
            "path": f"{SHARED_BGM_DIR_REL}/{spec['filename']}",
            "reason": "already_real",
        }
    rows = pick_tracks_for_catalog(catalog_id)
    if not rows:
        raise RuntimeError(f"Mixkit 未找到可用曲目：{catalog_id}")
    last_err: Exception | None = None
    for row in rows[:5]:
        try:
            return install_track(catalog_id, row)
        except Exception as e:
            last_err = e
            log.warning("mixkit install %s from #%s failed: %s", catalog_id, row.get("id"), e)
    raise RuntimeError(str(last_err or f"无法安装 {catalog_id}"))


def fetch_all_catalog_bgm(*, force: bool = False) -> dict[str, Any]:
    installed: list[dict[str, Any]] = []
    errors: list[str] = []
    for spec in _TRACK_SPECS:
        cid = str(spec["id"])
        try:
            installed.append(fetch_one_mood(cid, force=force))
        except Exception as e:
            errors.append(f"{cid}: {e}")
            log.warning("mixkit fetch %s failed: %s", cid, e)
    catalog = ensure_shared_bgm_catalog()
    real = sum(1 for t in (catalog.get("tracks") or []) if not t.get("procedural"))
    attr_rel = f"{SHARED_BGM_DIR_REL}/ATTRIBUTION.md"
    lines = [
        "# Mixkit BGM 来源",
        "",
        "曲目来自 [Mixkit Free Stock Music](https://mixkit.co/free-stock-music/)。",
        "适用 [Stock Music Free License](https://mixkit.co/license/#musicFree)：",
        "可用于社交/广告/视频等商业项目，署名非强制。",
        "注意：Mixkit 条款不允许用于独立发行的 CD/DVD、游戏、电视电台广播等（以官网为准）。",
        "",
    ]
    for item in installed:
        if item.get("skipped"):
            continue
        lines.append(
            f"- `{item.get('catalog_id')}`: Mixkit #{item.get('mixkit_id')} "
            f"(mood={item.get('mood')})"
        )
    path = resolve_safe(attr_rel)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return {
        "ok": True,
        "source": "mixkit",
        "installed": installed,
        "errors": errors,
        "real_tracks": real,
        "total": len(_TRACK_SPECS),
        "attribution_index": attr_rel,
    }


def maybe_autofill_from_mixkit() -> dict[str, Any] | None:
    """If catalog is still all-procedural, pull Mixkit free music (no key)."""
    import os

    if os.getenv("DRAMA_MIXKIT_AUTOFILL", "1").strip().lower() in ("0", "false", "no"):
        return None
    try:
        catalog = ensure_shared_bgm_catalog()
        tracks = catalog.get("tracks") or []
        if tracks and any(not t.get("procedural") for t in tracks if isinstance(t, dict)):
            return None
        return fetch_all_catalog_bgm(force=False)
    except Exception as e:
        log.warning("mixkit autofill skipped: %s", e)
        return {"ok": False, "error": str(e)}
