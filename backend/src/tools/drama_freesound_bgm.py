"""Fetch royalty-free BGM from Freesound into the shared catalog.

Uses the same Freesound APIv2 as common Freesound MCP servers (search + preview
download). Prefers Creative Commons 0; falls back to Attribution (CC-BY) with
attribution recorded beside each track.

Requires ``FREESOUND_API_KEY`` (https://freesound.org/apiv2/apply/).
"""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx

from tools.drama_bgm_catalog import SHARED_BGM_DIR_REL, _TRACK_SPECS, ensure_shared_bgm_catalog
from tools.workspace import resolve_safe, workspace_root

log = logging.getLogger("tools.drama_freesound")

API_BASE = "https://freesound.org/apiv2"
# CC0 only for commercial short-drama by default; Attribution needs credit.
LICENSE_CC0 = 'license:"Creative Commons 0"'
LICENSE_BY = 'license:"Attribution"'

MOOD_QUERIES: dict[str, dict[str, str]] = {
    "suspense_dark": {
        "query": "dark suspense ambient drone",
        "filter_extra": "tag:ambient OR tag:drone OR tag:dark",
    },
    "rebirth_resolve": {
        "query": "hopeful inspiring ambient music",
        "filter_extra": "tag:ambient OR tag:music OR tag:hope",
    },
    "sisters_rivalry": {
        "query": "tense pulse conflict ambient",
        "filter_extra": "tag:tension OR tag:pulse OR tag:dark",
    },
    "luxury_oppress": {
        "query": "dark luxury cinematic ambient",
        "filter_extra": "tag:cinematic OR tag:dark OR tag:ambient",
    },
    "sweet_daily": {
        "query": "light cheerful soft music loop",
        "filter_extra": "tag:music OR tag:loop OR tag:happy",
    },
    "revenge_climax": {
        "query": "epic dark climax cinematic",
        "filter_extra": "tag:cinematic OR tag:epic OR tag:dark",
    },
}


def freesound_api_key() -> str:
    try:
        from config import config

        return str(getattr(config, "FREESOUND_API_KEY", "") or os.getenv("FREESOUND_API_KEY", "")).strip()
    except Exception:
        return str(os.getenv("FREESOUND_API_KEY", "") or "").strip()


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Token {token}"}


def search_freesound(
    query: str,
    *,
    token: str,
    page_size: int = 8,
    license_pref: str = "cc0",
    duration_min: float = 20.0,
    duration_max: float = 180.0,
    filter_extra: str = "",
) -> list[dict[str, Any]]:
    """Search Freesound; return raw result rows with previews."""
    lic = LICENSE_CC0 if license_pref == "cc0" else LICENSE_BY
    filt = f"{lic} duration:[{duration_min:.0f} TO {duration_max:.0f}]"
    if filter_extra.strip():
        filt = f"{filt} ({filter_extra.strip()})"
    params = {
        "query": query,
        "page_size": max(1, min(int(page_size), 30)),
        "filter": filt,
        "fields": "id,name,duration,license,previews,username,url,tags,download",
        "sort": "rating_desc",
    }
    url = f"{API_BASE}/search/text/"
    with httpx.Client(timeout=45.0) as client:
        resp = client.get(url, params=params, headers=_headers(token))
        if resp.status_code == 401:
            raise RuntimeError("Freesound API Key 无效，请到 https://freesound.org/apiv2/apply/ 申请")
        if resp.status_code >= 400:
            raise RuntimeError(f"Freesound 搜索失败 HTTP {resp.status_code}: {(resp.text or '')[:200]}")
        data = resp.json()
    rows = data.get("results") if isinstance(data, dict) else None
    return [r for r in (rows or []) if isinstance(r, dict)]


def _preview_url(row: dict[str, Any]) -> str:
    previews = row.get("previews") if isinstance(row.get("previews"), dict) else {}
    return str(
        previews.get("preview-hq-mp3")
        or previews.get("preview-lq-mp3")
        or previews.get("preview-hq-ogg")
        or ""
    ).strip()


def _safe_filename(name: str) -> str:
    base = re.sub(r"[^\w\-]+", "_", str(name or "track"), flags=re.UNICODE).strip("_")
    return (base or "track")[:80]


def download_preview(url: str, dest: Path, *, token: str = "") -> bool:
    dest.parent.mkdir(parents=True, exist_ok=True)
    headers = _headers(token) if token else {}
    with httpx.Client(timeout=120.0, follow_redirects=True) as client:
        resp = client.get(url, headers=headers)
        if resp.status_code >= 400 or not resp.content or len(resp.content) < 2000:
            return False
        dest.write_bytes(resp.content)
    return dest.is_file() and dest.stat().st_size > 2000


def _write_attribution(dest: Path, row: dict[str, Any], *, catalog_id: str) -> Path:
    meta = {
        "catalog_id": catalog_id,
        "freesound_id": row.get("id"),
        "name": row.get("name"),
        "username": row.get("username"),
        "license": row.get("license"),
        "url": row.get("url"),
        "duration": row.get("duration"),
        "tags": row.get("tags") or [],
        "attribution": (
            f"\"{row.get('name')}\" by {row.get('username')} "
            f"({row.get('url')}) — {row.get('license')}"
        ),
        "note": "Preview downloaded via Freesound APIv2 for drama catalog (non-procedural).",
    }
    side = dest.with_suffix(dest.suffix + ".freesound.json")
    side.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return side


