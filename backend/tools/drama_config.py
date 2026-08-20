"""Unified configuration center (R0).

Three-layer coverage (low → high priority):
    ① global presets   backend/data/presets/*.json   (cheap / balanced / pro)
    ② project models   workspace/dramas/{slug}/models.json
    ③ episode/shot     (schema reserved: models.nodes + shot overrides)

For R0, the practical surface is: list presets, switch preset for a project
(baking the preset's node configs into models.json), and read/write a single
node's config. This keeps routing code unchanged while making every node
configurable from the workbench.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tools.drama_models import (
    DEFAULT_PRESET,
    PRESET_IDS,
    load_models,
    normalize_models,
    save_models,
)
from tools.workspace import resolve_safe

# Nodes that can be individually configured. image/motion are per-kind maps;
# others are scalar configs merged directly.
NODE_KEYS = (
    "script",
    "image",
    "motion",
    "lip",
    "tts",
    "subtitle",
    "bgm",
    "sfx",
    "qc",
)

_PRESET_DIR = Path(__file__).resolve().parent.parent / "data" / "presets"


def _preset_path(preset_id: str) -> Path:
    return _PRESET_DIR / f"{preset_id}.json"


def list_presets() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for pid in PRESET_IDS:
        path = _preset_path(pid)
        if not path.is_file():
            continue
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(raw, dict):
            continue
        rows.append(
            {
                "id": raw.get("id") or pid,
                "title": raw.get("title") or pid,
                "tag": raw.get("tag") or "",
                "description": raw.get("description") or "",
            }
        )
    return rows


def load_preset(preset_id: str) -> dict[str, Any]:
    pid = str(preset_id or "").strip().lower()
    if pid not in PRESET_IDS:
        raise ValueError(f"未知预设：{preset_id}，可选 {', '.join(PRESET_IDS)}")
    path = _preset_path(pid)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except OSError as e:
        raise ValueError(f"预设文件不存在：{path}") from e
    except json.JSONDecodeError as e:
        raise ValueError(f"预设文件损坏：{path}") from e
    if not isinstance(raw, dict) or "models" not in raw:
        raise ValueError(f"预设文件格式错误：{path}")
    return raw


def apply_preset(slug: str, preset_id: str) -> dict[str, Any]:
    """Switch a project to a preset: bake its node configs into models.json.

    Research cards (providers) and qc/bgm/sfx already set at project level stay
    untouched; only nodes the preset defines are replaced.
    """
    preset = load_preset(preset_id)
    doc = load_models(slug)
    for node, value in (preset.get("models") or {}).items():
        if node in NODE_KEYS and isinstance(value, dict):
            doc[node] = value
        elif node == "providers":
            # Presets must not override project research cards.
            continue
    doc["preset"] = preset_id
    doc = save_models(slug, doc)
    return {
        "slug": slug,
        "preset": preset_id,
        "title": preset.get("title") or preset_id,
        "description": preset.get("description") or "",
        "models": normalize_models(doc),
    }


def get_config(slug: str) -> dict[str, Any]:
    doc = load_models(slug)
    return {
        "slug": slug,
        "preset": doc.get("preset") or DEFAULT_PRESET,
        "presets": list_presets(),
        "currency": doc.get("currency"),
        "nodes": {node: doc.get(node) for node in NODE_KEYS if node in doc},
        "models": normalize_models(doc),
    }


def put_node_config(slug: str, node: str, value: Any) -> dict[str, Any]:
    if node not in NODE_KEYS:
        raise ValueError(f"未知节点：{node}，可选 {', '.join(NODE_KEYS)}")
    if not isinstance(value, dict):
        raise ValueError("节点配置必须是 JSON 对象")
    doc = load_models(slug)
    current = doc.get(node) if isinstance(doc.get(node), dict) else {}
    merged = {**current, **value}
    doc[node] = merged
    doc = save_models(slug, doc)
    return {
        "slug": slug,
        "node": node,
        "value": doc.get(node),
        "models": normalize_models(doc),
    }