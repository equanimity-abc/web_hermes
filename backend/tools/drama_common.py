"""Shared drama helpers (P2-13).

Single source for reusable pieces previously duplicated across studio /
routes / plugin: slug/episode/shot parsing, the two exception types used for
HTTP mapping, a slug regex, and a UTC timestamp helper.

``drama_studio`` re-exports these names for backward compatibility, so existing
``from tools.drama_studio import DramaNotFound, parse_episode`` imports keep
working.
"""

from __future__ import annotations

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