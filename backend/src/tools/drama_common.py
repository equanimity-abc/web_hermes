"""Shared drama helpers (P2-13).

Single source for reusable pieces previously duplicated across studio /
routes / plugin: slug/episode/shot parsing, the two exception types used for
HTTP mapping, a slug regex, and a UTC timestamp helper.

``drama_studio`` re-exports these names for backward compatibility, so existing
``from tools.drama_studio import DramaNotFound, parse_episode`` imports keep
working.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

SLUG_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,39}$")


class DramaNotFound(LookupError):
    pass


class DramaBadRequest(ValueError):
    pass


def parse_slug(raw: str) -> str:
    slug = str(raw or "").strip()
    if not SLUG_RE.match(slug):
        raise DramaBadRequest(
            "slug 须为 1–40 位字母数字、下划线或短横线，且以字母或数字开头"
        )
    return slug


def parse_episode(raw: Any) -> int:
    try:
        n = int(raw)
    except (TypeError, ValueError) as e:
        raise DramaBadRequest("episode 须为正整数 1–99") from e
    if n < 1 or n > 99:
        raise DramaBadRequest("episode 范围 1–99")
    return n


def parse_shot_n(raw: Any) -> int:
    try:
        n = int(raw)
    except (TypeError, ValueError) as e:
        raise DramaBadRequest("shot 须为正整数 1–99") from e
    if n < 1 or n > 99:
        raise DramaBadRequest("shot 范围 1–99")
    return n


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_project_title(title: str) -> str:
    return str(title or "").strip().strip("《》\"'“”‘’")


def _dramas_root() -> str:
    return "dramas"


def load_drama_project_file(name: str) -> dict[str, Any] | None:
    from tools.workspace import resolve_safe

    slug = str(name or "").strip()
    if not slug:
        return None
    path = resolve_safe(f"{_dramas_root()}/{slug}/project.json")
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def project_substance_score(slug: str) -> int:
    """Rough content weight: prefer the working copy over empty restart folders."""
    from tools.workspace import resolve_safe

    try:
        root = resolve_safe(f"{_dramas_root()}/{slug}")
    except Exception:
        return 0
    if not root.is_dir():
        return 0
    score = 0
    try:
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            ext = path.suffix.lower()
            if ext == ".mp4":
                score += 8
            elif ext in {".png", ".jpg", ".jpeg", ".webp"}:
                score += 2
            elif path.name == "shots.json":
                score += 20
            elif path.name in {"characters.json", "project.json"}:
                score += 1
    except OSError:
        return score
    return score


def find_project_slug_by_title(title: str) -> str | None:
    """Exact title match → richest (then newest) non-archived slug."""
    from tools.workspace import resolve_safe

    needle = normalize_project_title(title)
    if not needle:
        return None
    best: tuple[tuple, str] | None = None
    try:
        root = resolve_safe(_dramas_root())
    except Exception:
        return None
    if not root.is_dir():
        return None
    for child in root.iterdir():
        if not child.is_dir() or child.name.startswith("_"):
            continue
        data = load_drama_project_file(child.name)
        if not data or data.get("archived") or data.get("hidden"):
            continue
        t = normalize_project_title(str(data.get("title") or ""))
        if t != needle:
            continue
        sid = str(data.get("slug") or child.name)
        rank = (
            project_substance_score(sid),
            str(data.get("updated_at") or data.get("created_at") or ""),
        )
        if best is None or rank > best[0]:
            best = (rank, sid)
    return best[1] if best else None


def find_project_slug_by_logline(logline: str) -> str | None:
    from tools.workspace import resolve_safe

    needle = str(logline or "").strip()
    if len(needle) < 8:
        return None
    best: tuple[tuple, str] | None = None
    try:
        root = resolve_safe(_dramas_root())
    except Exception:
        return None
    if not root.is_dir():
        return None
    for child in root.iterdir():
        if not child.is_dir() or child.name.startswith("_"):
            continue
        data = load_drama_project_file(child.name)
        if not data or data.get("archived") or data.get("hidden"):
            continue
        if str(data.get("logline") or "").strip() != needle:
            continue
        sid = str(data.get("slug") or child.name)
        rank = (
            project_substance_score(sid),
            str(data.get("updated_at") or data.get("created_at") or ""),
        )
        if best is None or rank > best[0]:
            best = (rank, sid)
    return best[1] if best else None


def http_status(exc: Exception) -> tuple[int, str]:
    """Map a Python exception to (status_code, detail) for FastAPI handlers."""
    if isinstance(exc, DramaNotFound):
        return 404, str(exc)
    if isinstance(exc, DramaBadRequest):
        return 400, str(exc)
    if isinstance(exc, FileNotFoundError):
        return 404, str(exc)
    if isinstance(exc, ValueError):
        return 400, str(exc)
    return 500, str(exc)