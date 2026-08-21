"""Episode style packs (Q8): LoRA / prompt overlays on the image route table.

One `style_id` per episode. Applying a pack does not rebuild clips.
Dialogue/reaction/action may switch to a character model; establishing stays cheap.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from tools.drama_models import SHOT_KINDS, infer_kind, load_models, normalize_models
from tools.workspace import resolve_safe

_ID_RE = re.compile(r"^[a-z][a-z0-9_-]{0,47}$")
CHAR_KINDS = frozenset({"dialogue", "reaction", "action"})
CHEAP_MODELS = frozenset({"flux-scene", "l0", "mock"})
BUILTIN_DIR = Path(__file__).resolve().parent / "styles"


def parse_style_id(raw: Any) -> str:
    sid = str(raw or "").strip().lower()
    if not sid:
        return ""
    if not _ID_RE.match(sid):
        raise ValueError("style_id 须为小写字母开头的短名")
    return sid


def project_styles_rel(slug: str) -> str:
    return f"dramas/{slug}/styles"


def _read_json(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return raw if isinstance(raw, dict) else {}


def normalize_style(raw: Any) -> dict[str, Any]:
    data = raw if isinstance(raw, dict) else {}
    sid = str(data.get("id") or "").strip().lower()
    if sid and not _ID_RE.match(sid):
        sid = ""
    image_in = data.get("image") if isinstance(data.get("image"), dict) else {}
    image: dict[str, Any] = {}
    for kind in SHOT_KINDS:
        patch = image_in.get(kind) if isinstance(image_in.get(kind), dict) else {}
        if not patch:
            continue
        refs = patch.get("refs") if isinstance(patch.get("refs"), list) else []
        image[kind] = {
            "provider": str(patch.get("provider") or "http"),
            "model": str(patch.get("model") or "").strip(),
            "refs": [str(x).strip() for x in refs if str(x).strip()],
            "lora": str(patch.get("lora") or "").strip(),
            "cost_per_shot": float(patch.get("cost_per_shot") or 0),
        }
    lora_in = data.get("lora") if isinstance(data.get("lora"), dict) else {}
    return {
        "id": sid,
        "title": str(data.get("title") or sid).strip() or sid,
        "prompt": str(data.get("prompt") or "").strip(),
        "negative": str(data.get("negative") or "").strip(),
        "lora": {
            "character": str(lora_in.get("character") or "").strip(),
            "scene": str(lora_in.get("scene") or "").strip(),
        },
        "image": image,
        "builtin": bool(data.get("builtin")),
        "path": str(data.get("path") or ""),
    }


def _iter_style_files(slug: str) -> list[tuple[Path, bool]]:
    out: list[tuple[Path, bool]] = []
    if BUILTIN_DIR.is_dir():
        for path in sorted(BUILTIN_DIR.glob("*.json")):
            out.append((path, True))
    try:
        proj = resolve_safe(project_styles_rel(slug))
    except ValueError:
        proj = None
    if proj is not None and proj.is_dir():
        for path in sorted(proj.glob("*.json")):
            out.append((path, False))
    return out


def list_styles(slug: str) -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    for path, builtin in _iter_style_files(slug):
        rec = normalize_style({**_read_json(path), "path": str(path), "builtin": builtin})
        if rec["id"]:
            by_id[rec["id"]] = rec
    return [by_id[k] for k in sorted(by_id)]


def load_style(slug: str, style_id: str) -> dict[str, Any] | None:
    sid = parse_style_id(style_id)
    if not sid:
        return None
    hit = next((item for item in list_styles(slug) if item["id"] == sid), None)
    return hit


def overlay_style(models: dict[str, Any], style: dict[str, Any] | None) -> dict[str, Any]:
    doc = normalize_models(models)
    if not style or not style.get("id"):
        return doc
    image = dict(doc.get("image") or {})
    incoming = style.get("image") if isinstance(style.get("image"), dict) else {}
    for kind in SHOT_KINDS:
        patch = incoming.get(kind) if isinstance(incoming.get(kind), dict) else None
        if not patch:
            continue
        merged = {**(image.get(kind) or {}), **patch}
        if "cost_per_shot" in patch:
            try:
                merged["cost_per_shot"] = float(patch.get("cost_per_shot") or 0)
            except (TypeError, ValueError):
                pass
        image[kind] = merged
    doc["image"] = image
    doc["style_id"] = style.get("id") or ""
    doc["style_title"] = style.get("title") or ""
    return doc


def effective_models(
    slug: str,
    *,
    episode: int | None = None,
    doc: dict[str, Any] | None = None,
    shot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Full effective model config: project models → style pack → episode/shot overrides."""
    from tools.drama_models import models_with_overrides

    return models_with_overrides(slug, episode=episode, doc=doc, shot=shot)