def install_track_from_row(catalog_id: str, row: dict[str, Any], *, token: str) -> dict[str, Any]:
    """Write preview into shared/audio/bgm/{catalog_id}.mp3 and clear procedural marker."""
    spec = next((s for s in _TRACK_SPECS if s["id"] == catalog_id), None)
    filename = str((spec or {}).get("filename") or f"{catalog_id}.mp3")
    rel = f"{SHARED_BGM_DIR_REL}/{filename}"
    dest = resolve_safe(rel)
    preview = _preview_url(row)
    if not preview:
        raise RuntimeError(f"Freesound #{row.get('id')} 无 preview URL")
    if not download_preview(preview, dest, token=token):
        raise RuntimeError(f"下载 preview 失败：{preview[:80]}")
    marker = dest.with_suffix(dest.suffix + ".procedural")
    if marker.is_file():
        try:
            marker.unlink()
        except OSError:
            pass
    attr = _write_attribution(dest, row, catalog_id=catalog_id)
    return {
        "ok": True,
        "catalog_id": catalog_id,
        "path": rel.replace("\\", "/"),
        "freesound_id": row.get("id"),
        "name": row.get("name"),
        "license": row.get("license"),
        "attribution_path": str(attr).replace("\\", "/"),
        "preview_url": f"/api/workspace/file?path={quote(rel.replace(chr(92), '/'), safe='/')}",
    }


def fetch_one_mood(
    catalog_id: str,
    *,
    token: str | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Search + install one catalog slot. Skip if real file already present unless force."""
    key = (token or freesound_api_key()).strip()
    if not key:
        raise RuntimeError("缺少 FREESOUND_API_KEY")
    spec = next((s for s in _TRACK_SPECS if s["id"] == catalog_id), None)
    if not spec:
        raise ValueError(f"未知曲库 id：{catalog_id}")
    dest = resolve_safe(f"{SHARED_BGM_DIR_REL}/{spec['filename']}")
    marker = dest.with_suffix(dest.suffix + ".procedural")
    if dest.is_file() and dest.stat().st_size > 2000 and not marker.is_file() and not force:
        return {
            "ok": True,
            "skipped": True,
            "catalog_id": catalog_id,
            "path": f"{SHARED_BGM_DIR_REL}/{spec['filename']}",
            "reason": "already_real",
        }

    q = MOOD_QUERIES.get(catalog_id) or {"query": spec.get("mood") or catalog_id, "filter_extra": "tag:music"}
    rows = search_freesound(
        q["query"],
        token=key,
        filter_extra=str(q.get("filter_extra") or ""),
        license_pref="cc0",
    )
    if not rows:
        rows = search_freesound(
            q["query"],
            token=key,
            filter_extra=str(q.get("filter_extra") or ""),
            license_pref="by",
        )
    if not rows:
        raise RuntimeError(f"Freesound 未找到可用曲目：{catalog_id} / {q['query']}")
    # Prefer longer ambient loops.
    rows = sorted(rows, key=lambda r: float(r.get("duration") or 0), reverse=True)
    last_err: Exception | None = None
    for row in rows[:5]:
        try:
            return install_track_from_row(catalog_id, row, token=key)
        except Exception as e:
            last_err = e
            log.warning("install %s from #%s failed: %s", catalog_id, row.get("id"), e)
    raise RuntimeError(str(last_err or f"无法安装 {catalog_id}"))


def fetch_all_catalog_bgm(*, force: bool = False, token: str | None = None) -> dict[str, Any]:
    """Fill all built-in mood slots from Freesound, then refresh catalog.json."""
    key = (token or freesound_api_key()).strip()
    if not key:
        return {"ok": False, "error": "缺少 FREESOUND_API_KEY", "installed": []}
    installed: list[dict[str, Any]] = []
    errors: list[str] = []
    for spec in _TRACK_SPECS:
        cid = str(spec["id"])
        try:
            installed.append(fetch_one_mood(cid, token=key, force=force))
        except Exception as e:
            errors.append(f"{cid}: {e}")
            log.warning("freesound fetch %s failed: %s", cid, e)
    catalog = ensure_shared_bgm_catalog()
    real = sum(1 for t in (catalog.get("tracks") or []) if not t.get("procedural"))
    return {
        "ok": True,
        "installed": installed,
        "errors": errors,
        "real_tracks": real,
        "total": len(_TRACK_SPECS),
        "attribution_index": _write_attribution_index(installed),
    }


def _write_attribution_index(installed: list[dict[str, Any]]) -> str:
    lines = [
        "# Freesound BGM 署名",
        "",
        "以下曲目来自 [Freesound](https://freesound.org/)，请遵守各曲 license。",
        "CC0 可商用免署名；Attribution（CC-BY）需保留作者署名。",
        "",
    ]
    for item in installed:
        if item.get("skipped"):
            continue
        lines.append(
            f"- `{item.get('catalog_id')}`: {item.get('name')} "
            f"(#{item.get('freesound_id')}) — {item.get('license')}"
        )
    rel = f"{SHARED_BGM_DIR_REL}/ATTRIBUTION.md"
    path = resolve_safe(rel)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return rel


def maybe_autofill_from_freesound() -> dict[str, Any] | None:
    """If Key present and catalog still all-procedural, pull CC0/BY previews once."""
    key = freesound_api_key()
    if not key:
        return None
    if os.getenv("DRAMA_FREESOUND_AUTOFILL", "1").strip().lower() in ("0", "false", "no"):
        return None
    try:
        catalog = ensure_shared_bgm_catalog()
        tracks = catalog.get("tracks") or []
        if tracks and any(not t.get("procedural") for t in tracks if isinstance(t, dict)):
            return None
        return fetch_all_catalog_bgm(force=False, token=key)
    except Exception as e:
        log.warning("freesound autofill skipped: %s", e)
        return {"ok": False, "error": str(e)}
