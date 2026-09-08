"""Week3 observability: cost_log + failure_heat append-only journals."""

from __future__ import annotations

import json
import threading
from typing import Any

from tools.workspace import resolve_safe

_lock = threading.Lock()


def _cost_rel(slug: str) -> str:
    return f"dramas/{slug}/cost_log.jsonl"


def _heat_rel(slug: str, episode: int) -> str:
    return f"dramas/{slug}/videos/ep{int(episode):02d}/failure_heat.json"


def append_cost_log(
    slug: str,
    *,
    capability: str,
    provider: str,
    model: str = "",
    cost: float = 0.0,
    shot: int | None = None,
    episode: int | None = None,
    ok: bool = True,
    detail: str = "",
) -> None:
    from tools.drama_common import utc_now

    row = {
        "t": utc_now(),
        "capability": str(capability or ""),
        "provider": str(provider or ""),
        "model": str(model or ""),
        "cost": round(float(cost or 0), 4),
        "shot": shot,
        "episode": episode,
        "ok": bool(ok),
        "detail": str(detail or "")[:200],
    }
    path = resolve_safe(_cost_rel(slug))
    path.parent.mkdir(parents=True, exist_ok=True)
    with _lock:
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def bump_failure_heat(
    slug: str,
    episode: int,
    *,
    layer: str,
    provider: str = "",
) -> dict[str, Any]:
    path = resolve_safe(_heat_rel(slug, episode))
    path.parent.mkdir(parents=True, exist_ok=True)
    with _lock:
        data: dict[str, Any] = {"by_layer": {}, "by_provider": {}}
        if path.is_file():
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    data = raw
            except (OSError, json.JSONDecodeError):
                pass
        by_layer = data.setdefault("by_layer", {})
        by_provider = data.setdefault("by_provider", {})
        key = str(layer or "unknown")
        by_layer[key] = int(by_layer.get(key) or 0) + 1
        pid = str(provider or "").strip()
        if pid:
            by_provider[pid] = int(by_provider.get(pid) or 0) + 1
        data["updated_at"] = __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc
        ).isoformat()
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return data


def load_failure_heat(slug: str, episode: int) -> dict[str, Any]:
    path = resolve_safe(_heat_rel(slug, episode))
    if not path.is_file():
        return {"by_layer": {}, "by_provider": {}}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"by_layer": {}, "by_provider": {}}
    return raw if isinstance(raw, dict) else {"by_layer": {}, "by_provider": {}}


def estimate_provider_cost(slug: str, provider: str) -> float:
    try:
        from tools.drama_models import load_models, research_card

        models = load_models(slug)
        card = research_card(models, provider)
        return max(0.0, float(card.get("cost_per_shot") or 0))
    except Exception:
        return 0.0