def image_route(slug: str, shot: dict[str, Any], *, episode: int | None = None, models: dict[str, Any] | None = None) -> dict[str, Any]:
    models = models or effective_models(slug, episode=episode, shot=shot)
    kind = infer_kind(shot)
    route = dict((models.get("image") or {}).get(kind) or {})
    route["kind"] = kind
    return route


def is_character_route(route: dict[str, Any]) -> bool:
    model = str(route.get("model") or "").lower()
    refs = route.get("refs") if isinstance(route.get("refs"), list) else []
    return "char" in model or "lora" in model or "character" in [str(x).lower() for x in refs]


def is_cheap_route(route: dict[str, Any]) -> bool:
    model = str(route.get("model") or "").lower()
    kind = str(route.get("kind") or "")
    if kind in CHAR_KINDS and is_character_route(route):
        return False
    try:
        cost = float(route.get("cost_per_shot") or 0)
    except (TypeError, ValueError):
        cost = 0.0
    return model in CHEAP_MODELS or cost <= 0.05


def estimate_image(
    slug: str,
    shot: dict[str, Any],
    *,
    episode: int | None = None,
    models: dict[str, Any] | None = None,
) -> dict[str, Any]:
    models = models or effective_models(slug, episode=episode, shot=shot)
    route = image_route(slug, shot, episode=episode, models=models)
    try:
        cost = float(route.get("cost_per_shot") or 0)
    except (TypeError, ValueError):
        cost = 0.0
    character = is_character_route(route)
    return {
        "kind": route.get("kind") or infer_kind(shot),
        "provider": str(route.get("provider") or ""),
        "model": str(route.get("model") or ""),
        "lora": str(route.get("lora") or ""),
        "refs": list(route.get("refs") or []) if isinstance(route.get("refs"), list) else [],
        "cost_per_shot": round(cost, 4),
        "currency": str(models.get("currency") or "CNY"),
        "character_model": character,
        "cheap": is_cheap_route(route),
        "style_id": str(models.get("style_id") or ""),
    }


def estimate_episode_image(
    slug: str,
    shots: list[dict[str, Any]],
    *,
    episode: int | None = None,
    doc: dict[str, Any] | None = None,
) -> dict[str, Any]:
    models = effective_models(slug, episode=episode, doc=doc)
    total = 0.0
    char_n = 0
    scene_n = 0
    for shot in shots:
        info = estimate_image(slug, shot, episode=episode, models=models)
        total += float(info.get("cost_per_shot") or 0)
        if info.get("character_model"):
            char_n += 1
        else:
            scene_n += 1
    return {
        "image_estimate": round(total, 4),
        "image_character_shots": char_n,
        "image_scene_shots": scene_n,
        "style_id": str(models.get("style_id") or (doc or {}).get("style_id") or ""),
        "style_title": str(models.get("style_title") or ""),
    }


def style_prompt_clause(slug: str, shot: dict[str, Any], *, episode: int | None = None) -> str:
    models = effective_models(slug, episode=episode)
    style_id = str(models.get("style_id") or "")
    style = load_style(slug, style_id) if style_id else None
    if not style:
        return ""
    kind = infer_kind(shot)
    bits: list[str] = []
    if style.get("prompt"):
        bits.append(str(style["prompt"]))
    route = image_route(slug, shot, episode=episode, models=models)
    lora = str(route.get("lora") or "").strip()
    if not lora:
        pack = style.get("lora") if isinstance(style.get("lora"), dict) else {}
        lora = str(pack.get("character" if kind in CHAR_KINDS else "scene") or "").strip()
    if lora:
        bits.append(f"lora:{lora}")
    if is_character_route(route):
        bits.append("character LoRA / reference model")
    elif str(route.get("model") or ""):
        bits.append(f"scene model {route.get('model')}")
    return ", ".join(bits)


def public_style(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": item.get("id") or "",
        "title": item.get("title") or "",
        "prompt": item.get("prompt") or "",
        "builtin": bool(item.get("builtin")),
    }
